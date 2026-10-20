import copy
import struct
import re
import unittest
from unittest.mock import patch

from nvdisplay.telemetry import TransportTelemetry
from nvdisplay.framing import decode
from nvdisplay.service import Screen, validate
from test_display import Sink, state


class TelemetryTests(unittest.TestCase):
    def sample(self, t, clock, position, now, **extra):
        d = state(clock, position=position)['decks'][0]
        d.update(extra)
        t.observe(d, clock, now)
        return t.due(now)

    def test_fast_updates_leave_waveform_work_at_snapshot_rate(self):
        sink = Sink()
        screen = Screen('left', sink, 0, 'full')
        original = screen.update_deck
        with patch.object(screen, 'update_deck', wraps=original) as update:
            for i in range(1001):
                now = i / 1000
                if i % 50 == 0:
                    data = state(i, position=2000+i)
                    other = copy.deepcopy(data['decks'][0])
                    other.update(deck=3, title='Other layer', position_ms=4000-i)
                    data['decks'].append(other)
                    screen.update(validate(data), now)
                screen.tick(now)
        self.assertEqual(update.call_count, 42)
        frames = [decode(p) for p in re.findall(b'\xf0[^\xf7]*\xf7', bytes(sink.data))]
        positions = [struct.unpack('<BIiHi', p['raw']) for p in frames
                     if p['command'] == 5 and p['raw'][0] == 0]
        other_positions = [p for p in frames if p['command'] == 5 and p['raw'][0] == 2]
        self.assertGreaterEqual(len(other_positions), 59)
        self.assertGreaterEqual(len(positions), 59)
        self.assertLessEqual(len(positions), 62)
        self.assertTrue(any(p[2] % 50 != 0 for p in positions[4:]))
        self.assertLessEqual(screen.queue.bytes_sent, 6000+45000)
        self.assertTrue(all(abs(p[4]) <= 1000 for p in positions))

    def test_prediction_is_bounded_when_native_stops(self):
        t = TransportTelemetry()
        self.sample(t, 0, 2000, 0)
        self.sample(t, 50, 2050, .05)
        positions = []
        for now in (.067, .084, .101, .3, 2):
            deck, clock, speed = t.due(now)[0]
            positions.append(deck['position_ms'])
            if now > .1:
                self.assertEqual(speed, 0)
        self.assertEqual(max(positions), 2100)
        self.assertEqual(positions[-1], positions[-2])

    def test_pause_reverse_seek_loop_unload_and_generation_reset(self):
        t = TransportTelemetry()
        self.sample(t, 0, 2000, 0)
        self.assertEqual(self.sample(t, 50, 2050, .05)[0][2], 1)
        self.assertEqual(self.sample(t, 100, 2075, .1, playing=False)[0][2], 0)
        self.assertEqual(self.sample(t, 150, 2025, .15, playing=False)[0][2], -1)
        self.assertEqual(t.due(.18)[0][0]['position_ms'], 2009)
        self.assertEqual(self.sample(t, 200, 10000, .2)[0][2], 0)
        self.assertEqual(self.sample(t, 250, 4000, .25)[0][2], 0)
        self.assertEqual(self.sample(t, 300, 4050, .3, generation=2)[0][2], 0)
        self.assertEqual(self.sample(t, 350, 9999, .35, loaded=False)[0][0]['position_ms'], 0)

    def test_no_catchup_burst_after_scheduler_stall_and_pause_at_end(self):
        t = TransportTelemetry()
        self.sample(t, 0, 950, 0, duration_ms=1000)
        self.sample(t, 50, 990, .05, duration_ms=1000)
        self.assertEqual(t.due(.08)[0][0]['position_ms'], 1000)
        self.assertEqual(t.due(.5)[0][2], 0)
        self.assertEqual(t.due(.5), [])
        for hz in (0, 19, 61, float('nan')):
            with self.assertRaises(ValueError):
                TransportTelemetry(hz)

    def test_seek_drops_stale_tiles_and_transport_preserves_partial_sysex(self):
        sink = Sink(0)
        screen = Screen('left', sink, 0, 'full')
        screen.update(validate(state()), 0)
        screen.queue.invalidate(lambda k: k[0] == 'startup')
        screen.queue.burst = 16
        screen.queue.tokens = 16
        sink.limit = 10000
        screen.tick(0)
        self.assertIsNotNone(screen.queue.active)
        before = screen.queue.active[1]
        screen.update(validate(state(50, generation=2, position=70000)), .05)
        screen.queue.burst = 6000
        screen.tick(.05)
        wire = bytes(sink.data)
        self.assertTrue(wire.startswith(before))
        for p in wire.split(b'\xf7')[:-1]:
            decode(p+b'\xf7')
        self.assertTrue(all(k[2] >= 69250 for k in screen.queue.queue if k[:2] == (1,9)))

    def test_identical_watchdog_snapshots_do_not_invalidate_blank_backfill(self):
        t = TransportTelemetry()
        self.sample(t, 1000, 0, 1, playing=False)
        d = state(1000, position=0)['decks'][0]
        d['playing'] = False
        self.assertFalse(t.observe(d, 1000, 2))


if __name__ == '__main__':
    unittest.main()
