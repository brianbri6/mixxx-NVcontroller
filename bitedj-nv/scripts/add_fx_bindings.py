#!/usr/bin/env python3
"""Promote only the original-NV reference FX addresses out of diagnostics."""
from pathlib import Path
from add_input_diagnostics import update, BEGIN, END
ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'controller/Numark-NV-BiteDJ-Test.midi.xml'
start='            <!-- BEGIN reviewed FX controls -->'
end='            <!-- END reviewed FX controls -->'
s=TARGET.read_text()
for a,b in ((BEGIN,END),(start,end)):
    if a in s:s=s[:s.index(a)]+s[s.index(b)+len(b)+1:]
rows=[]
for status, addresses, handler in [(0x90,(15,16,17,19,20,21),'fxButton'),(0x80,(15,16,17,19,20,21),'fxButton'),(0xb0,(4,5,6,73,74,75),'fxKnob')]:
    for address in addresses:
        rows.append(f'            <control><group>[Master]</group><key>BiteDJNV.{handler}</key><status>{hex(status)}</status><midino>{hex(address)}</midino><options><script-binding /></options></control>')
s=s.replace('        </controls>', start+'\n'+'\n'.join(rows)+'\n'+end+'\n        </controls>')
s=s.replace('Controls Test v0.5.3','Controls Test v0.5.8').replace('Expand / collapse selected library item','Browser: folders / enter leaf / return to folders')
if 'variable="padColor1"' not in s:
    options='\n'.join(f'            <option variable="padColor{i+1}" type="integer" min="0" max="52" default="{code}" label="Pad {i+1} captured color code" />' for i,code in enumerate((12,52,48,21,6,3,52,21)))
    s=s.replace('    </settings>', '        <group label="Pad palette (codes 0,3,6,12,21,48,52 only)">\n'+options+'\n        </group>\n    </settings>')
TARGET.write_text(s)
update()
