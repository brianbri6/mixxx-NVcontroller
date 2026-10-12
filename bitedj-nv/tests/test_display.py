import base64
import copy
import ctypes
import errno
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

from nvdisplay import protocol as p
from nvdisplay.framing import decode, pack_7bit, unpack_7bit
from nvdisplay.service import Screen, validate
from nvdisplay.transport import AlsaOutput, OutputQueue, discover


class Sink:
    def __init__(self, limit=1000000):
        self.data = bytearray()
        self.limit = limit
        self.closed = False

    def write(self, data):
        count = min(self.limit, len(data))
        self.data.extend(data[:count])
        return count

    def close(self):
        self.closed = True


def state(clock=0, generation=1, position=2000):
    return {'schema': 1, 'source': 'native', 'session': 'test', 'clock_ms': clock,
            'decks': [{'deck': 1, 'loaded': True, 'generation': generation,
                       'title': 'Test track', 'artist': 'Artist', 'original_bpm': 96,
                       'bpm': 96, 'pitch_percent': 0, 'range_percent': 8,
                       'duration_ms': 120000, 'position_ms': position, 'playing': True,
                       'beat_distance': 0.5, 'overview_ready': True,
                       'overview': base64.b64encode(bytes([255, 0, 0, 120])*240).decode(),
                       'detail_ready': True, 'columns_per_second': 240,
                       'detail_start_ms': 1250,
                       'detail': base64.b64encode(bytes([0, 255, 0, 120])*480).decode()}]}


class ProtocolTests(unittest.TestCase):
    def test_capture_packets_roundtrip(self):
        records = json.loads((Path(__file__).parent/'fixtures/display_packets.json').read_text())
        for record in records:
            wire = bytes.fromhex(record['message_hex'])
            decoded = decode(wire)
            self.assertEqual(decoded['raw'], bytes.fromhex(record['raw_hex']))
            if record['command'] in p.LENGTHS:
                self.assertEqual(p.encode(decoded['display'], record['command'], decoded['raw']), wire)

    def test_all_byte_values_and_reject_unreviewed_commands(self):
        value = bytes(range(256))*4
        self.assertEqual(unpack_7bit(pack_7bit(value)), value)
        for side in ('left', 'right'):
            self.assertEqual(decode(p.encode(side, 0x30, value))['raw'], value)
        for command in (0x31, 0x50, 0x60):
            with self.assertRaises(ValueError):
                p.encode('left', command, bytes(1024))
        with self.assertRaises(ValueError):
            p.encode('left', 1, bytes(248))

    def test_numeric_capture_layout(self):
        deck = {'deck': 1, 'bpm': 96, 'pitch_percent': 0, 'range_percent': 8}
        self.assertEqual(p.numeric(deck), bytes.fromhex('00 39 36 2e 30 00 00 00 2b 30 2e 30 00 00 00 38 00 00 00'))
        raw = p.playhead({'deck': 4, 'position_ms': 1200, 'beat_distance': 0.5}, 123456, 1.08)
        self.assertEqual(struct.unpack('<BIiHi', raw), (3, 123456, 1200, 683, 1080))

    def test_platter_angle_follows_1800ms_rotation_not_track_beats(self):
        for position, angle in [(0, 0), (450, 256), (900, 512), (1350, 768),
                                (1800, 0), (2250, 256), (-450, 768)]:
            for bpm, beat in [(96, 0), (127, 0.75)]:
                raw = p.playhead({'deck': 1, 'position_ms': position,
                                  'bpm': bpm, 'beat_distance': beat}, 0, 0)
                self.assertEqual(struct.unpack('<BIiHi', raw)[3], angle)

    def test_metadata_fields_and_surrogates(self):
        raw = p.metadata({'deck': 2, 'loaded': True, 'title': 'A'*46+'😀',
                          'artist': 'Artist', 'key': 'C#m', 'duration_ms': 228963})
        self.assertEqual(len(raw), 249)
        self.assertEqual(raw[0], 1)
        self.assertEqual(raw[1:97].decode('utf-16-le').rstrip('\0'), 'A'*46)
        self.assertEqual(raw[97:193].decode('utf-16-le').rstrip('\0'), 'Artist')
        self.assertEqual(raw[199:241].decode('utf-16-le').rstrip('\0'), 'C#m')
        self.assertEqual(struct.unpack('<I', raw[245:])[0], 228963)

    def test_overview_chunks_reconstruct_bitmap_and_detail_header(self):
        peaks = bytes([255, 0, 0, 255])*240
        records = p.overview(3, peaks)
        reconstructed = bytearray()
        for i, record in enumerate(records):
            deck, chunk, size = struct.unpack('<BHH', record[:5])
            self.assertEqual((deck, chunk), (2, i+1))
            self.assertEqual(size, 512 if i < 7 else 256)
            reconstructed.extend(record[5:5+size])
        self.assertEqual(reconstructed, p.raster(peaks, 16))
        self.assertEqual(len(reconstructed), 3840)
        tile = p.detail(1, 6500, peaks[:120])
        self.assertEqual(struct.unpack('<BBIHH', tile[:10]), (0, 1, 6500, 1, 2160))
        self.assertEqual(len(tile), 2170)
        with self.assertRaises(ValueError):
            p.detail(1, 6510, peaks[:120])


class TransportTests(unittest.TestCase):
    def test_control_priority_keeps_partial_waveform_framing_and_survives_overflow(self):
        sink = Sink()
        queue = OutputQueue(sink, 0, rate=100, burst=2, max_records=2)
        queue.put('wave', b'abcdef', 0)
        queue.pump(0)
        queue.put('far', b'old', 0)
        queue.put('head', b'H', 0, priority=2)
        queue.put('near', b'N', 0, priority=1)
        self.assertNotIn('far', queue.queue)
        for now in (0.02, 0.04, 0.06, 0.08):
            queue.pump(now)
        self.assertEqual(sink.data, b'abcdefHN')

    def test_alsa_uses_exclusive_nonblocking_output_and_preserves_busy_error(self):
        lib = mock.Mock()
        lib.snd_rawmidi_open.return_value = 0
        lib.snd_rawmidi_write.side_effect = [-errno.EAGAIN, 3]
        with mock.patch('nvdisplay.transport.ctypes.CDLL', return_value=lib):
            output = AlsaOutput('hw:3,0,0')
            args = lib.snd_rawmidi_open.call_args.args
            self.assertEqual((args[0], args[2], args[3]), (None, b'hw:3,0,0', 2))
            output.handle = ctypes.c_void_p(123)
            self.assertEqual(output.write(b'abc'), 0)
            self.assertEqual(output.write(b'abc'), 3)
            output.close()
            lib.snd_rawmidi_drop.assert_called_once()
            lib.snd_rawmidi_close.assert_called_once()
            lib.snd_rawmidi_open.return_value = -errno.EBUSY
            with self.assertRaises(OSError) as caught:
                AlsaOutput('hw:4,0,0')
            self.assertEqual(caught.exception.errno, errno.EBUSY)
            self.assertIn('keep NV Audio sound output enabled', str(caught.exception))

    def test_partial_write_never_interleaves_and_ack_waits_for_completion(self):
        sink = Sink(3)
        queue = OutputQueue(sink, 0, rate=1, burst=3)
        done = []
        queue.put('a', b'abcdef', 0, done=lambda: done.append('a'))
        queue.put('b', b'XYZ', 0)
        queue.pump(0)
        self.assertEqual(done, [])
        queue.rate = 100
        queue.pump(0.03)
        self.assertEqual(done, ['a'])
        queue.pump(0.06)
        self.assertEqual(sink.data, b'abcdefXYZ')

    def test_expiry_overflow_latest_value_and_partial_stall(self):
        sink = Sink(0)
        queue = OutputQueue(sink, 0, max_records=2)
        queue.put('a', b'old', 0)
        queue.put('a', b'new', 0)
        queue.put('b', b'b', 0)
        queue.put('c', b'c', 0, ttl=0.1)
        self.assertEqual(len(queue.queue), 2)
        self.assertEqual(queue.dropped, 1)
        queue.pump(0.2)
        sink.limit = 100
        queue.pump(0.3)
        self.assertEqual(sink.data, b'b')
        self.assertEqual(queue.dropped, 2)
        partial = OutputQueue(Sink(1), 0, rate=1, burst=1)
        partial.put('tile', b'12345', 0)
        partial.pump(0)
        with self.assertRaises(TimeoutError):
            partial.pump(2)

    def test_invalidation_finishes_partial_sysex_without_stale_ack(self):
        sink = Sink(2)
        queue = OutputQueue(sink, 0, rate=100, burst=2)
        done = []
        queue.put((1, 9), b'abcdef', 0, done=lambda: done.append('stale'))
        queue.pump(0)
        queue.invalidate(lambda k: k[0] == 1)
        queue.put((1, 9), b'NEW', 0.01)
        for now in (0.02, 0.04, 0.06, 0.08):
            queue.pump(now)
        self.assertEqual(sink.data, b'abcdefNEW')
        self.assertEqual(done, [])

    def test_ports_follow_usb_identity_not_card_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sound = root/'sound'
            sound.mkdir()
            for card, product in ((7, '1033'), (1, '2033'), (0, '1005')):
                device = root/product
                device.mkdir()
                (device/'idVendor').write_text('15e4\n')
                (device/'idProduct').write_text(product+'\n')
                node = device/('midiC'+str(card)+'D0')
                node.mkdir()
                (sound/node.name).symlink_to(node)
            self.assertEqual(discover(sound), {'left': 'hw:7,0,0', 'right': 'hw:1,0,0'})
            duplicate = root/'1033/midiC8D0'
            duplicate.mkdir()
            (sound/duplicate.name).symlink_to(duplicate)
            self.assertIsNone(discover(sound)['left'])


class ScreenTests(unittest.TestCase):
    def test_two_moving_layers_keep_playhead_live_during_full_waveform_backfill(self):
        screen = Screen('left', Sink(), 0, 'full')
        for i in range(401):
            data = state(clock=i*50, position=2000+i*50)
            center = (2000+i*50)//125*125
            data['decks'][0]['detail_start_ms'] = center-750
            second = copy.deepcopy(data['decks'][0])
            second['deck'] = 3
            data['decks'].append(second)
            screen.update(validate(data), i*0.05)
            screen.tick(i*0.05)
            if i > 20:
                for deck in (1, 3):
                    clock = struct.unpack('<BIiHi', decode(screen.acked[(deck, 5, 0)])['raw'])[1]
                    self.assertLessEqual(i*50-clock, 100)
            if i >= 300:  # sustained playback once both full windows are primed
                for deck in (1, 3):
                    for n in range(-3, 5):
                        self.assertIn((deck, 9, center+n*125), screen.acked)
        for deck in (1, 3):
            self.assertEqual(screen.status()['decks'][deck]['detail_tiles_sent'], 16)
        self.assertLessEqual(screen.queue.bytes_sent, 6000+45000*20)

    def test_full_window_fills_all_sixteen_tiles_on_both_layers(self):
        screen = Screen('left', Sink(), 0, 'full')
        for i in range(80):
            data = state(clock=i*50)
            second = copy.deepcopy(data['decks'][0])
            second['deck'] = 3
            data['decks'].append(second)
            screen.update(validate(data), i*0.05)
            screen.tick(i*0.05)
        for deck in (1, 3):
            tiles = {k[2] for k in screen.acked if k[:2] == (deck, 9)}
            self.assertEqual(tiles, set(range(1250, 3250, 125)))
            coverage = screen.status()['decks'][deck]
            self.assertEqual(coverage['detail_tiles_sent'], 16)
            self.assertEqual(coverage['overview_chunks_sent'], 8)
            self.assertTrue(coverage['detail_ready'])
            self.assertTrue(coverage['metadata_sent'])
            for timestamp in tiles:
                self.assertTrue(any(decode(screen.acked[(deck, 9, timestamp)])['raw'][10:]))
        self.assertLessEqual(screen.queue.bytes_sent, 6000 + 45000 * 4)

    def test_pre_roll_and_analysis_pending_have_explicit_coverage(self):
        screen = Screen('right', Sink(), 0, 'full')
        for i in range(50):
            data = state(clock=i*50, position=-125)
            deck = data['decks'][0]
            deck.update(deck=2, detail_ready=False, overview_ready=False)
            screen.update(validate(data), i*0.05)
            screen.tick(i*0.05)
        coverage = screen.status()['decks'][2]
        self.assertFalse(coverage['detail_ready'])
        self.assertEqual(coverage['detail_window'], list(range(0, 1125, 125)))
        self.assertEqual(coverage['detail_tiles_sent'], 9)
        self.assertEqual(decode(screen.acked[(2, 9, 0)])['raw'][10:], bytes(2160))

    def test_paused_scratch_reports_signed_motion_and_seek_resets_speed(self):
        screen = Screen('left', Sink(), 0)
        for clock, position, expected in [(0, 0, 0), (50, 100, 2000),
                                          (100, 50, -1000), (150, 5000, 0),
                                          (200, 5000, 0)]:
            data = state(clock=clock, position=position)
            data['decks'][0]['playing'] = False
            screen.update(validate(data), clock/1000)
            screen.tick(clock/1000)
            raw = decode(screen.acked[(1, 5, 0)])['raw']
            self.assertEqual(struct.unpack('<BIiHi', raw)[4], expected)

    def test_reverting_to_acked_value_cancels_unsent_stale_record(self):
        screen = Screen('left', Sink(), 0)
        a = p.metadata({'deck': 1, 'loaded': True, 'title': 'A'})
        b = p.metadata({'deck': 1, 'loaded': True, 'title': 'B'})
        screen.record(1, 1, 0, a, 0)
        screen.tick(0)
        screen.record(1, 1, 0, b, 0.1)
        screen.record(1, 1, 0, a, 0.11)
        screen.tick(0.12)
        self.assertEqual(decode(screen.acked[(1, 1, 0)])['raw'], a)

    def test_reverting_during_partial_write_finishes_then_corrects_record(self):
        sink = Sink()
        screen = Screen('left', sink, 0)
        a = p.metadata({'deck': 1, 'loaded': True, 'title': 'A'})
        b = p.metadata({'deck': 1, 'loaded': True, 'title': 'B'})
        screen.record(1, 1, 0, a, 0)
        screen.tick(0)
        sink.data.clear()
        screen.queue.burst = 16
        screen.record(1, 1, 0, b, 0.1)
        screen.tick(0.1)
        self.assertEqual(screen.queue.active[4], 16)
        screen.record(1, 1, 0, a, 0.11)
        screen.queue.burst = 6000
        screen.tick(0.2)
        self.assertEqual(sink.data, p.encode('left', 1, b) + p.encode('left', 1, a))
        self.assertEqual(decode(screen.acked[(1, 1, 0)])['raw'], a)

    def test_watchdog_retries_expired_warning_and_all_blank_tiles(self):
        sink = Sink(0)
        screen = Screen('left', sink, 0, 'full')
        screen.update(validate(state()), 0)
        screen.tick(1.1)
        screen.tick(4)  # blocked beyond the first warning's deadline
        sink.limit = 1000000
        for i in range(30):
            screen.tick(4.01 + i*0.05)
        raw = decode(screen.acked[(1, 1, 0)])['raw']
        self.assertIn('data unavailable', raw[1:97].decode('utf-16-le'))
        for deck in (1, 3):
            for timestamp in (0, 125, 250, 375, 500):
                tile = decode(screen.acked[(deck, 9, timestamp)])['raw']
                self.assertEqual(tile[10:], bytes(2160))

    def test_expired_partial_write_correction_is_retried(self):
        sink = Sink()
        screen = Screen('left', sink, 0)
        a = p.metadata({'deck': 1, 'loaded': True, 'title': 'A'})
        b = p.metadata({'deck': 1, 'loaded': True, 'title': 'B'})
        screen.record(1, 1, 0, a, 0)
        screen.queue.pump(0)
        screen.queue.burst = 16
        screen.record(1, 1, 0, b, 0.1)
        screen.queue.pump(0.1)
        screen.record(1, 1, 0, a, 0.11, ttl=0.01)
        screen.queue.burst = 6000
        screen.queue.pump(0.2)  # finishes B, but the corrective A has expired
        self.assertNotIn((1, 1, 0), screen.acked)
        screen.record(1, 1, 0, a, 0.21)
        screen.queue.pump(0.22)
        self.assertEqual(decode(screen.acked[(1, 1, 0)])['raw'], a)

    def test_validation_rejects_bad_and_duplicate_snapshots(self):
        data = state()
        validate(data)
        for field, value in [('bpm', float('nan')), ('detail', 'bad'), ('deck', True)]:
            bad = copy.deepcopy(data)
            bad['decks'][0][field] = value
            with self.assertRaises(ValueError):
                validate(bad)
        data['decks'].append(data['decks'][0])
        with self.assertRaises(ValueError):
            validate(data)

    def test_side_routing_and_overview_only_on_change(self):
        screen = Screen('left', Sink(), 0, 'overview')
        screen.update(validate(state()), 0)
        for i in range(20):
            screen.tick(i*0.02)
        self.assertTrue(all(k[0] in (1, 3, 'aux') for k in screen.acked))
        overview_packets = {k: v for k, v in screen.acked.items() if k[1] == 7}
        self.assertEqual(len(overview_packets), 16)
        screen.update(validate(state(clock=500)), 0.5)
        self.assertFalse(any(k[1] == 7 for k in screen.queue.queue))
        screen.tick(0.5)
        self.assertEqual(overview_packets, {k: v for k, v in screen.acked.items() if k[1] == 7})

    def test_dropped_tile_is_retried_not_marked_sent(self):
        screen = Screen('left', Sink(0), 0, 'full')
        screen.update(validate(state()), 0)
        key = next(k for k in screen.queue.queue if k[:2] == (1, 9))
        screen.queue.queue.pop(key)  # simulate TTL/overflow eviction
        self.assertNotIn(key, screen.acked)
        screen.update(validate(state(clock=50)), 0.05)
        self.assertIn(key, screen.queue.queue)

    def test_new_track_and_seek_remove_old_queued_tiles(self):
        screen = Screen('left', Sink(0), 0, 'full')
        screen.update(validate(state()), 0)
        old = {k for k in screen.queue.queue if k[:2] == (1, 9)}
        new = state(clock=100, generation=2, position=9000)
        new['decks'][0]['detail_start_ms'] = 8250
        screen.update(validate(new), 0.1)
        self.assertFalse(old & set(screen.queue.queue))
        newer = state(clock=200, generation=2, position=20000)
        newer['decks'][0]['detail_start_ms'] = 19250
        screen.update(validate(newer), 0.2)
        self.assertTrue(all(k[2] >= 19750 for k in screen.queue.queue if k[:2] == (1, 9)))

    def test_watchdog_stops_playhead_and_session_restart_recovers(self):
        screen = Screen('left', Sink(), 0, 'info')
        screen.update(validate(state()), 0)
        # Startup now includes explicit auxiliary clears and exceeds one
        # burst; finish those records before simulating absent snapshots.
        for i in range(7):
            screen.tick(i*0.05)
        screen.tick(1.1)
        self.assertTrue(screen.stale)
        raw = decode(screen.acked[(1, 5, 0)])['raw']
        self.assertEqual(struct.unpack('<BIiHi', raw)[4], 0)
        self.assertFalse(screen.update(validate(state()), 1.2))
        restarted = state()
        restarted['session'] = 'new'
        self.assertTrue(screen.update(validate(restarted), 1.3))
        self.assertFalse(screen.stale)

    def test_unload_clears_track_and_overview(self):
        screen = Screen('left', Sink(), 0, 'overview')
        screen.update(validate(state()), 0)
        for i in range(20):
            screen.tick(i*0.02)
        screen.update(validate({'schema': 1, 'source': 'native', 'session': 'test',
                                'clock_ms': 500, 'decks': []}), 0.5)
        for i in range(20):
            screen.tick(0.5+i*0.02)
        raw = decode(screen.acked[(1, 1, 0)])['raw']
        self.assertEqual(raw[1:193], bytes(192))
        self.assertEqual(decode(screen.acked[(1, 7, 0)])['raw'][5:], bytes(512))


if __name__ == '__main__':
    unittest.main()
