#!/usr/bin/env python3
"""Recheck the supplied captures offline; no USB/MIDI replay."""
import collections
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'baseline_sources/v04/sources'))
from usb_capture import midi_events
from display_protocol import decode, pack_7bit

def angle_fit(rows):
    # Unwrap only across continuous positions. A seek/load reset must not be
    # interpreted as a platter turn. Keep reversals within a scratch gesture.
    segments = [[]]
    for row in rows:
        if segments[-1] and abs(row[2]-segments[-1][-1][2]) > 500:
            segments.append([])
        segments[-1].append(row)
    rows = max(segments, key=lambda s: max(r[2] for r in s)-min(r[2] for r in s))
    x, y, previous, unwrapped = [], [], None, 0
    for _, _, position, angle, _ in rows:
        unwrapped = angle if previous is None else unwrapped + (angle-previous+512) % 1024 - 512
        previous = angle
        x.append(position)
        y.append(unwrapped)
    xm, ym = sum(x)/len(x), sum(y)/len(y)
    xx = sum((v-xm)**2 for v in x)
    yy = sum((v-ym)**2 for v in y)
    xy = sum((a-xm)*(b-ym) for a, b in zip(x, y))
    result = {'samples': len(rows), 'position_span_ms': max(x)-min(x),
              'period_ms': 1024*xx/xy if xy else None,
              'correlation': xy/math.sqrt(xx*yy) if xx*yy else None}
    result['sufficient_rotation_span'] = result['position_span_ms'] >= 3600
    return result

expected = json.loads((ROOT/'INPUTS.json').read_text())
coverage = {'03-numarknvplatterwithaudio.pcapng': 2154,
            '04-numarknvplatter.pcapng': 1377, '05-NumarkNVVDJ.pcapng': 797, '10-led-test1.pcapng': 130}
results = []
for file in sorted((ROOT/'project_sources').glob('*.pcapng')):
    relative = str(file.relative_to(ROOT))
    sha = hashlib.sha256(file.read_bytes()).hexdigest()
    if sha != expected[relative]:
        raise SystemExit('Input capture changed: ' + relative)
    counts = collections.Counter()
    rotations = collections.defaultdict(list)
    selectors = collections.defaultdict(set)
    bpms = set()
    grids = []
    for event in midi_events(file):
        message = event['data']
        if event['kind'] != 'sysex' or not message.startswith(b'\xf0\x47'):
            continue
        record = decode(message)
        assert pack_7bit(record['raw']) == message[10:-1]
        counts[(record['display'], record['command'], len(record['raw']))] += 1
        side, command, raw = record['display'], record['command'], record['raw']
        if command in (1, 4, 5, 7, 9, 0x31):
            selectors[side].add(raw[0])
        if command == 5:
            rotations[(side, raw[0])].append(struct.unpack('<BIiHi', raw))
        if command in (1, 4):
            bpm = (raw[193:199] if command == 1 else raw[1:8]).decode('ascii').rstrip('\0')
            if bpm:
                bpms.add(bpm)
        if command == 0x31:
            assert len(raw) == 2049
            pairs = [struct.unpack('<If', raw[i:i+8]) for i in range(1, len(raw), 8)
                     if any(raw[i:i+8])]
            grids.append({'side': side, 'selector': raw[0], 'nonzero_uint32_float32_pairs': pairs})
    fits = [{'side': side, 'selector': selector, **angle_fit(rows)}
            for (side, selector), rows in sorted(rotations.items())]
    for fit in fits:
        if fit['sufficient_rotation_span']:
            assert 1790 < fit['period_ms'] < 1810 and fit['correlation'] > 0.999, fit
    assert sum(counts.values()) == coverage[file.name], (file.name, sum(counts.values()))
    results.append({'file': relative, 'sha256': sha, 'validated': sum(counts.values()),
                    'bpm_strings': sorted(bpms), 'angle_fits': fits,
                    'selectors': {k: sorted(v) for k, v in selectors.items()}, 'command31': grids,
                    'records': [{'side': k[0], 'command': hex(k[1]), 'bytes': k[2], 'count': n}
                                for k, n in sorted(counts.items())]})
total = sum(r['validated'] for r in results)
if len(results) != 4 or total != 4458:
    raise SystemExit('Capture coverage differs from the recovered baseline')
(ROOT/'work').mkdir(exist_ok=True)
(ROOT/'work/capture-validation.json').write_text(json.dumps(results, indent=2)+'\n')
print('PASS:', total, 'display messages across', len(results), 'captures; no hardware output')
