import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from runtime import sd_music as sd


ROOT = dict(device_id='179:2', target='/', root='/', options=['rw'], fstype='ext4', source='/dev/root')
MEDIA = dict(device_id='0:23', target='/media', root='/', options=['rw'], fstype='tmpfs', source='tmpfs')
PART = dict(name='mmcblk0p3', device_id='179:3', label='MUSIC', fstype='exfat', uuid='1234-ABCD')


class FakeSystem(sd.System):
    def __init__(self, root):
        super().__init__(root)
        self.table = [copy.deepcopy(ROOT), copy.deepcopy(MEDIA)]
        self.parts = [dict(PART)]
        self.commands = []
        self.failure = None
        self.identity_ok = True

    def mounts(self):
        return copy.deepcopy(self.table)

    def partitions(self, card):
        self.requested_card = card
        return copy.deepcopy(self.parts)

    def block_matches(self, candidate):
        return self.identity_ok

    def run(self, command, timeout=2):
        self.commands.append(command)
        if isinstance(self.failure, Exception):
            raise self.failure
        if self.failure == 'error':
            return subprocess.CompletedProcess(command, 1, '', 'wrong fs type')
        if self.failure != 'false_success':
            self.table.append(dict(ROOT, device_id=PART['device_id'], target=sd.TARGET, fstype='exfat'))
        return subprocess.CompletedProcess(command, 0, '', '')


class SdMusicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.s = FakeSystem(self.root)
        (self.root/'media').mkdir()
        block = self.root/'sys/devices/card/mmcblk0p2'
        block.mkdir(parents=True)
        dev = self.root/'sys/dev/block'
        dev.mkdir(parents=True)
        (dev/'179:2').symlink_to(block)

    def option(self, value):
        path = self.root/sd.OPTION
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def test_mount_after_media_setup_and_repeat_preserves_mount(self):
        result = sd.mount_music(self.s)
        self.assertEqual(result['status'], 'mounted')
        self.assertEqual(self.s.requested_card, 'mmcblk0')
        self.assertEqual(self.s.commands, [['/usr/bin/mount', '-t', 'exfat', '-o',
            'rw,nosuid,nodev,noexec,noatime', '/dev/mmcblk0p3', '/media/MUSIC']])
        self.assertEqual(sd.mount_music(self.s)['status'], 'already_mounted')
        self.assertEqual(len(self.s.commands), 1)

    def test_existing_custom_path_and_readonly_state_are_preserved(self):
        self.s.table.append(dict(ROOT, device_id='179:3', target='/music', options=['ro']))
        result = sd.mount_music(self.s)
        self.assertEqual((result['status'], result['target'], result['mount_options']),
                         ('already_mounted', '/music', ['ro']))
        self.assertFalse(self.s.commands)
        self.assertFalse((self.root/'media/MUSIC').exists())

    def test_no_early_mount_before_media_tmpfs(self):
        self.s.table.pop()
        self.assertIn('tmpfs is not ready', sd.mount_music(self.s)['reason'])
        self.assertFalse(self.s.commands)

    def test_missing_and_ambiguous_labels(self):
        self.s.parts[0]['label'] = 'BOOT'
        self.assertEqual(sd.mount_music(self.s)['status'], 'skipped')
        self.s.parts = [dict(PART), dict(PART, name='mmcblk0p4', device_id='179:4', label='music')]
        self.assertIn('Multiple MUSIC', sd.mount_music(self.s)['reason'])
        self.assertFalse(self.s.commands)

    def test_unsupported_filesystem(self):
        self.s.parts[0]['fstype'] = 'crypto_LUKS'
        self.assertIn('Unsupported MUSIC', sd.mount_music(self.s)['reason'])
        self.assertFalse(self.s.commands)

    def test_target_mount_collision(self):
        self.s.table.append(dict(ROOT, device_id='8:1', target=sd.TARGET))
        self.assertIn('occupied', sd.mount_music(self.s)['reason'])
        self.assertFalse(self.s.commands)

    def test_never_hides_files_or_follows_mount_path_symlink(self):
        target = self.root/'media/MUSIC'
        target.mkdir(); (target/'keep.mp3').write_bytes(b'user audio')
        self.assertIn('not an empty directory', sd.mount_music(self.s)['reason'])
        self.assertEqual((target/'keep.mp3').read_bytes(), b'user audio')
        (target/'keep.mp3').unlink(); target.rmdir(); target.symlink_to(self.root/'elsewhere')
        self.assertIn('symlink', sd.mount_music(self.s)['reason'])
        self.assertFalse(self.s.commands)

    def test_disabled_invalid_and_symlink_option_do_not_mount(self):
        for value,status in [('off\n','disabled'),('rm -rf /','error'),('auto\n'*20,'error')]:
            self.option(value)
            self.assertEqual(sd.mount_music(self.s)['status'], status)
        p=self.root/sd.OPTION; p.unlink(); p.symlink_to('/missing')
        self.assertIn('regular file', sd.mount_music(self.s)['reason'])
        self.assertFalse(self.s.commands)

    def test_launch_runs_mount_before_app_including_off_and_survives_failure(self):
        # Exercise the launcher with fixture paths; never call the real helper,
        # mount, native application or LCD service on the test machine.
        project = Path(__file__).resolve().parents[1]
        slot = self.root/'slot'; slot.mkdir()
        log = self.root/'events'
        python = self.root/'python'
        python.write_text('#!/bin/sh\nprintf "%s\\n" "$1" >> "'+str(log)+'"\nexit 1\n')
        python.chmod(0o755)
        app = '#!/bin/sh\nprintf "app:%s:%s\\n" "$0" "$1" >> "'+str(log)+'"\n'
        original = self.root/'original'; original.write_text(app); original.chmod(0o755)
        # The real app stays alive while the renderer starts asynchronously.
        # Wait for that fixture's event; an instant-exit fake app races the child.
        native = slot/'bitedj'
        native.write_text('#!/usr/bin/python3\nimport pathlib, sys, time\n'
                          + 'log = pathlib.Path(' + repr(str(log)) + ')\n'
                          + 'for attempt in range(100):\n'
                          + '    if "-m" in log.read_text().splitlines(): break\n'
                          + '    time.sleep(0.01)\n'
                          + 'with log.open("a") as f: f.write("app:" + sys.argv[0] + ":" + sys.argv[1] + "\\n")\n')
        native.chmod(0o755)
        launch = self.root/'launch.sh'
        source = (project/'runtime/launch.sh').read_text()
        source = source.replace('/usr/local/lib/bitedj-nv-v057', str(slot))
        source = source.replace('/usr/bin/python3', str(python))
        source = source.replace('/boot/firmware', str(self.root/'boot/firmware'))
        source = source.replace('/tmp/bitedj-nv', str(self.root/'logs'))
        launch.write_text(source)
        for mode in ('off', 'info', 'overview', 'full'):
            mode_file = self.root/'boot/firmware/BiteDJ_NV_display_mode.txt'
            mode_file.parent.mkdir(parents=True, exist_ok=True)
            mode_file.write_text(mode)
            log.write_text('')
            run = subprocess.run(['sh', str(launch), str(original), 'argument with spaces'],
                                 capture_output=True, text=True, timeout=5)
            self.assertEqual(run.returncode, 0, run.stderr)
            events = log.read_text().splitlines()
            self.assertEqual(events[:2], [str(slot/'sd_music.py'), str(slot/'nv_settings.py')])
            self.assertIn('app:'+str(original if mode == 'off' else native)+':argument with spaces', events)
            self.assertEqual('-m' in events, mode != 'off')

    def test_mount_failure_timeout_and_false_success_are_reported(self):
        for failure in ('error','false_success',subprocess.TimeoutExpired('mount',8)):
            self.s.failure = failure
            self.assertEqual(sd.mount_music(self.s)['status'], 'error')
            self.assertFalse((self.root/'media/MUSIC').exists())
        (self.root/'media/MUSIC').mkdir()
        sd.mount_music(self.s)
        self.assertTrue((self.root/'media/MUSIC').is_dir())

    def test_device_or_mount_change_before_mount_is_rejected(self):
        self.s.identity_ok = False
        self.assertIn('state changed', sd.mount_music(self.s)['reason'])
        self.s.identity_ok = True
        before=self.s.mounts()
        with mock.patch.object(self.s, 'mounts', side_effect=[before,before+[dict(ROOT,target='/other')]]):
            self.assertIn('state changed', sd.mount_music(self.s)['reason'])
        self.assertFalse(self.s.commands)

    def test_root_identity_requires_actual_mmc_p2_not_usb_or_bind(self):
        self.s.table[0]['root'] = '/subdir'
        self.assertEqual(sd.mount_music(self.s)['status'], 'error')
        self.s.table[0] = dict(ROOT)
        link=self.root/'sys/dev/block/179:2'; link.unlink()
        other=self.root/'sys/devices/sda2'; other.mkdir(); link.symlink_to(other)
        self.assertIn('MMC p2', sd.mount_music(self.s)['reason'])
        self.assertFalse(self.s.commands)

    def test_discovery_excludes_boot_root_and_other_cards(self):
        for name,num in [('mmcblk0p1',1),('mmcblk0p2',2),('mmcblk0p3',3),('mmcblk1p3',3),('sda1',1)]:
            p=self.root/'sys/class/block'/name; p.mkdir(parents=True)
            (p/'partition').write_text(str(num)); (p/'dev').write_text('179:'+str(num))
        system=sd.System(self.root)
        response=subprocess.CompletedProcess([],0,'LABEL=MUSIC\nTYPE=exfat\nUUID=1234\n','')
        with mock.patch.object(system,'block_matches',return_value=True), mock.patch.object(system,'run',return_value=response) as run:
            parts=system.partitions('mmcblk0')
            self.assertEqual([p['name'] for p in parts],['mmcblk0p3'])
            self.assertEqual(run.call_args.args[0][-1], '/dev/mmcblk0p3')

    def test_deadline_prevents_command_and_mountinfo_decodes_spaces(self):
        system=sd.System(self.root); system.deadline=0
        with self.assertRaises(TimeoutError): system.run(['must-not-execute'])
        rows=sd.mount_table('19 1 179:3 / /media/My\\040Music rw - exfat /dev/mmcblk0p3 rw\n')
        self.assertEqual(rows[0]['target'],'/media/My Music')
        with self.assertRaises(ValueError): sd.mount_table('malformed')


if __name__ == '__main__':
    unittest.main()
