#!/usr/bin/env python3
"""Migrate the preserved HDMI v0.2 image to a Pi 4 SD test image."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import lzma
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
import zstandard
from fat32 import Fat32

HERE=Path(__file__).resolve().parent
DOCS=HERE if (HERE/'README.txt').exists() else HERE.parent
CONFIG='''# BiteDJ Pi 4 4GB HDMI/NV test v0.3
# Connect the monitor to HDMI0 (micro-HDMI beside the USB-C power socket).
arm_64bit=1
kernel=kernel8.img
initramfs initramfs.img followkernel
enable_uart=0
disable_overscan=1
disable_fw_kms_setup=1
gpu_mem=64
camera_auto_detect=0
display_auto_detect=0
dtparam=audio=on
dtoverlay=vc4-kms-v3d,cma-256
# Radios remain offline in this preserved appliance image.
dtoverlay=disable-wifi
dtoverlay=disable-bt
# No overclock, GPIO LEDs/buttons, battery HAT, or DSI panel profile.
'''
CMDLINE=('isolcpus=2,3 nohz_full=3 rcu_nocbs=2,3 irqaffinity=0,1 kthread_cpus=0-1 skew_tick=1 '
         'usbcore.autosuspend=-1 sysrq_always_enabled console=tty0 quiet loglevel=3 '
         'vt.global_cursor_default=0 root=/dev/mmcblk0p2 datafs_wait=100 '
         'video=HDMI-A-1:1280x720@60D\n')
BOOT_MOUNT='''# Pi 4 test profile: expose BOOT for diagnostic capture and recovery.
mkdir -p /newroot/boot/firmware
BOOTFS="${DATAFS%p2}p1"
if [ -b "/newroot$BOOTFS" ]; then
    mount -t vfat -o rw,noatime,umask=0077 "/newroot$BOOTFS" /newroot/boot/firmware || \\
        echo "BiteDJ: diagnostic BOOT mount failed" >&2
fi

'''


def run(args,**kwargs):
    result=subprocess.run([str(x) for x in args],capture_output=True,text=True,**kwargs)
    if result.returncode:raise RuntimeError(str(args)+'\n'+result.stdout+result.stderr)
    return result


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while b:=f.read(4*1024*1024):h.update(b)
    return h.hexdigest()


def replace_once(text,old,new):
    if text.count(old)!=1:raise ValueError('Unexpected image insertion point: '+old[:100])
    return text.replace(old,new,1)


def cpio_tools(base):
    spec=importlib.util.spec_from_file_location('base_builder',base/'package/build_hdmi_image.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def root_read(root,path,destination):
    destination=Path(destination);destination.unlink(missing_ok=True)
    run(['debugfs','-R','dump '+path+' '+str(destination),root])
    if not destination.exists():raise ValueError('Missing root file '+path)
    return destination.read_bytes()


def make_payload(base,output):
    source=base/'package/modified-files/root';payload=output/'payload'
    shutil.copytree(HERE/'payload',payload,dirs_exist_ok=True)
    def save(name,text):
        p=payload/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    start=(source/'usr/bin/start-mixxx').read_text()
    start=replace_once(start,'--log-level warning','--log-level info')
    start=replace_once(start,'    export QT_QPA_PLATFORM=wayland\n    exec $MIXXX_BIN $MIXXX_ARGS',
        '    export QT_QPA_PLATFORM=wayland\n'
        '    /usr/bin/python3 /usr/local/share/bitedj-diag/diag.py ensure || true\n'
        '    exec $MIXXX_BIN $MIXXX_ARGS')
    start=replace_once(start,'# Core 2 belongs to USB (the peripheral IRQ cascade is routed there and the\n'
        '# dwc_otg IRQ threads are pinned there) and core 3 to the audio engine, which\n',
        '# Core 2 handles the Pi 4 xHCI interrupt and its IRQ threads.\n'
        '# Core 3 belongs to the audio engine, which\n')
    save('usr/bin/start-mixxx',start)
    init=(source/'usr/sbin/init').read_text()
    init=replace_once(init,'/usr/local/sbin/usb-watchdog &',
        ': # Pi 4: the Pi 3 dwc_otg power-cycling watchdog is disabled.\n'
        'echo "Pi 4 xHCI profile; dwc_otg watchdog disabled" > /var/log/usb-watchdog.log')
    init=replace_once(init,'    /bin/start-mixxx 2>&1 | tee /var/log/wm.log',
        '    mkdir -p /tmp/bitedj-diag\n'
        '    /usr/bin/python3 /usr/local/share/bitedj-diag/diag.py boot-report || true\n'
        '    : > /tmp/bitedj-diag/wm.log\n'
        '    /bin/start-mixxx 2>&1 | tee -a /tmp/bitedj-diag/wm.log')
    init=replace_once(init,'    echo "session: start-mixxx exited with $rc"',
        '    echo "session: start-mixxx exited with $rc"\n'
        '    /usr/bin/python3 /usr/local/share/bitedj-diag/diag.py export-now || true')
    save('usr/sbin/init',init)
    sway=(source/'etc/deckshark/sway-kiosk.conf').read_text()
    sway+='\n# Pi 4: fixed HDMI0 mode and diagnostic keyboard shortcuts.\n'
    sway+='output HDMI-A-1 mode 1280x720@60Hz\noutput HDMI-A-1 scale 1\n'
    for key,action in [('F9','reset'),('F10','mark'),('F12','export')]:
        sway+='bindsym '+key+' exec /usr/bin/python3 /usr/local/share/bitedj-diag/diag.py '+action+'\n'
    save('etc/deckshark/sway-kiosk.conf',sway)
    save('etc/default/rtirq','RTIRQ_NAME_LIST="xhci v3d vc4"\nRTIRQ_PRIO_HIGH=85\nRTIRQ_PRIO_DECR=5\n')
    save('etc/deckshark-release','BiteDJ Pi4 4GB HDMI NV Test v0.3\nBase firmware 20260926.1; unchanged Mixxx/BiteDJ 2.5.6 ARM64 binary\n')
    cfg=(source/'root/.mixxx/mixxx.cfg').read_text()
    cfg=replace_once(cfg,'FrameRate 52','FrameRate 30')
    cfg=cfg.replace('# 800x480','# Pi 4 HDMI 1280x720')
    preset='/usr/share/mixxx/controllers/Numark-NV-BiteDJ-Test.midi.xml'
    cfg=replace_once(cfg,'[ControllerPreset]\n','[ControllerPreset]\nNV_MIDI_1 '+preset+'\nNumark_NV_MIDI_1 '+preset+'\n')
    cfg=replace_once(cfg,'[Controller]\n','[Controller]\nNV_MIDI_1 1\nNumark_NV_MIDI_1 1\n')
    save('root/.mixxx/mixxx.cfg',cfg)
    xml=(base/'package/repair-payload/controllers/Numark-NV-BiteDJ-Test.midi.xml').read_text()
    xml=replace_once(xml,'Numark NV (BiteDJ Test v0.2)','Numark NV (BiteDJ Pi4 Test v0.3)')
    xml=replace_once(xml,'        </scriptfiles>',
        '            <file filename="BiteDJ-Diagnostics.js" functionprefix="BiteDJDiag" />\n        </scriptfiles>')
    ET.fromstring(xml);save('usr/share/mixxx/controllers/Numark-NV-BiteDJ-Test.midi.xml',xml)
    diagjs=payload/'usr/local/share/bitedj-diag/BiteDJ-Diagnostics.js'
    save('usr/share/mixxx/controllers/BiteDJ-Diagnostics.js',diagjs.read_text())
    return payload


def mutate_root(base,output,payload):
    root=output/'root.img';shutil.copyfile(base/'root.img',root)
    original_app=output/'original-app.bin';root_read(base/'root.img','/usr/share/mixxx/mixxx',original_app)
    files=sorted(p for p in payload.rglob('*') if p.is_file())
    parents=sorted({str(parent.relative_to(payload)) for p in files for parent in p.parents
                    if parent!=payload and payload in parent.parents},key=lambda x:(x.count('/'),x))
    commands=[]
    for parent in parents:commands.append('mkdir /'+parent)
    for file in files:
        relative='/'+str(file.relative_to(payload));commands.append('rm '+relative)
        commands.append('write '+str(file)+' '+relative)
        mode=0o100755 if relative in ['/usr/bin/start-mixxx','/usr/sbin/init','/usr/local/sbin/usb-irq-pin'] else 0o100644
        commands.append('set_inode_field '+relative+' mode 0'+format(mode,'o'))
    commandfile=output/'debugfs-write.txt';commandfile.write_text('\n'.join(commands)+'\n')
    result=run(['debugfs','-w','-f',commandfile,root]);(output/'debugfs-write.log').write_text(result.stdout+result.stderr)
    readback=output/'readback';readback.mkdir(exist_ok=True)
    for file in files:
        relative='/'+str(file.relative_to(payload));destination=readback/file.relative_to(payload)
        destination.parent.mkdir(parents=True,exist_ok=True)
        assert root_read(root,relative,destination)==file.read_bytes(),relative
        stat=run(['debugfs','-R','stat '+relative,root])
        expected='0755' if relative in ['/usr/bin/start-mixxx','/usr/sbin/init','/usr/local/sbin/usb-irq-pin'] else '0644'
        assert 'Mode:  '+expected in stat.stdout,(relative,stat.stdout)
    after_app=output/'after-app.bin';root_read(root,'/usr/share/mixxx/mixxx',after_app)
    assert sha(original_app)==sha(after_app),'Application binary changed'
    original_app.unlink();after_app.unlink()
    result=subprocess.run(['e2fsck','-fn',str(root)],capture_output=True,text=True)
    (output/'ext4-check.txt').write_text(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError('ext4 validation failed:\n'+result.stdout+result.stderr)
    return root,{'changed_files_verified':len(files),'file_modes':'passed','application_binary_unchanged':True,'ext4_check':'passed'}


def build(base,output):
    base=Path(base).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    payload=make_payload(base,output)
    for relative in ['usr/bin/start-mixxx','usr/sbin/init','usr/local/sbin/usb-irq-pin']:
        run(['sh','-n',payload/relative])
    for file in payload.rglob('*.py'):
        compile(file.read_bytes(),str(file),'exec')
    tools=cpio_tools(base);fat=Fat32(base/'boot.img')
    boot_entries={x['name'].casefold():x for x in fat.entries()}
    required=['start4.elf','fixup4.dat','bcm2711-rpi-4-b.dtb','kernel8.img','initramfs.img']
    for name in required:assert name in boot_entries,name
    kernel=fat.chain(boot_entries['kernel8.img']['cluster'])[:boot_entries['kernel8.img']['size']]
    raw=gzip.decompress(kernel) if kernel[:2]==b'\x1f\x8b' else kernel
    evidence=[b'brcm,bcm2711-pcie',b'xhci_pci_common_probe',b'brcm,bcm2711-hdmi0',b'brcm,bcm2711-vc5',b'PREEMPT_RT']
    for key in evidence:assert key in raw,key
    packed=fat.chain(boot_entries['initramfs.img']['cluster'])[:boot_entries['initramfs.img']['size']]
    records=tools.parse_cpio(zstandard.ZstdDecompressor().decompress(packed))
    original={r[3]:(r[1].copy(),r[4]) for r in records}
    init=next(r for r in records if r[3]=='init')
    init[4]=replace_once(init[4].decode(),'exec /bin/busybox switch_root /newroot /sbin/init',
        BOOT_MOUNT+'exec /bin/busybox switch_root /newroot /sbin/init').encode()
    initpath=output/'initramfs-init.sh';initpath.write_bytes(init[4]);run(['sh','-n',initpath])
    newinit=zstandard.ZstdCompressor(level=10).compress(tools.encode_cpio(records))
    restored={r[3]:r for r in tools.parse_cpio(zstandard.ZstdDecompressor().decompress(newinit))}
    for name,(fields,data) in original.items():
        if name!='init':assert restored[name][1]==fields and restored[name][4]==data,name
        else:assert restored[name][4]==init[4]
    originals={x['name']:fat.chain(x['cluster'])[:x['size']] for x in fat.entries() if not x['directory']}
    fat.replace('config.txt',CONFIG.encode());fat.replace('cmdline.txt',CMDLINE.encode());fat.replace('initramfs.img',newinit)
    boot=output/'boot.img';fat_checks=fat.save(boot)
    checked=Fat32(boot)
    for entry in checked.entries():
        if entry['directory']:continue
        content=checked.chain(entry['cluster'])[:entry['size']]
        if entry['name'].casefold() not in ['config.txt','cmdline.txt','initramfs.img']:
            assert content==originals[entry['name']],entry['name']
    checked.extract(output/'boot-files')
    root,root_checks=mutate_root(base,output,payload)
    image=output/'BiteDJ_Pi4_4GB_HDMI_NV_Test_v0_3.img'
    header=(base/'mbr.bin').read_bytes()
    import struct
    with image.open('wb') as target:
        target.write(header)
        for number,part in enumerate([boot,root]):
            start,count=struct.unpack_from('<II',header,446+number*16+8)
            assert part.stat().st_size==count*512
            target.seek(start*512)
            with part.open('rb') as source:shutil.copyfileobj(source,target,4*1024*1024)
    validation={'target':'Raspberry Pi 4 Model B, 4GB','version':'0.3','boot_assets':required,
        'kernel_driver_evidence':[key.decode() for key in evidence],
        'kernel_driver_evidence_limit':'Embedded driver/device strings; not a physical hardware probe.',
        'kernel_unchanged':True,'fat':fat_checks,'initramfs_members_preserved':len(original)-1,
        'initramfs_roundtrip':'passed','startup_shell_syntax':'passed',**root_checks,
        'physical_pi4_boot_test':'not performed','physical_nv_audio_test':'not performed',
        'nv_lcd_support':False,'wifi_ssh':'not added; original offline radio profile retained'}
    # Verify the assembled disk contains exactly the validated partition bytes.
    with image.open('rb') as f:
        for number,part in enumerate([boot,root]):
            start,count=struct.unpack_from('<II',header,446+number*16+8);f.seek(start*512)
            h=hashlib.sha256();left=count*512
            while left:
                b=f.read(min(left,4*1024*1024));assert b;h.update(b);left-=len(b)
            assert h.hexdigest()==sha(part)
    validation['assembled_partition_hashes']='passed';validation['disk_sha256']=sha(image)
    (output/'validation.json').write_text(json.dumps(validation,indent=2)+'\n')
    print('Image assembled and partitions verified: '+str(image),flush=True)
    run(['xz','-T2','-6','--memlimit-compress=512MiB','--keep','--force',image])
    compressed=image.with_suffix('.img.xz')
    h=hashlib.sha256()
    with lzma.open(compressed,'rb') as f:
        while b:=f.read(4*1024*1024):h.update(b)
    assert h.hexdigest()==validation['disk_sha256']
    validation['full_xz_decompression']='passed'
    validation['compressed_sha256']=sha(compressed)
    (output/'validation.json').write_text(json.dumps(validation,indent=2)+'\n')
    (output/'SHA256SUMS.txt').write_text(validation['compressed_sha256']+'  '+compressed.name+'\n')
    package=output/'BiteDJ_Pi4_4GB_HDMI_NV_Test_v0_3.zip'
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        z.write(compressed,compressed.name,compress_type=zipfile.ZIP_STORED)
        for name in ['README.txt','LICENSE.txt']:z.write(DOCS/name,name)
        for name in ['validation.json','SHA256SUMS.txt','offline-tests.json']:
            if (output/name).exists():z.write(output/name,name)
        for p in payload.rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:z.write(p,'modified-root/'+str(p.relative_to(payload)))
        for name in ['config.txt','cmdline.txt']:z.write(output/'boot-files'/name,'boot-settings/'+name)
        z.write(initpath,'boot-settings/initramfs-init.sh')
        for name in ['build_pi4.py','extract_base.py','fat32.py','test_pi4.py','test_telemetry.js']:
            if (HERE/name).exists():z.write(HERE/name,'sources/'+name)
        for p in (HERE/'payload').rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:z.write(p,'sources/payload/'+str(p.relative_to(HERE/'payload')))
        for p in (base/'package/repair-payload/controllers').glob('*'):
            if p.is_file():z.write(p,'nv-mapping/'+p.name)
        for p in (base/'package/repair-payload/docs').glob('*'):
            if p.is_file():z.write(p,'nv-mapping/docs/'+p.name)
        z.write(base/'package/build_hdmi_image.py','sources/base_cpio_tools.py')
    with zipfile.ZipFile(package) as z:assert z.testzip() is None
    print(json.dumps({'file':str(package),'bytes':package.stat().st_size,'validation':validation},indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--base',default=str(HERE/'base'))
    parser.add_argument('--output',default=str(HERE/'build'));args=parser.parse_args();build(args.base,args.output)
