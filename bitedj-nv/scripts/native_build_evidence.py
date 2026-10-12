#!/usr/bin/env python3
"""Bind a successfully built native executable to its exact patched sources."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PIN = '78074e05c8bf99ede6fedd755aa68bd222ba343c'
PROJECT = ('native/numarknvexporter.h', 'native/numarknvexporter.cpp', 'scripts/apply_native.py', 'native/browser_navigation.patch')
PATCHED = ('CMakeLists.txt', 'src/coreservices.cpp', 'src/library/library.h', 'src/library/library.cpp',
           'src/controllers/numarknvexporter.h', 'src/controllers/numarknvexporter.cpp',
           'src/library/sidebarmodel.cpp', 'src/widget/wlibrarysidebar.cpp')
STAMP = ROOT/'work/native-build.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inputs():
    source = ROOT/'vendor/bitedj'
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != PIN:
        raise ValueError('Unexpected upstream revision')
    for name in PROJECT[:2]:
        if (ROOT/name).read_bytes() != (source/'src/controllers'/Path(name).name).read_bytes():
            raise ValueError('Native sources differ from applied build tree')
    return {'upstream_commit': PIN, 'sources': {p: sha(ROOT/p) for p in PROJECT},
            'patched_sources': {p: sha(source/p) for p in PATCHED}}


def verify(binary):
    result = json.loads(STAMP.read_text())
    if result['native_sha256'] != sha(binary):
        raise ValueError('Native executable differs from successful build evidence')
    for key, value in inputs().items():
        if result[key] != value:
            raise ValueError('Native build evidence is stale: '+key)
    return result


def main():
    binary = ROOT/'work/build-arm/mixxx'
    incomplete = [str(p.relative_to(ROOT)) for p in (ROOT/'work/build-arm').rglob('*.o')
                  if p.stat().st_size == 0]
    if incomplete:
        raise ValueError('Incomplete object files from interrupted build: '+', '.join(incomplete))
    evidence = inputs()
    for name in PROJECT + tuple('vendor/bitedj/'+p for p in PATCHED):
        if (ROOT/name).stat().st_mtime_ns > binary.stat().st_mtime_ns:
            raise ValueError('Source newer than native executable: '+name)
    evidence.update(native_sha256=sha(binary), native_bytes=binary.stat().st_size,
                    hardware_tested=False)
    STAMP.write_text(json.dumps(evidence, indent=2)+'\n')
    print('Recorded successful native build:', evidence['native_sha256'])


if __name__ == '__main__':
    main()
