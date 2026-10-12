#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reproduce LCD field evidence from the three pinned PCAPs, without hardware.

Uses only the Python standard library. Writes JSON and decoded bitmap PNGs.
Packet numbers refer to the USB packet that completes a SysEx. Times are
seconds since the first USBPcap packet in each file, not since first MIDI.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'baseline_sources/v04/sources')]
from usb_capture import midi_events, packets
from nvdisplay.framing import decode, pack_7bit
from analysis.lcd_fields import decode_fields, encode_text_fields

EXPECTED = {'03-numarknvplatterwithaudio.pcapng': 2154,
            '04-numarknvplatter.pcapng': 1377, '05-NumarkNVVDJ.pcapng': 797}
TEXT_COMMANDS = (0x0A, 0x21, 0x22, 0x24)
# Independent, manually inspected examples. Byte-exact re-encoding alone does
# not establish the meaning of a region: keep concrete decoded expectations.
GOLDEN = {
    ('04-numarknvplatter.pcapng', 2455): {'labels': ['LPF', 'DELAY', 'REVERB']},
    ('05-NumarkNVVDJ.pcapng', 2091): {'labels': ['PITCH\r\n+0', 'STEMS\r\nN/A', 'REVERB\r\n50%']},
    ('05-NumarkNVVDJ.pcapng', 3641): {'labels': ['PITCH\r\nPOS', 'STEMS\r\nVOX', 'REVERB\r\nSTR']},
    ('05-NumarkNVVDJ.pcapng', 2134): {'visible_row': 4, 'folder_name': 'Favorite tracks'},
    ('05-NumarkNVVDJ.pcapng', 1860): {'header_text': 'Favorite tracks'},
    ('05-NumarkNVVDJ.pcapng', 3339): {'visible_row': 4, 'title': '3am', 'artist': 'Loe Shimmy', 'bpm_text': '127'},
    ('05-NumarkNVVDJ.pcapng', 4177): {'visible_row': 3, 'title': '3am', 'artist': 'Loe Shimmy', 'bpm_text': '127'},
    ('05-NumarkNVVDJ.pcapng', 4233): {'visible_row': 6, 'title': 'A+', 'artist': 'Key Glock', 'bpm_text': '127'},
    ('05-NumarkNVVDJ.pcapng', 3535): {'title': '1942', 'bpm_text': '163'},
    ('05-NumarkNVVDJ.pcapng', 5159): {'title': '3am', 'key': 'Ebm', 'duration_ms': 136176},
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def reference(event, start):
    return {k: event[k] for k in ('packet', 'bus', 'device', 'endpoint', 'cable')} | {
        'seconds': round(event['time']-start, 6)}


def write_png(path, width, height, indices, bgra):
    """Lossless RGB rendering of indexed capture bytes (no resampling)."""
    assert len(indices) == width*height and len(bgra) == 1024
    def chunk(kind, data):
        return (struct.pack('>I', len(data)) + kind + data +
                struct.pack('>I', zlib.crc32(kind+data)))
    pixels = b''.join(bytes((bgra[v*4+2], bgra[v*4+1], bgra[v*4])) for v in indices)
    rows = b''.join(b'\0'+pixels[y*width*3:(y+1)*width*3] for y in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' +
                     chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
                     chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def extract_images(records, output, stem):
    palettes = {}
    overviews = defaultdict(dict)
    completed = {}
    details = defaultdict(dict)
    for rec in records:
        raw, cmd = rec['_raw'], rec['command']
        # Route palettes by USB destination, not the header tag: VDJ uses tag
        # 0x20 even for the palette sent to the device otherwise using 0x10.
        route = (rec['bus'], rec['device'], rec['cable'])
        if cmd == 0x30:
            palettes[route] = rec
        elif cmd == 7:
            key = route + (raw[0],)
            chunk, size = struct.unpack_from('<HH', raw, 1)
            if chunk == 1:
                overviews[key] = {}
            overviews[key][chunk] = (raw[5:5+size], rec['packet'])
            if sorted(overviews[key]) == list(range(1, 9)):
                bitmap = b''.join(overviews[key][i][0] for i in range(1, 9))
                assert len(bitmap) == 240*16
                if any(bitmap):
                    completed[key] = (bitmap, [overviews[key][i][1] for i in range(1, 9)])
        elif cmd == 9 and any(raw[10:]):
            key = route + (raw[0],)
            stamp = struct.unpack_from('<I', raw, 2)[0]
            details[key][stamp] = rec
    images = []
    for key, (bitmap, packet_numbers) in sorted(completed.items()):
        palette = palettes.get(key[:3])
        if palette is None:
            continue
        name = f'{stem}-dev{key[1]}-selector{key[3]}-overview.png'
        write_png(output/name, 240, 16, bitmap, palette['_raw'])
        images.append({'file': name, 'kind': 'overview', 'width': 240, 'height': 16,
                       'usb_device': key[1], 'selector': key[3], 'packets': packet_numbers,
                       'palette_packet': palette['packet'], 'indexed_sha256': digest(bitmap)})
    for key, tiles in sorted(details.items()):
        palette = palettes.get(key[:3])
        if palette is None:
            continue  # Never borrow an unrecorded palette from another capture.
        first = min(tiles)
        selected = []
        for stamp in range(first, first+32*125, 125):
            if stamp not in tiles:
                break
            selected.append(tiles[stamp])
        bitmap = b''.join(rec['_raw'][10+y*30:10+(y+1)*30]
                          for y in range(72) for rec in selected)
        name = f'{stem}-dev{key[1]}-selector{key[3]}-detail.png'
        write_png(output/name, len(selected)*30, 72, bitmap, palette['_raw'])
        images.append({'file': name, 'kind': 'detail', 'width': len(selected)*30, 'height': 72,
                       'usb_device': key[1], 'selector': key[3], 'first_tile_ms': first,
                       'end_exclusive_ms': first+len(selected)*125,
                       'packets': [r['packet'] for r in selected],
                       'palette_packet': palette['packet'], 'indexed_sha256': digest(bitmap),
                       'note': 'Last nonzero version of each tile, stitched in track-time order; not an LCD screenshot.'})
    return images


def analyze(path, expected_hash, output):
    sha = digest(path.read_bytes())
    if sha != expected_hash:
        raise ValueError(f'Capture hash mismatch: {path.name}')
    start = end = None
    packet_count = 0
    for packet in packets(path):
        if start is None:
            start = packet['time']
        end = packet['time']
        packet_count += 1
    events = list(midi_events(path))
    counts, routes, populated = Counter(), Counter(), Counter()
    records, variants, waves, motion = [], {}, [], defaultdict(list)
    checks = Counter()
    for event in events:
        wire = event['data']
        if event['kind'] != 'sysex' or not wire.startswith(b'\xf0\x47'):
            continue
        decoded = decode(wire)
        raw, command = decoded['raw'], decoded['command']
        if pack_7bit(raw) != wire[10:-1]:
            raise ValueError('Payload does not round-trip')
        fields = decode_fields(command, raw)
        golden = GOLDEN.get((path.name, event['packet']))
        if golden is not None:
            assert all(fields.get(k) == v for k, v in golden.items()), (path.name, event['packet'], fields)
            checks['manually_checked_examples'] += 1
        rec = reference(event, start) | {'header_tag': f'0x{wire[2]:02X}',
                'command': command, 'raw_bytes': len(raw), 'decoded': fields, '_raw': raw}
        records.append(rec)
        counts[command] += 1
        routes[(event['bus'], event['device'], event['cable'], wire[2])] += 1
        if command in TEXT_COMMANDS:
            if encode_text_fields(command, fields) != raw:
                raise ValueError(f'Text re-encode mismatch at {path.name}:{event["packet"]}')
            checks['new_text_records_reencoded_exactly'] += 1
            values = (fields['labels'] if command == 10 else
                      [fields['folder_name']] if command == 33 else
                      [fields['header_text']] if command == 34 else
                      [fields['title'], fields['artist'], fields['bpm_text']])
            if any(values):
                populated[command] += 1
        if command in (7, 9):
            waves.append({k: v for k, v in rec.items() if k != '_raw'})
        elif command == 5:
            motion[(event['bus'], event['device'], wire[2], raw[0])].append(rec)
        else:
            key = (event['bus'], event['device'], event['cable'], wire[2], command, raw)
            if key not in variants:
                variants[key] = {k: v for k, v in rec.items() if k != '_raw'} | {
                    'raw_hex': raw.hex(), 'occurrences': []}
            variants[key]['occurrences'].append({'packet': event['packet'], 'seconds': rec['seconds']})
    assert sum(counts.values()) == EXPECTED[path.name]
    assert checks['manually_checked_examples'] == sum(name == path.name for name, _ in GOLDEN)
    lcd_devices = {(r['bus'], r['device']) for r in records}
    short_lcd, incoming_notes = [], []
    short_summary = defaultdict(Counter)
    for event in events:
        if event['kind'] != 'short':
            continue
        data = event['data']
        key = (event['bus'], event['device'], event['direction'], data[0], data[1])
        short_summary[key][data[2]] += 1
        ref = reference(event, start) | {'direction': event['direction'], 'hex': data.hex(' ')}
        if (event['bus'], event['device']) in lcd_devices:
            short_lcd.append(ref)
        if event['direction'] == 'in' and data[0] & 0xF0 in (0x80, 0x90):
            incoming_notes.append(ref)
    motion_summary = []
    for key, values in sorted(motion.items()):
        fields = ('clock_ms', 'position_ms', 'angle_1024', 'speed_milli')
        motion_summary.append({'bus': key[0], 'device': key[1], 'header_tag': f'0x{key[2]:02X}',
            'selector': key[3], 'count': len(values), 'first_packet': values[0]['packet'],
            'last_packet': values[-1]['packet'], 'ranges': {
                field: [min(r['decoded'][field] for r in values), max(r['decoded'][field] for r in values)]
                for field in fields}})
    return {'file': str(path.relative_to(ROOT)), 'sha256': sha, 'bytes': path.stat().st_size,
            'time_origin': 'first USBPcap packet in this file; SysEx time is completion packet',
            'duration_seconds': round(end-start, 6), 'usb_packets': packet_count,
            'lcd_records': sum(counts.values()),
            'command_counts': {f'0x{c:02X}': n for c, n in sorted(counts.items())},
            'populated_new_text_counts': {f'0x{c:02X}': n for c, n in sorted(populated.items())},
            'checks': dict(checks), 'routes': [
                {'bus': k[0], 'device': k[1], 'cable': k[2], 'header_tag': f'0x{k[3]:02X}', 'count': n}
                for k, n in sorted(routes.items())],
            'low_rate_variants': list(variants.values()), 'waveform_records': waves,
            'motion_summary': motion_summary, 'lcd_short_messages': short_lcd,
            'incoming_notes_unlabelled': incoming_notes,
            'short_message_inventory': [
                {'bus': k[0], 'device': k[1], 'direction': k[2],
                 'status': f'0x{k[3]:02X}', 'address': f'0x{k[4]:02X}',
                 'value_counts': dict(sorted(v.items()))} for k, v in sorted(short_summary.items())],
            'images': extract_images(records, output, path.stem)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'docs/lcd_capture_analysis')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    inputs = json.loads((ROOT/'INPUTS.json').read_text())
    captures = [analyze(ROOT/'project_sources'/name, inputs['project_sources/'+name], args.output)
                for name in EXPECTED]
    result = {'schema': 1, 'analysis': 'Original Numark NV LCD fields; offline only',
              'offsets': 'zero-based, unpacked raw payload bytes',
              'runtime_changed': False, 'hardware_tested': False, 'captures': captures}
    (args.output/'evidence.json').write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n')
    total = sum(c['lcd_records'] for c in captures)
    texts = sum(c['checks'].get('new_text_records_reencoded_exactly', 0) for c in captures)
    print(f'PASS: {total} LCD records; {texts} new text records round-trip byte-for-byte; no hardware output')
    print(args.output/'evidence.json')
    for c in captures:
        print(Path(c['file']).name, c['lcd_records'], c['populated_new_text_counts'])


if __name__ == '__main__':
    main()
