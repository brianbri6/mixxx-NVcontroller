#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Package the offline LCD report and reproducible analysis, not a Pi updater."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT):
        raise SystemExit('Commit tracked changes before packaging the analysis.')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    names = ['analysis/lcd_fields.py', 'scripts/analyze_lcd_fields.py',
             'scripts/verify_captures.py', 'scripts/package_lcd_analysis.py',
             'nvdisplay/__init__.py', 'nvdisplay/framing.py', 'INPUTS.json',
             'baseline_sources/v04/sources/usb_capture.py',
             'baseline_sources/v04/sources/display_protocol.py',
             'baseline_sources/v04/MIT_LICENSE.txt']
    names += [str(p.relative_to(ROOT)) for p in sorted((ROOT/'docs/lcd_capture_analysis').iterdir())
              if p.is_file()]
    members = {name: (ROOT/name).read_bytes() for name in names}
    members['START_HERE.txt'] = (
        'Numark NV LCD capture analysis — 2026-10-10\n\n'
        'Read docs/lcd_capture_analysis/REPORT.md. Open the PNGs beside it to see\n'
        'actual captured waveform pixels. evidence.json has byte/packet details.\n\n'
        'This is an offline analysis bundle, not a Pi firmware/update package.\n'
        'It does not send MIDI, replay USB, or require attached hardware.\n\n'
        'To reproduce: install Python 3.9+ (no extra modules needed), put the\n'
        'three original files in project_sources/ with these exact names:\n'
        '  03-numarknvplatterwithaudio.pcapng\n'
        '  04-numarknvplatter.pcapng\n'
        '  05-NumarkNVVDJ.pcapng\n'
        'The full project recovery checkpoint also contains these captures.\n'
        'Then, from the directory containing this file, run:\n'
        '  python3 scripts/analyze_lcd_fields.py\n'
        '  python3 scripts/verify_captures.py\n\n'
        'Expected: 4328 LCD records and 131 new text records re-encoded exactly.\n'
        'The packaging script itself requires the full Git checkout.\n'
        'No runtime or Pi updater changes were made in this analysis task.\n'
    ).encode()
    manifest = {'source_commit': commit, 'hardware_tested': False, 'pi_update': False,
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(members.items())}}
    members['MANIFEST.json'] = (json.dumps(manifest, indent=2)+'\n').encode()
    out = ROOT/'dist/NV_LCD_Capture_Analysis.zip'
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(members.items()):
            info = zipfile.ZipInfo(name, (2026, 10, 10, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(out) as archive:
        assert archive.testzip() is None
        for name, sha in manifest['files'].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == sha
    print(out)
    print('sha256=' + hashlib.sha256(out.read_bytes()).hexdigest())
    print('bytes=' + str(out.stat().st_size))


if __name__ == '__main__':
    main()
