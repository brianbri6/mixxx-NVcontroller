# SPDX-License-Identifier: MIT
"""Capture-grounded NV records. This module never opens a hardware device."""
import base64
import math
import struct
from functools import lru_cache
from pathlib import Path
from .framing import pack_7bit

LENGTHS = {0x01: 249, 0x04: 19, 0x05: 15, 0x06: 7, 0x07: 517,
           0x08: 7, 0x09: 2170, 0x0a: 97, 0x21: 131,
           0x22: 129, 0x24: 361, 0x30: 1024}
PALETTE = Path(__file__).with_name('palette.bin').read_bytes()
COLORS = [(PALETTE[i+2], PALETTE[i+1], PALETTE[i]) for i in range(0, 1024, 4)]
PLATTER_PERIOD_MS = 1800  # 33 1/3 RPM; observed at both 96 and 127 BPM.


@lru_cache(maxsize=216)
def palette_index(rgb):
    return min(range(2, 256), key=lambda i: sum((COLORS[i][b]-rgb[b])**2 for b in range(3)))


def encode(side, command, raw):
    if side not in ('left', 'right'):
        raise ValueError('Unknown side')
    if command not in LENGTHS or len(raw) != LENGTHS[command]:
        raise ValueError('Unreviewed command or record length')
    packed = pack_7bit(raw)
    outer = len(packed) + 2
    return bytes((0xf0, 0x47, 0x10 if side == 'left' else 0x20, 0x33, 5, command,
                  outer >> 7, outer & 127, len(packed) >> 7, len(packed) & 127)) + packed + b'\xf7'


def selector(deck):
    if type(deck) is not int or not 1 <= deck <= 4:
        raise ValueError('Invalid deck number')
    return deck - 1


def number(value, low, high):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('Non-finite numeric field')
    return max(low, min(high, value))


def ascii_field(text, size):
    return str(text).replace('\0', ' ').encode('ascii', 'replace')[:size-1].ljust(size, b'\0')


def utf16_field(text, size):
    value = str(text).replace('\0', ' ').encode('utf-16-le', 'replace')[:size-2]
    if value and 0xd800 <= int.from_bytes(value[-2:], 'little') <= 0xdbff:
        value = value[:-2]
    return value.ljust(size, b'\0')


def single_line(text):
    return str(text).replace('\0', ' ').replace('\r', ' ').replace('\n', ' ')


def effects(side, slots):
    if side not in ('left', 'right') or len(slots) > 3:
        raise ValueError('Invalid effect bank')
    labels = []
    for slot in slots:
        name = single_line(slot.get('name', ''))[:24]
        percent = slot.get('meta_percent')
        label = name
        if name and percent is not None:
            label += '\r\n' + str(round(number(percent, 0, 100))) + '%'
        labels.append(label)
    return effect_labels(side, labels)


def effect_labels(side, labels):
    if side not in ('left', 'right') or len(labels) > 3:
        raise ValueError('Invalid effect bank')
    return bytes([0 if side == 'left' else 1]) + b''.join(
        ascii_field(label, 32) for label in labels).ljust(96, b'\0')


def folder_row(index, name=''):
    if type(index) is not int or not 0 <= index < 8:
        raise ValueError('Invalid folder row')
    name = single_line(name)
    # Keep the observed populated/clear bytes; their icon/depth semantics
    # have not been established by the available captures.
    return bytes([index, 6 if name else 0, 2 if name else 0]) + utf16_field(name, 128)


def browser_heading(name=''):
    name = single_line(name)
    return bytes([6 if name else 0]) + utf16_field(name, 128)


def song_row(index, track=None):
    if type(index) is not int or not 0 <= index < 7:
        raise ValueError('Invalid song row')
    if track is None:
        return bytes([index]) + bytes(360)
    bpm = track.get('bpm')
    text = '' if bpm is None or bpm <= 0 else str(round(number(bpm, 0, 999)))
    return (bytes([index]) + utf16_field(single_line(track.get('title', '')), 256) +
            utf16_field(single_line(track.get('artist', '')), 96) + ascii_field(text, 4) +
            b'\xff'*4)  # Observed VDJ populated style; not an artwork identifier.


def browser_visibility(side, mode='preserve'):
    if side not in ('left', 'right') or mode not in ('preserve', 'performance', 'left', 'right', 'both'):
        raise ValueError('Invalid browser visibility test')
    if mode == 'preserve':
        return None
    # Captured B0 16 00/01 only. This opt-in experiment is not a D. VIEW cycle.
    return bytes([0xb0, 0x16, int(mode == 'both' or mode == side)])


def metadata(deck):
    loaded = deck.get('loaded', False)
    return (bytes([selector(deck['deck'])]) +
            utf16_field(deck.get('title', '') if loaded else '', 96) +
            utf16_field(deck.get('artist', '') if loaded else '', 96) +
            ascii_field(f"{number(deck.get('original_bpm', 0), 0, 999.9):.1f}", 6) +
            utf16_field(deck.get('key', '') if loaded else '', 42) + b'\0'*4 +
            struct.pack('<I', int(number(deck.get('duration_ms', 0), 0, 2**32-1))))


def numeric(deck):
    return (bytes([selector(deck['deck'])]) +
            ascii_field(f"{number(deck.get('bpm', 0), 0, 999.9):.1f}", 7) +
            ascii_field(f"{number(deck.get('pitch_percent', 0), -100, 100):+.1f}", 7) +
            ascii_field(f"{number(deck.get('range_percent', 8), 0, 100):g}", 4))


def playhead(deck, clock_ms, speed):
    position = int(number(deck.get('position_ms', 0), -2**31, 2**31-1))
    # This is the virtual platter angle, not the track's beat phase. Captures
    # show 1024 units per turn. Negative pre-roll wraps around the same circle.
    angle = round((position % PLATTER_PERIOD_MS) * 1024 / PLATTER_PERIOD_MS) % 1024
    return struct.pack('<BIiHi', selector(deck['deck']), int(clock_ms) & 0xffffffff,
                       position, angle,
                       round(number(speed, -16, 16) * 1000))


def decode_peaks(value, columns):
    if not isinstance(value, str) or len(value) > columns * 8:
        raise ValueError('Invalid peak data')
    data = base64.b64decode(value, validate=True)
    if len(data) != columns * 4:
        raise ValueError('Unexpected peak count')
    return data


def raster(peaks, height):
    if len(peaks) % 4 or height <= 0:
        raise ValueError('Invalid raster dimensions')
    width = len(peaks) // 4
    result = bytearray(width * height)
    # Quantize to the actual capture palette, including its index ordering.
    for x in range(width):
        low, mid, high, amplitude = peaks[x*4:x*4+4]
        if not amplitude:
            continue
        maximum = max(low, mid, high, 1)
        rgb = tuple(round(b * 5 / maximum) * 51 for b in (low, mid, high))
        # Cache 216 web-safe colors using the observed palette's actual ordering.
        index = palette_index(rgb)
        half = max(1, round(amplitude / 255 * (height / 2)))
        for y in range(max(0, height//2-half), min(height, height//2+half)):
            result[y*width+x] = index
    return bytes(result)


def overview(deck, peaks):
    if len(peaks) != 240*4:
        raise ValueError('Overview must have 240 columns')
    bitmap = raster(peaks, 16)
    records = []
    for index in range(8):
        chunk = bitmap[index*512:(index+1)*512]
        records.append(struct.pack('<BHH', selector(deck), index+1, len(chunk)) + chunk.ljust(512, b'\0'))
    return records


def detail(deck, timestamp_ms, peaks):
    if len(peaks) != 30*4 or timestamp_ms < 0 or timestamp_ms % 125:
        raise ValueError('Detail requires one aligned 125ms tile')
    bitmap = raster(peaks, 72)
    return struct.pack('<BBIHH', selector(deck), 1, timestamp_ms, 1, len(bitmap)) + bitmap


def startup(side):
    return [encode(side, 0x06, bytes.fromhex('01 f0 00 10 00 08 00')),
            encode(side, 0x08, bytes.fromhex('01 1e 00 20 00') +
                   (b'\x01\0' if side == 'left' else b'\x02\0')),
            encode(side, 0x30, PALETTE), b'\xb0\x10\0']
