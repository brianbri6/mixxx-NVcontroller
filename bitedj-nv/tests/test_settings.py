import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

SOURCE = Path(__file__).resolve().parents[1]/'runtime/nv_settings.py'
spec = importlib.util.spec_from_file_location('nv_settings', SOURCE)
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.cfg = self.root/s.NV_CONFIG
        self.cfg.parent.mkdir(parents=True)
        self.original = ('[Soundcard]\nNV_Audio_device 3\nlatency 128\n\n'
                         '[ControllerPreset]\n' + ''.join(key+' '+s.NV_MAPPING+'\n' for key in
                          ('NV_Control_MIDI_1', *s.NV_DISPLAY_KEYS)) +
                         '[Controller]\nNV_Control_MIDI_1 1\nNV_Audio_MIDI_1 1\nNV_Graphics_MIDI_1 1\n'
                         'OTHER_CONTROLLER 1\n[Unrelated]\ncustom value with spaces\n')
        self.cfg.write_text(self.original)
        self.options = self.root/s.NV_OPTIONS
        self.options.parent.mkdir(parents=True)
        self.group = s.nv_setting_group('NV Control MIDI 1')

    def set_options(self, **values):
        self.options.write_text(json.dumps(values))

    def test_pad_palette_is_reversible_and_accepts_only_observed_codes(self):
        for code in s.NV_PAD_PALETTE:
            self.set_options(padColor1=code, padColor8=52)
            s.nv_apply_settings(self.root)
            self.assertEqual(s.nv_get(self.cfg.read_text(), self.group, 'padColor1'), str(code))
        s.nv_restore_settings(self.root)
        self.assertEqual(self.cfg.read_text(), self.original)

    def test_default_port_reservation_is_narrow_idempotent_and_reversible(self):
        s.nv_apply_settings(self.root)
        expected = self.original.replace('NV_Audio_MIDI_1 1', 'NV_Audio_MIDI_1 0').replace('NV_Graphics_MIDI_1 1', 'NV_Graphics_MIDI_1 0')
        self.assertEqual(self.cfg.read_text(), expected)
        stamp = self.cfg.stat().st_mtime_ns
        s.nv_apply_settings(self.root)
        self.assertEqual(self.cfg.stat().st_mtime_ns, stamp)
        s.nv_restore_settings(self.root)
        self.assertEqual(self.cfg.read_text(), self.original)
        s.nv_restore_settings(self.root)
        self.assertEqual(self.cfg.read_text(), self.original)

    def test_native_settings_group_defaults_and_boot_values(self):
        self.set_options(scratchSensitivity=4.5, vuTest=True)
        s.nv_apply_settings(self.root)
        self.assertEqual(s.nv_get(self.cfg.read_text(), self.group, 'scratchSensitivity'), '4.5')
        self.assertEqual(s.nv_get(self.cfg.read_text(), self.group, 'vuTest'), 'true')
        xml = ET.parse(SOURCE.parents[1]/'controller/Numark-NV-BiteDJ-Test.midi.xml')
        options = {e.attrib['variable']: e.attrib for e in xml.findall('.//settings//option')}
        self.assertEqual(set(options), set(s.NV_NUMBERS) | set(s.NV_BOOLEANS))
        self.assertEqual(options['scratchSensitivity']['default'], '2.0')
        for key, (low, high) in s.NV_NUMBERS.items():
            self.assertEqual((float(options[key]['min']), float(options[key]['max'])), (low, high))
        s.nv_restore_settings(self.root)
        self.assertEqual(self.cfg.read_text(), self.original)

    def test_rollback_merges_only_owned_keys_and_keeps_later_user_changes(self):
        self.set_options(scratchSensitivity=4, vuTest=False)
        s.nv_apply_settings(self.root)
        text = self.cfg.read_text().replace('latency 128', 'latency 256').replace('scratchSensitivity 4', 'scratchSensitivity 6')
        self.cfg.write_text(text)
        s.nv_restore_settings(self.root)
        text = self.cfg.read_text()
        self.assertIn('latency 256', text)
        self.assertEqual(s.nv_get(text, self.group, 'scratchSensitivity'), '6')
        self.assertIsNone(s.nv_get(text, self.group, 'vuTest'))
        self.assertEqual(s.nv_get(text, '[Controller]', 'NV_Audio_MIDI_1'), '1')

    def test_changed_boot_value_keeps_original_for_rollback(self):
        self.cfg.write_text(s.nv_set(self.original, self.group, 'scratchSensitivity', '1.25'))
        self.set_options(scratchSensitivity=4)
        s.nv_apply_settings(self.root)
        self.set_options(scratchSensitivity=2)
        s.nv_apply_settings(self.root)
        s.nv_restore_settings(self.root)
        self.assertEqual(s.nv_get(self.cfg.read_text(), self.group, 'scratchSensitivity'), '1.25')

    def test_reject_invalid_data_before_any_preference_changes(self):
        for values in ({'scratchSensitivity': 0}, {'scratchSensitivity': '4'}, {'scratchSensitivity': True},
                       {'scratchSensitivity': float('nan')}, {'vuTest': 1}, {'vuPeakLevel': 4.5}, {'padColor1': 4}, {'padColor2': 3.5}, {'padColor8': True}, {'command': 'anything'}):
            self.options.write_text(json.dumps(values))
            with self.assertRaises(ValueError):
                s.nv_apply_settings(self.root)
            self.assertEqual(self.cfg.read_text(), self.original)
            self.assertFalse((self.root/s.NV_JOURNAL).exists())

    def test_does_not_disable_other_presets_or_enable_inactive_controls(self):
        text = self.original.replace('NV_Audio_MIDI_1 '+s.NV_MAPPING, 'NV_Audio_MIDI_1 /custom/Other.xml').replace('NV_Control_MIDI_1 1', 'NV_Control_MIDI_1 0')
        self.cfg.write_text(text)
        s.nv_apply_settings(self.root)
        self.assertEqual(s.nv_get(self.cfg.read_text(), '[Controller]', 'NV_Audio_MIDI_1'), '1')
        self.assertEqual(s.nv_get(self.cfg.read_text(), '[Controller]', 'NV_Control_MIDI_1'), '0')

    def test_journal_precedes_write_and_interruption_can_rollback(self):
        def fail(path, data, mode=0o644):
            if path == self.cfg:
                self.assertTrue((self.root/s.NV_JOURNAL).exists())
                raise KeyboardInterrupt('power lost before config replace')
            s.nv_atomic_write(path, data, mode)
        with self.assertRaises(KeyboardInterrupt):
            s.nv_apply_settings(self.root, writer=fail)
        s.nv_restore_settings(self.root)
        self.assertEqual(self.cfg.read_text(), self.original)
        s.nv_apply_settings(self.root)
        s.nv_restore_settings(self.root)
        self.assertEqual(self.cfg.read_text(), self.original)

    def test_crlf_and_unrelated_bytes_preserved(self):
        original = self.original.replace('\n', '\r\n').encode()
        self.cfg.write_bytes(original)
        s.nv_apply_settings(self.root)
        s.nv_restore_settings(self.root)
        self.assertEqual(self.cfg.read_bytes(), original)

    def test_power_loss_after_config_replace_recovers_without_losing_user_settings(self):
        self.set_options(scratchSensitivity=8)
        def fail_after(path, data, mode=0o644):
            s.nv_atomic_write(path, data, mode)
            if path == self.cfg:
                raise KeyboardInterrupt('power lost after config replace')
        with self.assertRaises(KeyboardInterrupt):
            s.nv_apply_settings(self.root, writer=fail_after)
        self.assertEqual(s.nv_get(self.cfg.read_text(), self.group, 'scratchSensitivity'), '8')
        s.nv_restore_settings(self.root)
        self.assertEqual(self.cfg.read_text(), self.original)

    def test_unknown_journal_key_and_duplicate_target_fail_without_writes(self):
        s.nv_apply_settings(self.root)
        path = self.root/s.NV_JOURNAL
        state = json.loads(path.read_text())
        state['changes'][0]['key'] = 'OTHER_CONTROLLER'
        path.write_text(json.dumps(state))
        before = self.cfg.read_bytes()
        with self.assertRaises(ValueError):
            s.nv_restore_settings(self.root)
        self.assertEqual(self.cfg.read_bytes(), before)
        path.unlink()
        self.cfg.write_text(self.original.replace('NV_Audio_MIDI_1 1', 'NV_Audio_MIDI_1 1\nNV_Audio_MIDI_1 0'))
        with self.assertRaises(ValueError):
            s.nv_apply_settings(self.root)


if __name__ == '__main__':
    unittest.main()
