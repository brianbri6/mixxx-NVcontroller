#!/usr/bin/env python3
"""Check all ELF NEEDED libraries against the retained Pi4 runtime, recursively."""
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
runtime = ROOT/'work/rootfs'
binary = ROOT/'work/build-arm/mixxx'
readelf = ROOT/'work/hostroot/usr/bin/aarch64-linux-gnu-readelf'
env = dict(os.environ, LD_LIBRARY_PATH=str(ROOT/'work/host-compat'))
search = [runtime/'usr/lib/aarch64-linux-gnu', runtime/'lib/aarch64-linux-gnu',
          runtime/'usr/lib', runtime/'lib']
visited, missing = {}, []
queue = [binary]
while queue:
    file = queue.pop()
    if str(file) in visited:
        continue
    headers = subprocess.check_output([str(readelf), '-h', str(file)], env=env, text=True)
    if 'AArch64' not in headers:
        raise SystemExit('Non-ARM64 library: ' + str(file))
    dynamic = subprocess.check_output([str(readelf), '-d', str(file)], env=env, text=True)
    needs = re.findall(r'\(NEEDED\).*?\[(.*?)\]', dynamic)
    extra = []
    for paths in re.findall(r'\((?:RPATH|RUNPATH)\).*?\[(.*?)\]', dynamic):
        for directory in paths.split(':'):
            if '$ORIGIN' in directory or '${ORIGIN}' in directory:
                extra.append(Path(directory.replace('${ORIGIN}', str(file.parent)).replace('$ORIGIN', str(file.parent))))
            elif directory.startswith('/'):
                extra.append(runtime/directory.lstrip('/'))
    visited[str(file)] = needs
    for name in needs:
        candidates = [directory/name for directory in extra+search]
        resolved = next((path for path in candidates if path.is_file()), None)
        if resolved is None:
            missing.append({'file': str(file), 'library': name})
        else:
            queue.append(resolved)
result = {'binary': str(binary.relative_to(ROOT)), 'runtime': str(runtime.relative_to(ROOT)),
          'native_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
          'checked_elf_files': len(visited), 'missing': missing, 'hardware_tested': False,
          'scope': 'ELF architecture and recursive NEEDED presence; execution separately checked with QEMU'}
(ROOT/'work/abi-audit.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result, indent=2))
raise SystemExit(1 if missing else 0)
