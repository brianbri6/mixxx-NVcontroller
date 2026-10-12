#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        spec = importlib.util.spec_from_file_location('nv_update', HERE.parent / 'build/nv_update_generated.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.boot = self.root / 'boot/firmware'
        self.boot.mkdir(parents=True)
        release = self.root / 'etc/deckshark-release'
        release.parent.mkdir(parents=True)
        release.write_text('BiteDJ Pi4 4GB HDMI NV Test v0.3\n')
        for item in self.module.PAYLOAD:
            p = self.root / item['path']
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes((HERE.parent / 'image' / p.name).read_bytes())
        self.settings = self.root / 'root/.mixxx/mixxx.cfg'
        self.settings.parent.mkdir(parents=True)
        self.settings.write_bytes(b'[Waveform]\nframe_rate 0\n[Soundcard]\nlatency 21\ncustom-routing-kept\n')
        self.original_settings = self.settings.read_bytes()

    def tearDown(self):
        self.temporary.cleanup()

    def test_install_preserves_settings_and_is_idempotent(self):
        self.assertEqual(self.module.update(self.root), 'installed')
        times = []
        for item in self.module.PAYLOAD:
            path = self.root / item['path']
            self.assertEqual(self.module.digest(path.read_bytes()), item['new_sha256'])
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            times.append(path.stat().st_mtime_ns)
        self.assertEqual(self.module.update(self.root), 'already_installed')
        self.assertEqual(times, [(self.root / p['path']).stat().st_mtime_ns for p in self.module.PAYLOAD])
        self.assertEqual(self.settings.read_bytes(), self.original_settings)

    def test_rollback_restores_both_files_and_keeps_settings(self):
        self.module.update(self.root)
        (self.boot / self.module.ROLLBACK).touch()
        self.assertEqual(self.module.update(self.root), 'rolled_back')
        for item in self.module.PAYLOAD:
            self.assertEqual(self.module.digest((self.root / item['path']).read_bytes()), item['old_sha256'])
        self.assertEqual(self.settings.read_bytes(), self.original_settings)

    def test_edited_mapping_is_rejected_before_changes(self):
        target = self.root / self.module.PAYLOAD[1]['path']
        target.write_bytes(b'custom user mapping')
        self.assertEqual(self.module.update(self.root), 'error')
        self.assertEqual(target.read_bytes(), b'custom user mapping')
        self.assertFalse((self.root / self.module.BACKUP).exists())
        first = self.module.PAYLOAD[0]
        self.assertEqual(self.module.digest((self.root / first['path']).read_bytes()), first['old_sha256'])

    def test_interrupted_install_can_finish_from_verified_backups(self):
        self.module.update(self.root)
        item = self.module.PAYLOAD[1]
        (self.root / item['path']).write_bytes((HERE.parent / 'image' / Path(item['path']).name).read_bytes())
        state = self.root / self.module.BACKUP / 'state.json'
        state.write_text(json.dumps({'installed': False, 'installing': True}))
        self.assertEqual(self.module.update(self.root), 'installed')
        for item in self.module.PAYLOAD:
            self.assertEqual(self.module.digest((self.root / item['path']).read_bytes()), item['new_sha256'])

    def test_write_error_restores_originals(self):
        actual = self.module.atomic_write
        target = self.root / self.module.PAYLOAD[1]['path']
        fired = [False]
        def fail_once(path, data, mode=0o644):
            if path == target and not fired[0]:
                fired[0] = True
                raise OSError('simulated write failure')
            return actual(path, data, mode)
        self.module.atomic_write = fail_once
        self.assertEqual(self.module.update(self.root), 'error')
        for item in self.module.PAYLOAD:
            self.assertEqual(self.module.digest((self.root / item['path']).read_bytes()), item['old_sha256'])
        self.assertEqual(self.settings.read_bytes(), self.original_settings)


if __name__ == '__main__':
    unittest.main()
