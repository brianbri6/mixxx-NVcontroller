#!/usr/bin/env python3
"""AI-generated documentation.
Reproduce timing and direction-safe LED evidence offline, without MIDI output.
Capture timing is not a hardware refresh-rate measurement.
End AI-generated documentation.
"""
import collections
import hashlib
import json
from pathlib import Path
import statistics
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'baseline_sources/v04/sources'))
from usb_capture import midi_events, packets
from display_protocol import decode


def main():
    pins = json.loads((ROOT/'INPUTS.json').read_text())
    report = {'hardware_tested': False, 'timing': [], 'led_outputs': []}
    for filename in ('03-numarknvplatterwithaudio.pcapng', '04-numarknvplatter.pcapng', '10-led-test1.pcapng'):
        path = ROOT/'project_sources'/filename
        assert hashlib.sha256(path.read_bytes()).hexdigest() == pins[str(path.relative_to(ROOT))]
        identities = {}
        for p in packets(path):
            raw = p['payload']
            if p['transfer'] == 2 and p['endpoint'] == 0x80 and p['status'] == 0 and raw[:2] == b'\x12\x01' and len(raw) >= 18:
                identities[(p['bus'], p['device'])] = struct.unpack_from('<HH', raw, 8)
        timing, outputs = collections.defaultdict(list), collections.defaultdict(collections.Counter)
        for e in midi_events(path):
            if e['direction'] != 'out':
                continue
            raw = e['data']
            if filename.startswith('10-') and e['kind'] == 'short' and e['cable'] == 0 and e['endpoint'] == 1:
                if identities.get((e['bus'],e['device'])) == (0x15e4,0x1005):
                    outputs[(raw[0], raw[1])][raw[2]] += 1
            if e['kind'] == 'sysex' and raw.startswith(b'\xf0\x47'):
                d = decode(raw)
                if d['command'] in (5,9):
                    key = (e['bus'],e['device'],e['endpoint'],d['display'],d['raw'][0],d['command'])
                    timing[key].append(e['time'])
        for key, times in sorted(timing.items()):
            intervals = [(b-a)*1000 for a,b in zip(times,times[1:])]
            report['timing'].append({'capture':filename, 'bus':key[0], 'device':key[1], 'endpoint':key[2],
                'tag':key[3], 'selector':key[4], 'command':key[5], 'messages':len(times),
                'median_interval_ms':statistics.median(intervals) if intervals else None})
        if outputs:
            assert len(outputs) == 112
            report['led_outputs'] = [{'status':k[0],'address':k[1],'values':dict(v)} for k,v in sorted(outputs.items())]
            palette = sorted({n for (s,a),v in outputs.items() if 0x91 <= s <= 0x94 and 0x47 <= a <= 0x4e for n in v})
            assert palette == [0,3,4,6,12,16,21,48,52]
            report['pad_palette'] = palette
    (ROOT/'docs/HANDOFF_EVIDENCE.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'led_outputs'}, indent=2))


if __name__ == '__main__':
    main()
