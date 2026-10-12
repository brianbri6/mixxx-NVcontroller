from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def bindings(path):
    controls = ET.parse(path).findall('./controller/controls/control')
    result = {}
    for control in controls:
        address = (int(control.findtext('status'), 0), int(control.findtext('midino'), 0))
        if address in result:
            raise AssertionError('Duplicate MIDI input: ' + str(address))
        result[address] = (control.findtext('group'), control.findtext('key'))
    return result


class MappingTests(unittest.TestCase):
    def test_diagnostics_preserve_every_existing_control_and_cannot_send_output(self):
        previous = bindings(ROOT/'baseline_sources/v04/sources/payload/Numark-NV-BiteDJ-Test.midi.xml')
        current = bindings(ROOT/'controller/Numark-NV-BiteDJ-Test.midi.xml')
        for address, target in previous.items():
            self.assertEqual(current[address], target, address)
        fx = {(status, note): 'BiteDJNV.fxButton' for status in (0x80, 0x90)
              for note in (15, 16, 17, 19, 20, 21)}
        fx.update({(0xb0, cc): 'BiteDJNV.fxKnob' for cc in (4, 5, 6, 73, 74, 75)})
        for address in current.keys() - previous.keys():
            self.assertEqual(current[address][1], fx.get(address, 'BiteDJNV.observeInput'))
        for address, handler in fx.items():
            self.assertEqual(current[address][1], handler)
        # Every unknown note-on/CC in the documented NV channels is observable.
        for channel in range(5):
            for status in (0x90+channel, 0xb0+channel):
                for control in range(128):
                    self.assertIn((status, control), current)
