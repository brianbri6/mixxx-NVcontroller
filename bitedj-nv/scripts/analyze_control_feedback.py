#!/usr/bin/env python3
"""Extract bounded original-NV control evidence; never replay MIDI."""
import collections
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'baseline_sources/v04/sources'))
from usb_capture import midi_events

SOURCES = {'03-numarknvplatterwithaudio.pcapng':20,
           '04-numarknvplatter.pcapng':20, '05-NumarkNVVDJ.pcapng':14}

def main():
    evidence = {'format':1, 'hardware_tested':False, 'sources':{}, 'records':[]}
    pins = json.loads((ROOT/'INPUTS.json').read_text())
    for name, device in SOURCES.items():
        path = ROOT/'project_sources'/name
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert pins[str(path.relative_to(ROOT))] == digest
        evidence['sources'][name] = {'sha256':digest, 'control_device':device}
        records = {}
        for event in midi_events(path, device=device):
            if event['kind'] != 'short' or event['cable'] != 0 or event['endpoint'] & 127 != 1:
                continue
            status, address, value = event['data']
            category = None
            if event['direction'] == 'out':
                if status == 0xb0 and address in (0x48,0x49,0x4b): category = 'meter'
                elif 0x91 <= status <= 0x94 and 0x47 <= address <= 0x4e: category = 'pad_palette'
                elif status == 0x90 and address in (0x0f,0x10,0x11,0x13,0x14,0x15): category = 'fx_led'
            elif status == 0xb0 and address in (4,5,6,0x49,0x4a,0x4b): category = 'fx_knob'
            if category:
                key = (category, status, address)
                row = records.setdefault(key, {'capture':name, 'direction':event['direction'],
                    'category':category,'status':status,'address':address,'counts':collections.Counter(), 'examples':[]})
                if not row['counts'][value] and len(row['examples']) < 8:
                    row['examples'].append({'packet':event['packet'], 'bytes':list(event['data'])})
                row['counts'][value] += 1
        evidence['records'].extend(records[k] for k in sorted(records))
    out = ROOT/'docs/control-feedback-evidence.json'
    out.write_text(json.dumps(evidence, indent=2)+'\n')
    colors=sorted({int(v) for r in evidence['records'] if r['category']=='pad_palette' for v in r['counts']})
    print('Records:',len(evidence['records']),'captured pad codes:',colors)

if __name__ == '__main__': main()
