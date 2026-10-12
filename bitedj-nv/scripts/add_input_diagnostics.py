#!/usr/bin/env python3
"""Add bounded, read-only diagnostics without replacing any existing binding."""
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT/'controller/Numark-NV-BiteDJ-Test.midi.xml'
BEGIN = '            <!-- BEGIN generated unmapped-input diagnostics -->'
END = '            <!-- END generated unmapped-input diagnostics -->'


def update():
    text = TARGET.read_text()
    if BEGIN in text:
        start, end = text.index(BEGIN), text.index(END) + len(END) + 1
        text = text[:start] + text[end:]
    document = ET.fromstring(text)
    used = {(int(c.findtext('status'), 0), int(c.findtext('midino'), 0))
            for c in document.findall('./controller/controls/control')}
    rows = []
    # The original NV uses global channel 0 and deck channels 1..4. Unknown
    # note-on and CC messages are logged, never echoed or assigned an action.
    for channel in range(5):
        for status in (0x90 + channel, 0xb0 + channel):
            for control in range(128):
                if (status, control) in used:
                    continue
                group = '[Master]' if channel == 0 else f'[Channel{channel}]'
                rows.append('            <control><group>'+group+'</group>'
                            '<key>BiteDJNV.observeInput</key><status>'+hex(status)+'</status>'
                            '<midino>'+hex(control)+'</midino><options>'
                            '<script-binding /></options></control>')
    marker = '        </controls>'
    assert text.count(marker) == 1
    TARGET.write_text(text.replace(marker, BEGIN+'\n'+'\n'.join(rows)+'\n'+END+'\n'+marker))
    print(f'Added {len(rows)} diagnostic bindings; retained {len(used)} existing bindings')


if __name__ == '__main__':
    update()
