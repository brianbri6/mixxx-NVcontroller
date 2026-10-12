#!/usr/bin/env python3
"""Download and unpack a Debian trixie cross toolchain; no host package install."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work'
TARGET = '''libavformat-dev libchromaprint-dev libebur128-dev libfftw3-dev
libflac-dev libgtest-dev libgl1-mesa-dev libhidapi-dev libid3tag0-dev libmad0-dev
libmodplug-dev libmp3lame-dev libmsgsl-dev libopus-dev libopusfile-dev libportmidi-dev
libprotobuf-dev libqt6core5compat6-dev libqt6opengl6-dev libqt6svg6-dev
librubberband-dev libsndfile1-dev libsoundtouch-dev libsqlite3-dev libssl-dev
libtag1-dev libudev-dev libusb-1.0-0-dev libwavpack-dev portaudio19-dev
qt6-declarative-private-dev qt6-base-private-dev qt6-shadertools-dev'''.split()
HOST = '''cmake ninja-build g++-aarch64-linux-gnu qt6-base-dev qt6-base-dev-tools
qt6-declarative-dev qt6-declarative-dev-tools qt6-shadertools-dev qt6-shader-baker
protobuf-compiler pkg-config qemu-user'''.split()


def run(command, **kwargs):
    subprocess.run([str(c) for c in command], check=True, **kwargs)


def verify_extraction(deb, dest):
    """Check extracted bytes and make completed writes visible to workspace snapshots.

    dpkg restores historical mtimes. In an interrupted workspace this left old
    or partial files visible in subsequent calls despite successful extraction.
    Touch only package-owned regular files after checking the package manifest.
    """
    control = subprocess.check_output(['dpkg-deb', '--ctrl-tarfile', str(deb)])
    with tarfile.open(fileobj=io.BytesIO(control)) as archive:
        sums = next((m for m in archive.getmembers() if m.name == './md5sums'), None)
        if sums is None:
            return
        for line in archive.extractfile(sums).read().decode().splitlines():
            expected, name = line.split(None, 1)
            path = dest/name
            if hashlib.md5(path.read_bytes()).hexdigest() != expected:
                raise ValueError('Incomplete dependency extraction: '+str(path))
            path.touch()


def main():
    WORK.mkdir(exist_ok=True)
    rootfs = WORK / 'rootfs'
    if not (rootfs / 'var/lib/dpkg/status').is_file():
        raise SystemExit('Extract the baseline rootfs first (see CODEX_PROGRESS.md).')
    key = WORK / 'debian-trixie-archive.asc'
    if not key.exists():
        with urllib.request.urlopen('https://ftp-master.debian.org/keys/archive-key-13.asc') as response:
            key.write_bytes(response.read())
    for arch, status, packages, dest in [
            ('arm64', rootfs / 'var/lib/dpkg/status', TARGET, WORK / 'sysroot'),
            ('amd64', WORK / 'empty-status', HOST, WORK / 'hostroot')]:
        status.touch(exist_ok=True) if not status.exists() else None
        aptdir = WORK / ('apt-' + arch)
        for folder in ('lists/partial', 'cache/archives/partial', 'sourceparts'):
            (aptdir / folder).mkdir(parents=True, exist_ok=True)
        (aptdir / 'sources.list').write_text(
            'deb [signed-by=' + str(key) + '] https://deb.debian.org/debian trixie main\n')
        config = aptdir / 'apt.conf'
        config.write_text(f'''APT::Architecture "{arch}";
APT::Architectures {{"{arch}";}};
APT::Sandbox::User "root";
Dir::Etc::sourcelist "{aptdir / 'sources.list'}";
Dir::Etc::sourceparts "{aptdir / 'sourceparts'}";
Dir::State::lists "{aptdir / 'lists'}";
Dir::State::status "{status}";
Dir::Cache "{aptdir / 'cache'}";
Dir::Cache::archives "{aptdir / 'cache/archives'}";
Acquire::Languages "none";
''')
        run(['/usr/bin/apt-get', '-c', config, 'update'])
        run(['/usr/bin/apt-get', '-c', config, '-y', '--download-only', '--no-install-recommends',
             'install', *packages])
        if arch == 'arm64' and not dest.exists():
            shutil.copytree(rootfs, dest, symlinks=True)
        dest.mkdir(exist_ok=True)
        manifest = []
        for deb in sorted((aptdir / 'cache/archives').glob('*.deb')):
            run(['dpkg-deb', '-x', deb, dest])
            verify_extraction(deb, dest)
            manifest.append({'file': deb.name, 'sha256': hashlib.sha256(deb.read_bytes()).hexdigest()})
        (WORK / ('packages-' + arch + '.json')).write_text(json.dumps(manifest, indent=2) + '\n')
        print('Extracted', len(manifest), arch, 'packages', flush=True)
    compat = WORK / 'host-compat'
    compat.mkdir(exist_ok=True)
    exclude = ('libc.so', 'libm.so', 'libpthread', 'librt.so', 'libdl.so', 'libresolv',
               'libnss', 'ld-linux', 'libutil', 'libanl', 'libBrokenLocale')
    for lib in (WORK / 'hostroot/usr/lib/x86_64-linux-gnu').glob('*.so*'):
        if lib.name.startswith(exclude):
            continue
        link = compat / lib.name
        if not link.is_symlink() and not link.exists():
            link.symlink_to(lib)
    host = WORK / 'hostroot'
    sysroot = WORK / 'sysroot'
    toolchain = WORK / 'cross.cmake'
    toolchain.write_text(f'''set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
set(CMAKE_SYSROOT "{sysroot}")
set(CMAKE_C_COMPILER "{host}/usr/bin/aarch64-linux-gnu-gcc")
set(CMAKE_CXX_COMPILER "{host}/usr/bin/aarch64-linux-gnu-g++")
set(CMAKE_FIND_ROOT_PATH "{sysroot}")
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
set(QT_HOST_PATH "{host}/usr" CACHE PATH "")
set(QT_HOST_PATH_CMAKE_DIR "{host}/usr/lib/x86_64-linux-gnu/cmake" CACHE PATH "")
set(Protobuf_PROTOC_EXECUTABLE "{host}/usr/bin/protoc" CACHE FILEPATH "")
set(CMAKE_C_FLAGS_INIT "-B{sysroot}/usr/lib/aarch64-linux-gnu/ -L{sysroot}/usr/lib/aarch64-linux-gnu/")
set(CMAKE_CXX_FLAGS_INIT "-B{sysroot}/usr/lib/aarch64-linux-gnu/ -L{sysroot}/usr/lib/aarch64-linux-gnu/")
''')
    (WORK / 'build-env.sh').write_text(f'''#!/bin/sh
export PATH='{host}/usr/bin':"$PATH"
export LD_LIBRARY_PATH='{compat}'
export PKG_CONFIG_SYSROOT_DIR='{sysroot}'
export PKG_CONFIG_LIBDIR='{sysroot}/usr/lib/aarch64-linux-gnu/pkgconfig:{sysroot}/usr/lib/pkgconfig:{sysroot}/usr/share/pkgconfig'
exec "$@"
''')
    print('Toolchain ready:', toolchain)


if __name__ == '__main__':
    main()
