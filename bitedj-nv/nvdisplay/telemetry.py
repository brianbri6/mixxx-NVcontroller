# SPDX-License-Identifier: MIT
"""AI-generated documentation.
Bounded display-only prediction from the native 20 Hz snapshots. This module
never reads tracks, analyzes peaks, or controls audio. Limits are engineering
choices for testing, not measured firmware requirements.
End AI-generated documentation.
"""
import math


class TransportTelemetry:
    def __init__(self, hz=60):
        if not 20 <= hz <= 60 or not math.isfinite(hz):
            raise ValueError('Transport rate must be between 20 and 60 Hz')
        self.interval = 1.0 / hz
        self.next_tick = 0.0
        self.samples = {}
        self.ticks = 0
        self.discontinuities = 0

    def clear(self):
        self.samples.clear()
        self.next_tick = 0.0

    def observe(self, deck, clock, now):
        number = deck['deck']
        old = self.samples.get(number)
        identity = (deck['generation'], deck['loaded'])
        position = deck.get('position_ms', 0) if deck['loaded'] else 0
        playing = bool(deck.get('playing', False))
        speed = 0.0
        discontinuity = old is None or old['identity'] != identity
        horizon = 0.0
        if not discontinuity:
            dt = clock - old['clock']
            delta = position - old['position_ms']
            discontinuity = (dt == 0 and delta != 0) or dt < 0 or dt > 150 or abs(delta) > max(125, dt * 4)
            if not discontinuity and dt > 0 and playing == old['playing'] and deck['loaded']:
                velocity = delta / dt
                if abs(velocity) <= 4:
                    speed = velocity
                    horizon = min(dt, 50) if playing else min(dt, 16)
        if discontinuity:
            self.discontinuities += 1
            self.next_tick = 0.0
        self.samples[number] = {
            'deck': number, 'identity': identity, 'position_ms': position,
            'clock': clock, 'received': now, 'speed': speed, 'horizon_ms': horizon,
            'playing': playing, 'duration_ms': max(0, deck.get('duration_ms', 0)),
        }
        return discontinuity

    def due(self, now):
        if now + 1e-9 < self.next_tick or not self.samples:
            return []
        if self.next_tick == 0 or now - self.next_tick >= self.interval:
            self.next_tick = now + self.interval
        else:
            self.next_tick += self.interval
        self.ticks += 1
        records = []
        for sample in self.samples.values():
            age = max(0.0, (now - sample['received']) * 1000)
            elapsed = min(age, sample['horizon_ms'])
            speed = sample['speed'] if age <= sample['horizon_ms'] else 0.0
            position = sample['position_ms'] + elapsed * sample['speed']
            duration = sample['duration_ms']
            if duration > 0 and sample['position_ms'] <= duration and position > duration:
                position, speed = duration, 0.0
            records.append(({'deck': sample['deck'], 'position_ms': position},
                            sample['clock'] + age, speed))
        return records
