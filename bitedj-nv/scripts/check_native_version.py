#!/usr/bin/env python3
"""Check ARM64 --version under QEMU with original Pi runtime libraries only.

No GUI, telemetry socket, USB or audio is tested by this command.
"""
import json
import os
from pathlib import Path
import subprocess
from native_build_evidence import verify

ROOT = Path(__file__).resolve().parents[1]
binary = ROOT/'work/build-arm/mixxx'
evidence = verify(binary)
runtime_dir = ROOT/'work/version-runtime'
runtime_dir.mkdir(mode=0o700, exist_ok=True)
command = [str(ROOT/'work/hostroot/usr/bin/qemu-aarch64'), '-L', str(ROOT/'work/rootfs'),
           '-U', 'LD_LIBRARY_PATH', '-U', 'BITEDJ_NV_SOCKET',
           '-E', 'QT_QPA_PLATFORM=offscreen',
           '-E', 'QT_PLUGIN_PATH='+str(ROOT/'work/rootfs/usr/lib/aarch64-linux-gnu/qt6/plugins'),
           '-E', 'XDG_RUNTIME_DIR='+str(runtime_dir), str(binary), '--version']
result = subprocess.run(command, env=dict(os.environ, LD_LIBRARY_PATH=str(ROOT/'work/host-compat')),
                        capture_output=True, text=True, timeout=30)
out = {'native_sha256': evidence['native_sha256'], 'exit_code': result.returncode,
       'stdout': result.stdout, 'stderr': result.stderr, 'hardware_tested': False,
       'scope': 'QEMU --version and runtime dynamic linking only; no GUI/audio/socket test',
       'passed': result.returncode == 0 and 'Bite DJ' in result.stdout}
(ROOT/'work/native-version.json').write_text(json.dumps(out, indent=2)+'\n')
print(json.dumps(out, indent=2))
raise SystemExit(0 if out['passed'] else 1)
