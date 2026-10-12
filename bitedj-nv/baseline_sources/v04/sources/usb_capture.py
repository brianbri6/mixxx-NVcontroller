#!/usr/bin/env python3
"""Read USBPcap pcapng records and USB-MIDI events without replaying USB data.

Offline analysis only. No hardware access or third-party Python dependencies.
"""
import collections
import struct
from pathlib import Path


def packets(path):
    endian = '<'
    interfaces = []
    with Path(path).open('rb') as stream:
        index = 0
        while header := stream.read(8):
            if len(header) != 8:
                raise ValueError('Truncated pcapng header')
            if header[:4] == b'\x0a\x0d\x0d\x0a':
                bom = stream.read(4)
                endian = '<' if bom == b'\x4d\x3c\x2b\x1a' else '>'
                kind, size = struct.unpack(endian + 'II', header)
                body = bom + stream.read(size - 12)
                interfaces = []
            else:
                kind, size = struct.unpack(endian + 'II', header)
                if size < 12 or size % 4:
                    raise ValueError('Invalid pcapng block size')
                body = stream.read(size - 8)
            if len(body) != size - 8 or struct.unpack(endian + 'I', body[-4:])[0] != size:
                raise ValueError('Truncated or inconsistent pcapng block')
            if kind == 1:
                link, _, snap = struct.unpack(endian + 'HHI', body[:8])
                resolution = 1e-6
                cursor = 8
                while cursor + 4 <= len(body) - 4:
                    code, length = struct.unpack(endian + 'HH', body[cursor:cursor+4])
                    val = body[cursor+4:cursor+4+length]
                    cursor += 4 + ((length + 3) & ~3)
                    if code == 0:
                        break
                    if code == 9 and length == 1:
                        resolution = (2 ** -(val[0] & 127)) if val[0] & 128 else 10 ** -val[0]
                interfaces.append((link, resolution))
            elif kind == 6:
                index += 1
                interface, hi, lo, captured, original = struct.unpack(endian + 'IIIII', body[:20])
                if captured > original or len(body) < 24 + ((captured + 3) & ~3):
                    raise ValueError('Invalid captured packet size')
                link, resolution = interfaces[interface]
                if link != 249:
                    continue
                raw = body[20:20+captured]
                if len(raw) < 27:
                    continue
                hdr, irp, status, function, info, bus, device, endpoint, transfer, length = struct.unpack('<HQIHBHHBBI', raw[:27])
                if hdr < 27 or hdr > len(raw):
                    raise ValueError('Invalid USBPcap header size')
                payload = raw[hdr:hdr+length]
                yield dict(packet=index, time=(hi * 2**32 + lo) * resolution,
                           bus=bus, device=device, endpoint=endpoint, transfer=transfer,
                           function=function, info=info, status=status,
                           header=raw[:hdr], payload=payload, declared_length=length)


def midi_events(path, device=None):
    """Select successful IN completions / OUT submissions, once per USB transfer."""
    sysex = {}
    for packet in packets(path):
        if device is not None and packet['device'] != device:
            continue
        incoming = bool(packet['endpoint'] & 128)
        if packet['status'] or packet['transfer'] != 3 or packet['info'] != (1 if incoming else 0):
            continue
        payload = packet['payload']
        if len(payload) % 4:
            continue
        for pos in range(0, len(payload), 4):
            code, a, b, c = payload[pos:pos+4]
            cable, cin = code >> 4, code & 15
            base = {k: packet[k] for k in ('packet', 'time', 'bus', 'device', 'endpoint')}
            base.update(direction='in' if incoming else 'out', cable=cable)
            key = (packet['bus'], packet['device'], packet['endpoint'], cable)
            if cin in (4, 5, 6, 7):
                data = bytes((a, b, c))[:3 if cin == 4 else cin - 4]
                if data.startswith(b'\xf0'):
                    sysex[key] = bytearray()
                if key not in sysex:
                    continue
                sysex[key].extend(data)
                if cin != 4:
                    message = bytes(sysex.pop(key))
                    if message.endswith(b'\xf7'):
                        yield dict(base, kind='sysex', data=message)
            elif cin in (8, 9, 10, 11, 12, 13, 14) and (a >> 4) == cin and b < 128 and c < 128:
                yield dict(base, kind='short', data=bytes((a, b, c)))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture')
    args = parser.parse_args()
    counts = collections.Counter()
    for message in midi_events(args.capture):
        data = message['data']
        signature = data[:min(len(data), 8)].hex(' ') if message['kind'] == 'sysex' else data[:2].hex(' ')
        counts[(message['device'], message['endpoint'], message['direction'], message['kind'], signature, len(data))] += 1
    for key, count in counts.most_common():
        print(count, key)
