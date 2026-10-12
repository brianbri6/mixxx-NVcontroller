#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python3 scripts/apply_native.py
# Reuse the source archive bundled with the verified earlier release. This
# supports offline builds and keeps the exact dependency pinned by BiteDJ.
python3 - <<'PY'
import hashlib
from pathlib import Path
from scripts.saved_release import load_v05
archive, _, _, _ = load_v05()
data = archive.read('source/libkeyfinder-2.2.8.zip')
assert hashlib.sha256(data).hexdigest() == '4f10e9e5673d948776e47e78273fa4d61408155cb0e210af1538c83222f285d4'
target = Path('work/build-arm/downloads/libkeyfinder-2.2.8.zip')
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(data)
PY
sh work/build-env.sh cmake -S vendor/bitedj -B work/build-arm -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE="$PWD/work/cross.cmake" -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_TESTING=OFF -DBUILD_BENCH=OFF -DENGINEPRIME=OFF -DKEYFINDER=ON \
    -DBROADCAST=OFF -DQTKEYCHAIN=OFF -DBATTERY=OFF -DLILV=OFF \
    -DVINYLCONTROL=OFF -DDOWNLOAD_MANUAL=OFF
sh work/build-env.sh cmake --build work/build-arm --parallel "${NV_BUILD_JOBS:-6}"
python3 scripts/native_build_evidence.py
