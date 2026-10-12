#!/usr/bin/env python3
"""Pi 4 BiteDJ bounded RAM recorder and boot-partition report export."""
import argparse
from collections import deque
import datetime
import glob
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import zipfile

RAM=Path(os.environ.get('BITEDJ_DIAG_RAM','/tmp/bitedj-diag'))
BOOT=Path(os.environ.get('BITEDJ_DIAG_BOOT','/boot/firmware'))
PIDFILE=RAM/'recorder.pid'
HISTORY=600
LOG_LIMIT=1024*1024
MATCH=re.compile(r'mixxx|bitedj|sway|Xwayland|undervolt|thermal-indicat|irq/.*(?:xhci|usb|vc4|v3d|mmc|snd)',re.I)


def read(path,limit=65536):
    try:
        with open(path,'rb') as f:
            return f.read(limit).decode(errors='replace').replace('\x00',' ').strip()
    except (OSError,ValueError):
        return None


def tail(path):
    try:
        with open(path,'rb') as f:
            size=f.seek(0,2);f.seek(max(0,size-LOG_LIMIT));return f.read(LOG_LIMIT)
    except OSError:
        return b''


def command(args):
    try:
        p=subprocess.run(args,capture_output=True,text=True,timeout=3)
        return {'returncode':p.returncode,'stdout':p.stdout[-32768:],'stderr':p.stderr[-4096:]}
    except (OSError,subprocess.TimeoutExpired) as e:
        return {'error':str(e)}


def stamp():
    return {'wall_time':time.time(),'monotonic':time.monotonic()}


def parse_stat(text):
    end=text.rfind(')');f=text[end+2:].split()
    return {'name':text[text.find('(')+1:end],'state':f[0],'utime_ticks':int(f[11]),'stime_ticks':int(f[12]),
            'major_faults':int(f[9]),'start_ticks':int(f[19]),'cpu':int(f[36]),'rt_priority':int(f[37]),'policy':int(f[38])}


def threads():
    result=[]
    for p in Path('/proc').glob('[0-9]*'):
        name=read(p/'comm',128) or ''
        try:executable=os.readlink(p/'exe')
        except OSError:executable=''
        if not MATCH.search(name+' '+executable):continue
        for t in (p/'task').glob('[0-9]*'):
            try:row=parse_stat(read(t/'stat',8192) or '')
            except (ValueError,IndexError):continue
            row.update(pid=int(p.name),tid=int(t.name),process_name=name,executable=executable)
            status=read(t/'status',8192) or ''
            for key in ['Cpus_allowed_list','voluntary_ctxt_switches','nonvoluntary_ctxt_switches']:
                m=re.search(r'^'+key+r':\s*(.*)$',status,re.M);row[key]=m.group(1) if m else None
            row['schedstat']=read(t/'schedstat',128);row['wchan']=read(t/'wchan',128)
            result.append(row)
    return result


def paths(pattern,limit=4096):
    return {p:read(p,limit) for p in sorted(glob.glob(pattern))}


def sample():
    row=stamp()
    row.update(cpu_stat=read('/proc/stat',8192),interrupts=read('/proc/interrupts',24576),
        loadavg=read('/proc/loadavg',256),meminfo=read('/proc/meminfo',4096),diskstats=read('/proc/diskstats',8192),
        pressure={k:read('/proc/pressure/'+k,1024) for k in ['cpu','io','memory']},threads=threads(),
        pcm=paths('/proc/asound/card*/pcm*/sub*/status'),
        temperatures=paths('/sys/class/thermal/thermal_zone*/temp',128),
        clocks=paths('/sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq',128),
        undervoltage=paths('/sys/class/hwmon/hwmon*/in*_lcrit_alarm',128))
    return row


def snapshot():
    files={p:read(p) for p in ['/proc/cmdline','/proc/cpuinfo','/proc/meminfo','/proc/version','/proc/mounts',
        '/proc/asound/cards','/proc/asound/pcm','/proc/asound/seq/clients',
        '/sys/firmware/devicetree/base/model','/sys/devices/system/cpu/isolated','/sys/devices/system/cpu/nohz_full',
        '/proc/sys/kernel/sched_rt_runtime_us','/etc/default/rtirq','/etc/deckshark-release',
        '/root/.mixxx/mixxx.cfg','/etc/deckshark/sway-kiosk.conf','/usr/bin/start-mixxx',
        '/boot/firmware/config.txt','/boot/firmware/cmdline.txt']}
    for pattern in ['/proc/asound/card*/stream*','/proc/asound/card*/pcm*/sub*/hw_params',
        '/proc/asound/card*/pcm*/sub*/sw_params','/proc/irq/*/*affinity*',
        '/sys/devices/system/cpu/cpufreq/policy*/scaling_governor',
        '/sys/devices/system/cpu/cpufreq/policy*/cpuinfo_max_freq','/sys/class/hwmon/hwmon*/name']:
        files.update(paths(pattern))
    for row in threads():
        if row['pid']==row['tid']:
            maps=read('/proc/%s/maps'%row['pid'],512*1024) or ''
            files['/proc/%s/renderer-maps'%row['pid']]='\n'.join(x for x in maps.splitlines() if re.search('dri|mesa|llvm|EGL|OpenGL|wayland',x,re.I))
    usb=[]
    for device in Path('/sys/bus/usb/devices').glob('*'):
        if not (device/'idVendor').exists():continue
        entry={name:read(device/name,512) for name in ['idVendor','idProduct','product','manufacturer','speed','busnum','devnum','power/control']}
        entry['path']=str(device)
        try:entry['driver']=str((device/'driver').resolve(strict=True))
        except OSError:entry['driver']=None
        usb.append(entry)
    pci=[]
    for dev in Path('/sys/bus/pci/devices').glob('*'):
        entry={n:read(dev/n,512) for n in ['vendor','device','class','irq']};entry['path']=str(dev)
        try:entry['driver']=str((dev/'driver').resolve(strict=True))
        except OSError:entry['driver']=None
        pci.append(entry)
    return {'time':stamp(),'uname':list(os.uname()),'files':files,'usb':usb,'pci':pci,
            'sway_outputs':command(['swaymsg','-r','-t','get_outputs']),'clock_ticks_per_second':os.sysconf('SC_CLK_TCK')}


def logs():
    return {name:tail(path) for name,path in {
        'wm.log':RAM/'wm.log','mixxx.log':'/root/.mixxx/mixxx.log','recorder.log':RAM/'recorder.log',
        'dmesg.log':'/var/log/dmesg.log','rtirq.log':'/var/log/rtirq.log',
        'usb-irq-pin.log':'/var/log/usb-irq-pin.log','boot-report.txt':BOOT/'BiteDJ_boot_report.txt'}.items()}


def export(samples,markers,started):
    snap=snapshot();data=logs();unique={}
    for blob in data.values():
        for line in blob.decode(errors='replace').splitlines():
            if 'BITEDJ_DIAG ' not in line:continue
            try:
                row=json.loads(line.split('BITEDJ_DIAG ',1)[1]);unique[json.dumps(row,sort_keys=True)]=row
            except json.JSONDecodeError:pass
    telemetry=sorted(unique.values(),key=lambda row:row.get('wall_ms',0))
    name='BiteDJ_Pi4_diagnostics_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'.zip'
    if not BOOT.exists():raise OSError('Boot partition is not mounted')
    target=BOOT/name;temporary=target.with_suffix('.zip.part')
    compression=zipfile.ZIP_DEFLATED if zipfile.zlib is not None else zipfile.ZIP_STORED
    manifest={'format':'BiteDJ Pi4 diagnostics v0.3','started':started,'exported':stamp(),
              'retained_samples':len(samples),'sample_interval_seconds':1,'history_limit_seconds':HISTORY,
              'recorded_music_audio':False,'privacy_note':'Logs/config may include track paths and device identifiers.'}
    limitations=('This capture is evidence, not an automatic diagnosis.\n'
        'Analyze app telemetry only within the manifest started/exported time window.\n'
        'Audio processing usage 1.0 means the full buffer deadline.\n'
        'The buffer failure counter is throttled and does not count every lost buffer.\n'
        'The controller timer measures its thread, not the GUI event loop.\n'
        'One-second OS samples and periodic telemetry can miss short spikes.\n'
        'Renderer mappings alone do not prove hardware acceleration.\n')
    if not telemetry:limitations+='No in-app telemetry: select/apply the NV preset and repeat. OS data is usable.\n'
    with zipfile.ZipFile(temporary,'w',compression,compresslevel=1) as z:
        z.writestr('manifest.json',json.dumps(manifest,indent=2))
        z.writestr('system.json',json.dumps(snap,indent=2))
        z.writestr('samples.jsonl',''.join(json.dumps(r,separators=(',',':'))+'\n' for r in samples))
        z.writestr('markers.json',json.dumps(markers,indent=2))
        z.writestr('app-telemetry.jsonl',''.join(json.dumps(r)+'\n' for r in telemetry))
        z.writestr('read-me.txt',limitations)
        z.writestr('kernel-at-export.json',json.dumps(command(['dmesg']),indent=2))
        for name,blob in data.items():z.writestr('logs/'+name,blob)
    with temporary.open('rb') as f:os.fsync(f.fileno())
    temporary.replace(target)
    os.sync();(RAM/'last-export.txt').write_text(str(target)+'\n')
    return target


def announce(message):
    try:subprocess.Popen(['swaynag','-t','warning','-m',message],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    except OSError:pass


def recorder_pid():
    try:
        pid=int(PIDFILE.read_text());cmd=read('/proc/%d/cmdline'%pid,8192) or ''
        if 'diag.py' in cmd and 'record' in cmd:return pid
    except (OSError,ValueError):pass
    return None


def record(seconds=0):
    RAM.mkdir(parents=True,exist_ok=True);samples=deque(maxlen=HISTORY);marks=deque(maxlen=100)
    started=stamp();pending={k:False for k in ['mark','export','reset','stop']}
    for sig,key in [(signal.SIGUSR1,'mark'),(signal.SIGUSR2,'export'),(signal.SIGHUP,'reset'),(signal.SIGTERM,'stop')]:
        signal.signal(sig,lambda _s,_f,k=key:pending.__setitem__(k,stamp() if k=='mark' else True))
    PIDFILE.write_text(str(os.getpid()));begin=time.monotonic();next_trim=begin+30
    try:
        while not pending['stop']:
            if seconds and time.monotonic()-begin>=seconds:break
            if pending['reset']:samples.clear();marks.clear();started=stamp();pending['reset']=False
            if pending['mark']:marks.append(dict(pending['mark'],label='Observed skip or lag'));pending['mark']=False
            try:samples.append(sample())
            except Exception as e:print('Sample failed:',repr(e),flush=True)
            if time.monotonic()>=next_trim:
                next_trim=time.monotonic()+30
                for path in [RAM/'wm.log',RAM/'recorder.log']:
                    try:
                        if path.stat().st_size>2*LOG_LIMIT:
                            blob=tail(path)
                            with path.open('r+b') as f:f.write(blob);f.truncate()
                    except OSError:pass
            if pending['export']:
                pending['export']=False
                try:
                    destination=export(list(samples),list(marks),started)
                    announce('Saved '+destination.name+'. Shut down normally, then copy the report from the SD card BOOT partition.')
                except Exception as e:
                    print('Export failed:',repr(e),flush=True);announce('Diagnostic export failed. Check BOOT mount and free space.')
            time.sleep(1)
    finally:
        try:
            if int(PIDFILE.read_text())==os.getpid():PIDFILE.unlink(missing_ok=True)
        except (OSError,ValueError):pass


def boot_report():
    report={'format':'BiteDJ Pi4 boot v0.3','system':snapshot(),'startup_sample':sample(),
            'kernel':command(['dmesg']),'usb_tree':command(['lsusb','-t']),
            'irq_setup':read('/var/log/usb-irq-pin.log'),'rtirq':read('/var/log/rtirq.log')}
    if BOOT.exists():
        destination=BOOT/'BiteDJ_boot_report.txt';destination.write_text(json.dumps(report,indent=2)+'\n')
        with destination.open('rb') as f:os.fsync(f.fileno())


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['ensure','record','mark','export','reset','boot-report','export-now'])
    parser.add_argument('--seconds',type=float,default=0);args=parser.parse_args()
    RAM.mkdir(parents=True,exist_ok=True)
    if args.action=='boot-report':boot_report();return
    if args.action=='export-now':print(export([],[],stamp()));return
    if args.action=='record':record(args.seconds);return
    current=recorder_pid()
    if args.action=='ensure':
        if (BOOT/'bitedj-diag.disabled').exists():return
        if not current:
            with (RAM/'recorder.log').open('ab',buffering=0) as log:
                subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'record'],stdout=log,stderr=log,start_new_session=True)
        return
    if current:os.kill(current,{'mark':signal.SIGUSR1,'export':signal.SIGUSR2,'reset':signal.SIGHUP}[args.action])
    else:announce('Diagnostic recorder is not running. Remove bitedj-diag.disabled from BOOT and reboot.')


if __name__=='__main__':main()
