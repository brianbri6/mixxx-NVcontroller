# SPDX-License-Identifier: MIT
"""ALSA raw-MIDI output; never detaches/resets a USB interface or touches audio."""
from collections import OrderedDict
import ctypes
import errno
import os
from pathlib import Path
import re

# ALSA rawmidi.h: APPEND=1, NONBLOCK=2. Never request append/shared writes:
# the queue owns message framing and needs exclusive, nonblocking output.
SND_RAWMIDI_NONBLOCK = 0x0002


def discover(sys_sound=Path('/sys/class/sound')):
    found = {'left': [], 'right': []}
    for node in sorted(Path(sys_sound).glob('midiC*D*')):
        match = re.fullmatch(r'midiC(\d+)D(\d+)', node.name)
        if not match:
            continue
        for parent in (node.resolve(), *node.resolve().parents):
            try:
                vendor = (parent / 'idVendor').read_text().strip().lower()
                product = (parent / 'idProduct').read_text().strip().lower()
            except OSError:
                continue
            if vendor == '15e4' and product in ('1033', '2033'):
                side = 'left' if product == '1033' else 'right'
                found[side].append('hw:' + match[1] + ',' + match[2] + ',0')
            break
    # Ambiguity is reported, never resolved by enumeration order.
    return {side: names[0] if len(names) == 1 else None for side, names in found.items()}


class AlsaOutput:
    def __init__(self, name):
        self.lib = ctypes.CDLL('libasound.so.2')
        self.lib.snd_rawmidi_open.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
                                             ctypes.c_char_p, ctypes.c_int]
        self.lib.snd_rawmidi_open.restype = ctypes.c_int
        self.lib.snd_rawmidi_write.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
        self.lib.snd_rawmidi_write.restype = ctypes.c_ssize_t
        self.lib.snd_rawmidi_drop.argtypes = [ctypes.c_void_p]
        self.lib.snd_rawmidi_close.argtypes = [ctypes.c_void_p]
        self.handle = ctypes.c_void_p()
        error = self.lib.snd_rawmidi_open(None, ctypes.byref(self.handle), name.encode(), SND_RAWMIDI_NONBLOCK)
        if error < 0:
            hint = '; disable NV Audio/Graphics in Devices (keep NV Audio sound output enabled)' if error == -errno.EBUSY else ''
            raise OSError(-error, 'Cannot open NV raw MIDI ' + name + ': ' + os.strerror(-error) + hint)

    def write(self, data):
        count = self.lib.snd_rawmidi_write(self.handle, data, len(data))
        if count in (-errno.EAGAIN, -errno.EWOULDBLOCK):
            return 0
        if count < 0:
            raise OSError(-count, 'NV MIDI write failed')
        return count

    def close(self):
        if self.handle:
            self.lib.snd_rawmidi_drop(self.handle)
            self.lib.snd_rawmidi_close(self.handle)
            self.handle = ctypes.c_void_p()


class OutputQueue:
    """Latest keyed records, byte budget, TTLs, and ACK only on completed writes.

    An in-flight SysEx always finishes before another message. Invalidating a
    deck removes unsent work and suppresses in-flight completion callbacks;
    the caller queues a new deck clear/update after that message.
    """
    def __init__(self, output, now, rate=45000, burst=6000, max_records=48):
        self.output, self.rate, self.burst = output, rate, burst
        self.tokens = float(burst)
        self.last = now
        self.max_records = max_records
        self.queue = OrderedDict()
        self.active = None
        self.sent = self.dropped = self.bytes_sent = 0

    def put(self, key, data, now, ttl=2.0, done=None, priority=0):
        entry = [key, bytes(data), now+ttl, done, 0, None, priority]
        self.queue[key] = entry
        if len(self.queue) > self.max_records:
            oldest_low_priority = min(self.queue, key=lambda k: self.queue[k][6])
            del self.queue[oldest_low_priority]
            self.dropped += 1

    def prioritize(self, key, priority):
        if key in self.queue:
            self.queue[key][6] = priority

    def contains(self, key):
        return key in self.queue or (self.active is not None and self.active[0] == key)

    def pending_data(self, key):
        if key in self.queue:
            return self.queue[key][1]
        if self.active is not None and self.active[0] == key:
            return self.active[1]
        return None

    def invalidate(self, predicate):
        for key in list(self.queue):
            if predicate(key):
                del self.queue[key]
                self.dropped += 1
        if self.active is not None and predicate(self.active[0]):
            if self.active[4] == 0:
                self.active = None
                self.dropped += 1
            else:
                self.active[3] = None  # complete framing, discard stale ACK

    def pump(self, now):
        self.tokens = min(self.burst, self.tokens + max(0, now-self.last)*self.rate)
        self.last = now
        budget = min(self.burst, int(self.tokens))
        while budget > 0:
            if self.active is None:
                if not self.queue:
                    return
                # Text and current playhead must not expire behind a waveform
                # backfill. Equal priorities keep insertion order. An active
                # partial record is still indivisible, regardless of priority.
                key = max(self.queue, key=lambda k: self.queue[k][6])
                # AI-generated queue note: Wait for a whole record's budget
                # before starting it, so a tile cannot consume a few tokens
                # and block newer playheads for the next 55 ms. Real partial
                # writes still finish without interleaving. Tiny test budgets
                # and records larger than burst retain incremental writes.
                # End AI-generated queue note.
                length = len(self.queue[key][1])
                if budget < length <= self.burst:
                    return
                self.active = self.queue.pop(key)
            entry = self.active
            key, data, deadline, done, offset, began, _ = entry
            if offset == 0 and now > deadline:
                self.active = None
                self.dropped += 1
                continue
            if offset and now-began > 0.5:
                raise TimeoutError('NV MIDI partial write stalled')
            chunk = data[offset:offset+budget]
            count = self.output.write(chunk)
            if count < 0 or count > len(chunk):
                raise OSError('Invalid raw MIDI write count')
            if count == 0:
                return
            if began is None:
                entry[5] = now
            entry[4] += count
            self.tokens -= count
            budget -= count
            self.bytes_sent += count
            if entry[4] == len(data):
                self.active = None
                self.sent += 1
                if done is not None:
                    done()

    def close(self):
        self.queue.clear()
        self.active = None
        self.output.close()
