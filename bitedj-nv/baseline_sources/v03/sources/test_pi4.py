#!/usr/bin/env python3
"""Image mutation / diagnostic behavior checks, without a physical Pi."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from fat32 import Fat32

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('diag',HERE/'payload/usr/local/share/bitedj-diag/diag.py')
diag=importlib.util.module_from_spec(spec);spec.loader.exec_module(diag)


class DiagnosticChecks(unittest.TestCase):
    def test_proc_stat_name_with_parentheses(self):
        raw=Path('/proc/self/stat').read_text();original=diag.parse_stat(raw)
        changed=raw[:raw.find('(')]+'(Audio (worker) thread)'+raw[raw.rfind(')')+1:]
        parsed=diag.parse_stat(changed)
        self.assertEqual(parsed['name'],'Audio (worker) thread')
        for key in ['utime_ticks','stime_ticks','start_ticks','policy','rt_priority']:self.assertEqual(parsed[key],original[key])

    def test_marker_export_reset_signal_dispatch(self):
        old_pid,old_kill,old_argv,old_ram=diag.recorder_pid,diag.os.kill,sys.argv,diag.RAM
        calls=[]
        try:
            with tempfile.TemporaryDirectory() as directory:
                diag.recorder_pid=lambda:12345;diag.os.kill=lambda pid,sig:calls.append((pid,sig));diag.RAM=Path(directory)
                for action in ['mark','export','reset']:sys.argv=['diag.py',action];diag.main()
                self.assertEqual(calls,[(12345,signal.SIGUSR1),(12345,signal.SIGUSR2),(12345,signal.SIGHUP)])
        finally:diag.recorder_pid,diag.os.kill,sys.argv,diag.RAM=old_pid,old_kill,old_argv,old_ram

    def test_recorder_marker_and_report_export(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);ram=base/'ram';boot=base/'boot';ram.mkdir();boot.mkdir()
            row={'wall_ms':time.time()*1000,'usage':0.1,'usage_peak':0.6,'underflow_count':2}
            (ram/'wm.log').write_text('BITEDJ_DIAG '+json.dumps(row)+'\n')
            env=dict(os.environ,BITEDJ_DIAG_RAM=str(ram),BITEDJ_DIAG_BOOT=str(boot))
            with (base/'test.log').open('wb') as logfile:
                child=subprocess.Popen([sys.executable,str(HERE/'payload/usr/local/share/bitedj-diag/diag.py'),'record','--seconds','12'],
                    env=env,stdout=logfile,stderr=logfile)
                try:
                    until=time.monotonic()+4
                    while not (ram/'recorder.pid').exists() and time.monotonic()<until:time.sleep(0.05)
                    self.assertTrue((ram/'recorder.pid').exists())
                    # Host /proc uses a different PID namespace; Popen's child
                    # signals exercise the recorder, CLI dispatch is checked above.
                    child.send_signal(signal.SIGUSR1);child.send_signal(signal.SIGUSR2)
                    until=time.monotonic()+8;reports=[]
                    while time.monotonic()<until:
                        reports=list(boot.glob('*.zip'))
                        if reports and (ram/'last-export.txt').exists():break
                        time.sleep(0.1)
                    self.assertEqual(len(reports),1,(base/'test.log').read_text())
                    with zipfile.ZipFile(reports[0]) as z:
                        self.assertIsNone(z.testzip());manifest=json.loads(z.read('manifest.json'))
                        self.assertGreater(manifest['retained_samples'],0);self.assertFalse(manifest['recorded_music_audio'])
                        self.assertEqual(len(json.loads(z.read('markers.json'))),1)
                        self.assertIn('"underflow_count": 2',z.read('app-telemetry.jsonl').decode())
                        json.loads(z.read('system.json'))
                        for line in z.read('samples.jsonl').splitlines():self.assertIn('cpu_stat',json.loads(line))
                finally:
                    if child.poll() is None:child.send_signal(signal.SIGTERM)
                    child.wait(timeout=6)
            self.assertEqual(child.returncode,0);self.assertFalse((ram/'recorder.pid').exists())

    def test_boot_report_is_readable(self):
        old_boot=diag.BOOT
        try:
            with tempfile.TemporaryDirectory() as directory:
                diag.BOOT=Path(directory);diag.boot_report()
                report=json.loads((diag.BOOT/'BiteDJ_boot_report.txt').read_text())
                self.assertIn('system',report);self.assertIn('pci',report['system']);self.assertIn('kernel',report)
        finally:diag.BOOT=old_boot


class FatMutationChecks(unittest.TestCase):
    def test_replacements_resize_preserve_all_other_boot_files(self):
        fat=Fat32(HERE/'base/boot.img')
        baseline={e['name']:fat.chain(e['cluster'])[:e['size']] for e in fat.entries() if not e['directory']}
        fat.replace('config.txt',b'# test\n'+b'x'*2400)
        fat.replace('cmdline.txt',b'video=HDMI-A-1:1280x720@60D\n')
        stats=fat.validate();self.assertEqual(stats['crosslinks'],0)
        for e in fat.entries():
            if e['directory'] or e['name'].casefold() in ['config.txt','cmdline.txt']:continue
            self.assertEqual(fat.chain(e['cluster'])[:e['size']],baseline[e['name']],e['name'])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'boot.img';fat.save(path);reread=Fat32(path)
            self.assertEqual(reread.validate(),stats)
            e=next(e for e in reread.entries() if e['name'].casefold()=='config.txt')
            self.assertEqual(reread.chain(e['cluster'])[:e['size']],b'# test\n'+b'x'*2400)


if __name__=='__main__':unittest.main(verbosity=2)
