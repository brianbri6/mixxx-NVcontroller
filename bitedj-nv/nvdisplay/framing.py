#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline decoder for observed Numark NV LCD SysEx. Never sends MIDI or USB."""
import struct


def unpack_7bit(data):
    out = bytearray()
    accumulator = bits = 0
    for value in data:
        if value & 128:
            raise ValueError('Non-MIDI-safe byte in packed data')
        accumulator |= value << bits
        bits += 7
        while bits >= 8:
            out.append(accumulator & 255)
            accumulator >>= 8
            bits -= 8
    if accumulator:
        raise ValueError('Nonzero padding bits')
    return bytes(out)


def pack_7bit(data):
    out = bytearray()
    accumulator = bits = 0
    for value in data:
        accumulator |= value << bits
        bits += 8
        while bits >= 7:
            out.append(accumulator & 127)
            accumulator >>= 7
            bits -= 7
    if bits:
        out.append(accumulator & 127)
    return bytes(out)


def decode(message):
    if len(message) < 11 or message[:2] != b'\xf0\x47' or message[2] not in (0x10, 0x20) or message[3:5] != b'\x33\x05' or message[-1] != 0xf7:
        raise ValueError('Unrecognized NV display message')
    outer_length = message[6] * 128 + message[7]
    packed_length = message[8] * 128 + message[9]
    if outer_length != len(message) - 9 or packed_length != len(message) - 11:
        raise ValueError('Inconsistent display packet lengths')
    raw = unpack_7bit(message[10:-1])
    if pack_7bit(raw) != message[10:-1]:
        raise ValueError('Noncanonical packed payload')
    return dict(display='left' if message[2] == 0x10 else 'right',
                command=message[5], raw=raw, packed_size=packed_length)


if __name__ == '__main__':
    import argparse
    import collections
    import json
    from usb_capture import midi_events
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture')
    args = parser.parse_args()
    result = collections.Counter()
    for event in midi_events(args.capture):
        message = event['data']
        if event['kind'] != 'sysex' or not message.startswith(b'\xf0\x47'):
            continue
        decoded = decode(message)
        result[(decoded['display'], decoded['command'], len(decoded['raw']))] += 1
    print(json.dumps([dict(display=k[0], command=hex(k[1]), decoded_bytes=k[2], messages=n)
                      for k, n in sorted(result.items())], indent=2))
