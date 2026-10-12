import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1]/'runtime/update_installer.py'


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        spec = importlib.util.spec_from_file_location('nv_update_v056', SOURCE)
        self.u = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.u)
        self.u.COMPATIBILITY = {}
        (self.root/'etc').mkdir()
        (self.root/'etc/deckshark-release').write_text(self.u.RELEASE+'\n')
        self.boot = self.root/'boot/firmware'
        self.boot.mkdir(parents=True)
        self.original = {'usr/bin/start-mixxx': b'old launcher',
                         'usr/share/mixxx/controllers/NV.js': b'v04 mapping'}
        for name, data in self.original.items():
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(0o755 if name.endswith('start-mixxx') else 0o644)
        self.settings = self.root/'root/.mixxx/mixxx.cfg'
        self.settings.parent.mkdir(parents=True)
        self.settings.write_bytes(b'User audio routing and waveform settings\n')
        new = {**{name: b'new '+data for name, data in self.original.items()},
               'usr/local/lib/bitedj-nv-v05/bitedj': b'new application'}
        self.u.PAYLOAD = [{'path': name, 'new_sha256': self.u.digest(data),
                           'old_sha256': [self.u.digest(self.original[name])] if name in self.original else [None],
                           'mode': 0o755, 'base64': base64.b64encode(data).decode()}
                          for name, data in new.items()]

    def check_originals(self):
        for name, data in self.original.items():
            self.assertEqual((self.root/name).read_bytes(), data)
        self.assertFalse((self.root/'usr/local/lib/bitedj-nv-v05/bitedj').exists())
        self.assertEqual(self.settings.read_bytes(), b'User audio routing and waveform settings\n')

    def test_install_idempotent_and_rollback_keeps_settings(self):
        self.assertEqual(self.u.update(self.root), 'installed')
        mtimes = [(self.root/x['path']).stat().st_mtime_ns for x in self.u.PAYLOAD]
        self.assertEqual(self.u.update(self.root), 'already_installed')
        self.assertEqual(mtimes, [(self.root/x['path']).stat().st_mtime_ns for x in self.u.PAYLOAD])
        (self.boot/self.u.ROLLBACK).touch()
        self.assertEqual(self.u.update(self.root), 'rolled_back')
        self.check_originals()
        self.assertEqual((self.root/'usr/bin/start-mixxx').stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.root/'usr/share/mixxx/controllers/NV.js').stat().st_mode & 0o777, 0o644)

    def test_unknown_mapping_rejected_before_launcher_change(self):
        path = self.root/'usr/share/mixxx/controllers/NV.js'
        path.write_bytes(b'user customized mapping')
        self.assertEqual(self.u.update(self.root), 'error')
        self.assertEqual(path.read_bytes(), b'user customized mapping')
        self.assertEqual((self.root/'usr/bin/start-mixxx').read_bytes(), b'old launcher')

    def test_write_failure_restores_original_files(self):
        original_write = self.u.atomic_write
        failed = False
        def fail_once(path, data, mode=0o644):
            nonlocal failed
            if path == self.root/'usr/share/mixxx/controllers/NV.js' and not failed:
                failed = True
                raise OSError('simulated media write error')
            return original_write(path, data, mode)
        with mock.patch.object(self.u, 'atomic_write', fail_once):
            self.assertEqual(self.u.update(self.root), 'error')
        self.check_originals()

    def test_next_boot_recovers_interrupted_install(self):
        original_write = self.u.atomic_write
        def power_loss(path, data, mode=0o644):
            if path == self.root/'usr/share/mixxx/controllers/NV.js':
                raise KeyboardInterrupt('simulated abrupt termination')
            return original_write(path, data, mode)
        with mock.patch.object(self.u, 'atomic_write', power_loss):
            with self.assertRaises(KeyboardInterrupt):
                self.u.update(self.root)
        self.assertEqual(self.u.update(self.root), 'installed')
        (self.boot/self.u.ROLLBACK).touch()
        self.assertEqual(self.u.update(self.root), 'rolled_back')
        self.check_originals()

    def test_rollback_refuses_edited_target_and_corrupt_backup(self):
        self.u.update(self.root)
        path = self.root/'usr/bin/start-mixxx'
        path.write_bytes(b'user edited launcher')
        (self.boot/self.u.ROLLBACK).touch()
        self.assertEqual(self.u.update(self.root), 'error')
        self.assertEqual(path.read_bytes(), b'user edited launcher')

    def test_payload_hash_and_backup_paths_are_validated(self):
        self.u.PAYLOAD[0]['base64'] = base64.b64encode(b'tampered').decode()
        self.assertEqual(self.u.update(self.root), 'error')
        self.check_originals()

    def test_preexisting_unjournaled_bad_backup_is_rejected(self):
        path = self.root/self.u.BACKUP/'files/usr/bin/start-mixxx'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'corrupt backup')
        self.assertEqual(self.u.update(self.root), 'error')
        self.check_originals()

    def test_all_older_interrupted_updates_must_recover_before_upgrade(self):
        for backup in self.u.LEGACY_BACKUPS:
            path = self.root/backup/'state.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'installing': True}))
            self.assertEqual(self.u.update(self.root), 'error')
            self.check_originals()
            self.assertEqual(json.loads(path.read_text()), {'installing': True})
            path.unlink()

    def test_payload_rollback_restores_preferences_without_clobbering_audio_changes(self):
        from runtime import nv_settings as settings
        self.settings.write_text('[ControllerPreset]\nNV_Audio_MIDI_1 ' + settings.NV_MAPPING +
                                 '\n[Controller]\nNV_Audio_MIDI_1 1\n[Soundcard]\nlatency 128\n')
        self.assertEqual(self.u.update(self.root), 'installed')
        settings.nv_apply_settings(self.root)
        self.settings.write_text(self.settings.read_text().replace('latency 128', 'latency 256'))
        (self.boot/self.u.ROLLBACK).touch()
        self.assertEqual(self.u.update(self.root), 'rolled_back')
        self.assertIn('NV_Audio_MIDI_1 1', self.settings.read_text())
        self.assertIn('latency 256', self.settings.read_text())


if __name__ == '__main__':
    unittest.main()
