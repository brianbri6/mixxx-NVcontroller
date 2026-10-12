import copy
import json
from pathlib import Path
import struct
import unittest

from nvdisplay import protocol as p
from nvdisplay.framing import decode
from nvdisplay.service import Screen, validate
from test_display import Sink, state


def auxiliary(data):
    data['effects'] = [{'unit': 1, 'slots': [{'name': 'Reverb', 'meta_percent': 50}]},
                       {'unit': 2, 'slots': [{'name': 'Echo', 'meta_percent': 25}]}]
    data['browser'] = {'available': True, 'heading': 'Favorite tracks',
                       'folders': ['Music', 'Favorite tracks'], 'selected_folder': 1,
                       'tracks': [{'title': '3am', 'artist': 'Loe Shimmy', 'bpm': 127},
                                  {'title': 'Unknown', 'artist': '', 'bpm': None}],
                       'selected_row': 0, 'first_row': 0, 'total_rows': 2}
    return data


def fields(screen, command, index=0):
    return decode(screen.acked[('aux', command, index)])['raw']


def text(raw):
    return raw.decode('utf-16-le').split('\0')[0]


class IntegrationTests(unittest.TestCase):
    def test_captured_populated_and_clear_records(self):
        records = json.loads((Path(__file__).parent/'fixtures/lcd_text_records.json').read_text())
        checked = {10: 0, 33: 0, 34: 0, 36: 0}
        for record in records:
            raw, f, command = bytes.fromhex(record['raw_hex']), record['fields'], record['command']
            self.assertEqual(decode(p.encode(record['side'], command, raw))['raw'], raw)
            if command == 10:
                result = p.effect_labels(record['side'], f['labels'])
            elif command == 33:
                result = p.folder_row(f['visible_row'], f['folder_name'])
            elif command == 34:
                if f['unknown_type_or_flags'] not in (0, 6):
                    continue  # Stems uses a different category; not emitted here.
                result = p.browser_heading(f['header_text'])
            else:
                track = None if not any(raw[1:]) else {
                    'title': f['title'], 'artist': f['artist'],
                    'bpm': int(f['bpm_text']) if f['bpm_text'] else None}
                result = p.song_row(f['visible_row'], track)
            self.assertEqual(result, raw, (record['file'], record['packet']))
            checked[command] += 1
        self.assertTrue(all(v >= 3 for v in checked.values()))

    def test_text_bounds_and_unreviewed_commands(self):
        raw = p.song_row(6, {'title': 'A'*126+'😀', 'artist': 'line\n2\0', 'bpm': 123.6})
        self.assertEqual(len(raw), 361)
        self.assertEqual(text(raw[1:257]), 'A'*126)
        self.assertEqual(text(raw[257:353]), 'line 2 ')
        self.assertEqual(raw[353:357], b'124\0')
        raw = p.effects('left', [{'name': 'N'*100+'\r\n', 'meta_percent': 100}])
        self.assertEqual(raw[1:33].split(b'\0')[0], b'N'*24+b'\r\n100%')
        self.assertEqual(p.song_row(0, {'bpm': None})[353:357], bytes(4))
        for command, size in [(2, 65), (3, 9), (16, 10), (32, 10), (35, 10), (49, 2049)]:
            with self.assertRaises(ValueError):
                p.encode('left', command, bytes(size))

    def test_optional_schema_rejects_unbounded_invalid_auxiliary(self):
        validate(state())  # Older producer remains accepted.
        validate(auxiliary(state()))
        mutations = [lambda d: d['effects'].append(d['effects'][0]),
                     lambda d: d['effects'][0]['slots'][0].update(meta_percent=float('nan')),
                     lambda d: d['browser'].update(folders=['x']*9),
                     lambda d: d['browser'].update(selected_row=2),
                     lambda d: d['browser']['tracks'][0].update(bpm=True),
                     lambda d: d['browser']['tracks'][0].update(title='x'*257)]
        for mutation in mutations:
            data = auxiliary(state())
            mutation(data)
            with self.assertRaises(ValueError):
                validate(data)

    def test_per_screen_effects_shared_browser_and_current_selection(self):
        for side, label, bank in [('left', b'Reverb\r\n50%', 0), ('right', b'Echo\r\n25%', 1)]:
            screen = Screen(side, Sink(), 0)
            screen.update(validate(auxiliary(state())), 0)
            for i in range(9):
                screen.tick(i*0.05)
            self.assertEqual(fields(screen, 10)[0], bank)
            self.assertEqual(fields(screen, 10)[1:33].split(b'\0')[0], label)
            self.assertEqual(text(fields(screen, 33, 1)[3:]), '> Favorite tracks')
            self.assertEqual(text(fields(screen, 36)[1:257]), '> 3am')
            self.assertEqual(fields(screen, 36, 1)[353:357], bytes(4))
            status = screen.status()['auxiliary']
            self.assertEqual((status['folder_rows_sent'], status['song_rows_sent']), (8, 7))
            self.assertTrue(status['effects_sent'])

    def test_late_bpm_and_shorter_list_clear_without_resending_unchanged_fields(self):
        screen = Screen('left', Sink(), 0)
        data = auxiliary(state())
        screen.update(validate(data), 0)
        for i in range(9): screen.tick(i*0.05)
        data['clock_ms'] = 500
        data['browser']['tracks'][1]['bpm'] = 160  # Same caller object; cache must be copied.
        screen.update(validate(data), 0.5)
        keys = {k for k in screen.queue.queue if k[0] == 'aux'}
        self.assertEqual(keys, {('aux', 36, 1)})
        screen.tick(0.5)
        self.assertEqual(fields(screen, 36, 1)[353:357], b'160\0')
        data['clock_ms'] = 1000
        data['browser'].update(tracks=[], selected_row=-1, total_rows=0, folders=[], selected_folder=-1)
        screen.update(validate(data), 1)
        for i in range(9): screen.tick(1+i*0.05)
        self.assertEqual(fields(screen, 36)[1:], bytes(360))
        self.assertEqual(fields(screen, 33, 1)[1:], bytes(130))

    def test_dropped_auxiliary_retry_stale_clear_and_restart(self):
        sink = Sink(0)
        screen = Screen('left', sink, 0)
        data = auxiliary(state())
        screen.update(validate(data), 0)
        screen.queue.queue.pop(('aux', 36, 0))
        data['clock_ms'] = 50
        screen.update(validate(data), 0.05)
        self.assertIn(('aux', 36, 0), screen.queue.queue)
        screen.tick(3)  # All previously queued auxiliary values have expired.
        sink.limit = 1000000
        for i in range(10): screen.tick(3.1+i*0.05)
        self.assertEqual(fields(screen, 36)[1:], bytes(360))
        self.assertEqual(fields(screen, 10)[1:], bytes(96))
        self.assertFalse(screen.status()['auxiliary']['browser_available'])
        data.update(session='restarted', clock_ms=0)
        screen.update(validate(data), 4)
        for i in range(10): screen.tick(4+i*0.05)
        self.assertEqual(text(fields(screen, 36)[1:257]), '> 3am')

    def test_two_playing_layers_and_fast_browsing_keep_playhead_priority_and_byte_cap(self):
        screen = Screen('left', Sink(), 0, 'full')
        max_delay = 0
        for i in range(801):
            data = auxiliary(state(clock=i*50, position=2000+i*50))
            center = (2000+i*50)//125*125
            data['decks'][0]['detail_start_ms'] = center-750
            second = copy.deepcopy(data['decks'][0])
            second['deck'] = 3
            data['decks'].append(second)
            page = min(i//4, 50)  # Change all seven text rows at 5 Hz, then stop browsing.
            data['browser'].update(tracks=[{'title': 'Page '+str(page)+' row '+str(j), 'artist': 'Artist', 'bpm': 128} for j in range(7)],
                                   total_rows=1000, first_row=page)
            screen.update(validate(data), i*0.05)
            screen.tick(i*0.05)
            if i > 20:
                for deck in (1, 3):
                    clock = struct.unpack('<BIiHi', decode(screen.acked[(deck, 5, 0)])['raw'])[1]
                    max_delay = max(max_delay, i*50-clock)
            self.assertLessEqual(len(screen.queue.queue), 48)
        self.assertLessEqual(max_delay, 100)
        self.assertLessEqual(screen.queue.bytes_sent, 6000+45000*40)
        for deck in (1, 3):
            self.assertEqual(screen.status()['decks'][deck]['detail_tiles_sent'], 16)

    def test_browser_visibility_is_explicit_and_uses_only_captured_values(self):
        for side in ('left', 'right'):
            self.assertIsNone(p.browser_visibility(side))
            for mode in ('performance', 'left', 'right', 'both'):
                self.assertEqual(p.browser_visibility(side, mode),
                                 bytes([0xb0, 0x16, int(mode in (side, 'both'))]))
                screen = Screen(side, Sink(), 0, browser_view=mode)
                self.assertEqual(screen.queue.queue[('startup', 'browser')][1], p.browser_visibility(side, mode))
        with self.assertRaises(ValueError): p.browser_visibility('left', 'cycle')


if __name__ == '__main__':
    unittest.main()
