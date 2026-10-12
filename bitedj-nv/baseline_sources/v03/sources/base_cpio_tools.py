#!/usr/bin/env python3
"""Build an offline, bootable HDMI test image from the supplied sharkware update.

Requires Linux, Python 3, zstandard, dosfstools, mtools, and e2fsprogs.
Writes regular image files only; never opens or flashes a physical disk.
"""
import argparse
from collections import deque
import difflib
import gzip
import hashlib
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import uuid
import zipfile

import zstandard

NAME = "BiteDJ_Pi3BPlus_HDMI_Test_v0_2"
MIB = 1024 * 1024
BOOT_START = 2048
BOOT_SECTORS = 128 * MIB // 512
ROOT_START = BOOT_START + BOOT_SECTORS
ROOT_SECTORS = 1536 * MIB // 512
TOTAL_SECTORS = ROOT_START + ROOT_SECTORS
SOURCE_URL = "https://github.com/TeamDeckshark/bitedj"

CONFIG = """# BiteDJ HDMI test build v0.2 - Raspberry Pi 3 Model B+
# Connect and power the HDMI monitor before powering the Pi.
# KMS/Sway uses the HDMI display's detected preferred mode (EDID).
arm_64bit=1
kernel=kernel8.img
initramfs initramfs.img followkernel
enable_uart=0
disable_overscan=1
disable_fw_kms_setup=1
gpu_mem=64
camera_auto_detect=0
display_auto_detect=0
dtparam=audio=on
dtoverlay=vc4-kms-v3d,cma=128
# Preserve the original firmware's offline radio configuration.
dtoverlay=disable-wifi
dtoverlay=disable-bt
# No DSI touchscreen overlay, PWM LEDs, I2C battery HAT, or GPIO buttons.
"""

SWAY = """# HDMI monitor session; visible mouse pointer, normal display mode.
output * bg /etc/deckshark/wallpaper.png fill
include /tmp/sway-rotation.conf
default_border none
default_floating_border none
hide_edge_borders both
seat * hide_cursor 0
exec /usr/local/bin/undervolt-indicator
exec /usr/local/bin/thermal-indicator
exec /bin/start-mixxx mixxx
"""

README = (Path(__file__).resolve().parent / 'README.txt').read_text()

MIT = """MIT License

Copyright (c) 2026 HDMI conversion contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
IN THE SOFTWARE.

This license covers the conversion and validation tools only, not the\nfirmware, NV mapping, or cursor artwork.
"""


def run(args, capture=False):
    p = subprocess.run([str(x) for x in args], text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, check=False)
    if p.returncode:
        raise RuntimeError(f"Command failed ({p.returncode}): {args[0]}\n{p.stdout}")
    if capture:
        return p.stdout
    if p.stdout.strip():
        print(p.stdout.strip(), flush=True)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(4 * MIB), b''):
            h.update(chunk)
    return h.hexdigest()


def safe_name(name):
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts:
        raise ValueError(f"Unsafe archive path: {name!r}")
    return Path(*p.parts)


def extract_tree(archive, destination):
    """Extract regular data first, then links, without following archive links."""
    destination.mkdir(parents=True)
    metadata = []
    devices = []
    with tarfile.open(archive) as t:
        members = t.getmembers()
        for m in members:
            safe_name(m.name)
        for m in members:
            if m.isdir():
                (destination / safe_name(m.name)).mkdir(parents=True, exist_ok=True)
        for m in members:
            if not m.isfile():
                continue
            target = destination / safe_name(m.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with t.extractfile(m) as source, target.open('wb') as out:
                shutil.copyfileobj(source, out, 4 * MIB)
            os.chmod(target, m.mode)
            os.utime(target, (m.mtime, m.mtime))
        for m in members:
            target = destination / safe_name(m.name)
            if m.islnk():
                os.link(destination / safe_name(m.linkname), target)
            elif m.issym():
                os.symlink(m.linkname, target)
            elif m.isdev():
                devices.append(m)
            elif not (m.isfile() or m.isdir()):
                raise ValueError(f"Unsupported archive member: {m.name}")
            if not m.isdev():
                if m.uid or m.gid:
                    metadata.append((str(safe_name(m.name)), m.uid, m.gid))
                if m.isdir():
                    os.chmod(target, m.mode)
                    os.utime(target, (m.mtime, m.mtime))
    return metadata, devices


def parse_cpio(data):
    records = []
    at = 0
    while at + 110 <= len(data):
        magic = data[at:at + 6]
        if magic not in [b'070701', b'070702']:
            if not any(data[at:]):
                break
            raise ValueError(f"Unexpected initramfs encoding at {at}")
        fields = [int(data[at + 6 + i * 8:at + 14 + i * 8], 16) for i in range(13)]
        size, namesize = fields[6], fields[11]
        rawname = data[at + 110:at + 110 + namesize]
        begin = (at + 110 + namesize + 3) & ~3
        name = rawname[:-1].decode()
        records.append([magic, fields, rawname, name, data[begin:begin + size]])
        at = (begin + size + 3) & ~3
        if name == 'TRAILER!!!':
            break
    return records


def encode_cpio(records):
    result = bytearray()
    for magic, fields, rawname, name, payload in records:
        fields = fields.copy()
        fields[6] = len(payload)
        if magic == b'070702':
            fields[12] = sum(payload) & 0xFFFFFFFF
        result.extend(magic + b''.join(f'{x:08x}'.encode() for x in fields))
        result.extend(rawname)
        result.extend(b'\0' * ((-len(result)) % 4))
        result.extend(payload)
        result.extend(b'\0' * ((-len(result)) % 4))
    result.extend(b'\0' * ((-len(result)) % 512))
    return bytes(result)


def modify_config(text):
    section = ''
    output = []
    for line in text.splitlines():
        if line.startswith('['):
            section = line
        key = line.split(' ', 1)[0]
        if (section == '[BiteDJ]' and key.startswith('usb_drive_path_')) or \
           (section in ['[Controller]', '[ControllerPreset]'] and key == 'eject') or \
           (section == '[MainWindow]' and key in ['geometry', 'state']):
            continue
        output.append(line)
    return '\n'.join(output) + '\n'


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Expected exactly one startup block: {old[:90]!r}")
    return text.replace(old, new, 1)


def chs(lba):
    c, rem = divmod(lba, 255 * 63)
    h, s = divmod(rem, 63)
    if c > 1023:
        return b'\xfe\xff\xff'
    return bytes([h, ((c >> 2) & 0xC0) | (s + 1), c & 0xFF])


def disk_mbr():
    b = bytearray(512)
    struct.pack_into('<I', b, 440, 0x53484D49)
    for index, (start, sectors, kind, active) in enumerate([
            (BOOT_START, BOOT_SECTORS, 0x0C, 0x80),
            (ROOT_START, ROOT_SECTORS, 0x83, 0)]):
        b[446 + 16 * index:462 + 16 * index] = \
            bytes([active]) + chs(start) + bytes([kind]) + chs(start + sectors - 1) + \
            struct.pack('<II', start, sectors)
    b[510:512] = b'\x55\xaa'
    return b


def verify_shared_libraries(root, readelf):
    """Resolve core ELF dependencies within the image, including private RUNPATHs."""
    root = root.absolute()

    def virtual(path):
        todo = deque(PurePosixPath(path).parts)
        current = []
        links = 0
        while todo:
            part = todo.popleft()
            if part in ['/', '.', '']:
                continue
            if part == '..':
                if current:
                    current.pop()
                continue
            candidate = root.joinpath(*current, part)
            if candidate.is_symlink():
                links += 1
                if links > 50:
                    raise ValueError('Image symlink loop')
                target = PurePosixPath(os.readlink(candidate))
                if target.is_absolute():
                    current = []
                todo.extendleft(reversed(target.parts))
            else:
                current.append(part)
        return root.joinpath(*current)

    standard = ['/usr/lib/aarch64-linux-gnu', '/usr/lib', '/usr/local/lib',
                '/lib/aarch64-linux-gnu', '/lib']
    seeds = [root / 'usr/bin/sway', root / 'usr/share/mixxx/mixxx',
             root / 'usr/local/bin/undervolt-indicator',
             root / 'usr/local/bin/thermal-indicator']
    seeds += list((root / 'usr/lib/aarch64-linux-gnu/qt6/plugins/platforms').glob('*wayland*.so'))
    queue = deque(seeds)
    seen = set()
    missing = []
    while queue:
        path = queue.popleft()
        if path in seen:
            continue
        seen.add(path)
        info = run([readelf, '-d', path], capture=True)
        origin = '/' + str(path.parent.relative_to(root))
        private = []
        for rpath in re.findall(r'\((?:RUNPATH|RPATH)\).*?\[([^]]+)\]', info):
            private.extend(s.replace('${ORIGIN}', origin).replace('$ORIGIN', origin)
                           for s in rpath.split(':') if s)
        for soname in re.findall(r'\(NEEDED\).*?\[([^]]+)\]', info):
            found = None
            for directory in private + standard:
                candidate = virtual(directory + '/' + soname)
                if candidate.is_file():
                    found = candidate
                    break
            if found:
                queue.append(found)
            else:
                missing.append((str(path.relative_to(root)), soname))
    result = {'seed_count': len(seeds), 'resolved_elf_objects': len(seen),
              'missing_shared_libraries': missing}
    if missing:
        raise ValueError('Unresolved core image dependencies: ' + repr(missing))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--native-tools', type=Path)
    parser.add_argument('--node', default=shutil.which('node'))
    a = parser.parse_args()
    a.input = a.input.resolve()
    work = a.work_dir.resolve()
    output = a.output_dir.resolve()
    if work == output or work.exists():
        raise ValueError('Use a new, empty work directory distinct from output.')
    if not a.input.is_file():
        raise ValueError('Input must be a regular sharkware archive file.')
    work.mkdir(parents=True)
    output.mkdir(parents=True, exist_ok=True)
    package = work / 'package'
    package.mkdir()
    patches = []

    def tool(name):
        if a.native_tools:
            for d in ['sbin', 'usr/sbin', 'bin', 'usr/bin']:
                p = a.native_tools / d / name
                if p.is_file():
                    # mtools selects its command from argv[0]; keep the mcopy link.
                    return str(p.absolute())
        found = shutil.which(name)
        if not found:
            raise RuntimeError(f'Missing build dependency: {name}')
        return found

    programs = {n: tool(n) for n in ['mkfs.fat', 'fsck.fat', 'mcopy',
                                    'mke2fs', 'e2fsck', 'debugfs', 'readelf', 'sh']}
    print('Verifying the supplied firmware checksums...', flush=True)
    source_hash = sha256(a.input)
    with tarfile.open(a.input) as t:
        release = t.extractfile('RELEASE').read().decode()
        sums = t.extractfile('SHA256').read().decode()
        for line in sums.splitlines():
            digest, name = line.split(None, 1)
            name = name.strip()
            payload = t.extractfile(name).read()
            if hashlib.sha256(payload).hexdigest() != digest:
                raise ValueError(f'Original archive checksum failed: {name}')
            (work / name).write_bytes(payload)
    original_version = dict(l.split('=', 1) for l in release.splitlines() if '=' in l)['VERSION']
    if original_version != '20260926.1':
        raise ValueError('This patch was reviewed for firmware 20260926.1 only.')

    root = work / 'rootfs'
    boot = work / 'bootfs'
    print('Extracting original boot and root filesystems...', flush=True)
    extract_tree(work / 'bootfs.tar.xz', boot)
    metadata, devices = extract_tree(work / 'datafs.tar.xz', root)

    def patch(path, new, base=root):
        target = base / path
        old = target.read_text() if target.exists() else ''
        if old != new:
            prefix = 'boot/' if base == boot else 'root/'
            patches.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                               fromfile='original/' + prefix + path,
                                               tofile='hdmi/' + prefix + path))
            target.write_text(new)
            dest = package / 'modified-files' / prefix / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(new)

    print('Applying HDMI and mouse settings...', flush=True)
    patch('config.txt', CONFIG, boot)
    cmdline = (boot / 'cmdline.txt').read_text().strip().split()
    cmdline = [s for s in cmdline if s not in ['splash']]
    patch('cmdline.txt', ' '.join(cmdline) + '\n', boot)
    patch('etc/deckshark-mode', 'MODE=hdmi\n')
    patch('etc/deckshark/sway-kiosk.conf', SWAY)
    patch('etc/deckshark-release',
          'NAME="Deckshark HDMI"\nID=debian\n'
          'PRETTY_NAME="Deckshark / BiteDJ HDMI test build v0.2"\n'
          'VERSION="20260926.1-hdmi-test2"\nVERSION_ID="13"\n'
          'VERSION_CODENAME=trixie\nBUILD_DATE="2026-10-05"\nMODE=hdmi\n')
    patch('root/.mixxx/mixxx.cfg', modify_config((root / 'root/.mixxx/mixxx.cfg').read_text()))
    start = (root / 'usr/bin/start-mixxx').read_text()
    begin = start.index('# Repair [BiteDJ],usb_drive_path_N')
    end = start.index('# RT scheduling is handled inside Mixxx itself', begin)
    start = start[:begin] + '# HDMI profile uses software eject; no fixed GPIO port paths.\n\n' + start[end:]
    start = replace_once(start, 'if [ "$MODE" = "hw" ]; then',
                         'if [ "$MODE" = "hw" ] || [ "$MODE" = "hdmi" ]; then')
    start = replace_once(start, 'export XCURSOR_THEME=invisible', 'export XCURSOR_THEME=default')
    patch('usr/bin/start-mixxx', start)
    init = (root / 'usr/sbin/init').read_text()
    init, nled = re.subn(r'^[ \t]*\[ -x /usr/local/sbin/sharkware-leds \] && /usr/local/sbin/sharkware-leds -[lo] \|\|:[ \t]*$',
                         '    : # HDMI profile has no GPIO eject LEDs.', init, flags=re.M)
    if nled != 3:
        raise ValueError(f'Expected three LED operations, found {nled}')
    init = replace_once(init, 'uhubctl -l 2 -a 2 -d 0',
                        ': # HDMI profile does not power-cycle a production-specific USB hub.')
    patch('usr/sbin/init', init)

    with (boot / 'initramfs.img').open('rb') as f:
        with zstandard.ZstdDecompressor().stream_reader(f) as reader:
            records = parse_cpio(reader.read())
    entries = {x[3]: x for x in records}
    initramfs_init = entries['init'][4].decode()
    modified_initramfs = replace_once(initramfs_init,
        '[ -x /usr/bin/sharkware-update ] && /usr/bin/sharkware-update',
        ': # HDMI test image: preserve this profile; update by writing a new SD image.')
    entries['init'][4] = modified_initramfs.encode()
    patches.extend(difflib.unified_diff(initramfs_init.splitlines(True), modified_initramfs.splitlines(True),
                                       fromfile='original/initramfs/init', tofile='hdmi/initramfs/init'))
    cpio = encode_cpio(records)
    (boot / 'initramfs.img').write_bytes(zstandard.ZstdCompressor(level=10).compress(cpio))
    initramfs_copy = package / 'modified-files/initramfs/init'
    initramfs_copy.parent.mkdir(parents=True)
    initramfs_copy.write_text(modified_initramfs)
    run([programs['sh'], '-n', root / 'usr/sbin/init'])
    run([programs['sh'], '-n', root / 'usr/bin/start-mixxx'])
    run([programs['sh'], '-n', initramfs_copy])

    print('Installing and validating the visible cursor and original NV preset...', flush=True)
    helpers = Path(__file__).resolve().parent
    repair_payload = helpers / 'repair-payload'
    repaired_files = ['usr/bin/start-mixxx', 'etc/deckshark/sway-kiosk.conf']
    before_repair = {name: (root / name).read_text() for name in repaired_files}
    run([sys.executable, helpers / 'apply_repair.py', '--root', root,
         '--payload', repair_payload])
    for name in repaired_files:
        updated = (root / name).read_text()
        patches.extend(difflib.unified_diff(before_repair[name].splitlines(True),
                                           updated.splitlines(True),
                                           fromfile='hdmi/root/' + name,
                                           tofile='nv-pointer/root/' + name))
        shutil.copy2(root / name, package / 'modified-files/root' / name)
    run([programs['sh'], '-n', root / 'usr/bin/start-mixxx'])
    if not a.node:
        raise RuntimeError('Node.js is required for mapping validation.')
    run([sys.executable, helpers / 'validate_repair.py', '--root', root,
         '--node', a.node, '--output', package / 'repair-validation.json'])
    repair_validation = json.loads((package / 'repair-validation.json').read_text())
    for name in ['apply_repair.py', 'validate_repair.py', 'nv_mapping_test.js']:
        shutil.copy2(helpers / name, package / name)
    shutil.copytree(repair_payload, package / 'repair-payload', symlinks=True)

    # Native offline filesystem creation; no loop devices or mounts required.
    print('Creating FAT32 boot and ext4 data partitions...', flush=True)
    fat = work / 'boot.img'
    ext = work / 'root.img'
    with fat.open('wb') as f:
        f.truncate(BOOT_SECTORS * 512)
    run([programs['mkfs.fat'], '-F', '32', '-s', '1', '-h', BOOT_START,
         '-n', 'SHARKBOOT', fat])
    boot_files = [x for x in sorted(boot.iterdir()) if not x.name.startswith('.')]
    run([programs['mcopy'], '-s', '-i', fat, *boot_files, '::/'])
    with ext.open('wb') as f:
        f.truncate(ROOT_SECTORS * 512)
    root_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, source_hash + '/hdmi-test-v0.2'))
    run([programs['mke2fs'], '-q', '-t', 'ext4', '-L', 'SHARKDATA', '-U', root_uuid,
         '-b', '4096', '-m', '1', '-E', 'lazy_itable_init=0,lazy_journal_init=0',
         '-d', root, ext])
    commands = []
    for m in devices:
        relative = safe_name(m.name)
        if relative.parent != Path('dev'):
            raise ValueError(f'Unreviewed device: {m.name}')
        commands.extend(['cd /dev', f'mknod {relative.name} c {m.devmajor} {m.devminor}',
                         f'set_inode_field {relative.name} mode 0{stat.S_IFCHR | m.mode:o}'])
    for name, uid, gid in metadata:
        q = '"/' + name.replace('"', '\\"') + '"'
        commands.extend([f'set_inode_field {q} uid {uid}', f'set_inode_field {q} gid {gid}'])
    if commands:
        meta = work / 'inode_metadata.txt'
        meta.write_text('\n'.join(commands) + '\n')
        result = run([programs['debugfs'], '-w', '-f', meta, ext], capture=True)
        if re.search(r'not found|File not found|Bad|Usage:|invalid', result, re.I):
            raise RuntimeError('Offline inode metadata failed:\n' + result)

    print('Validating both filesystems and boot files...', flush=True)
    fat_check = run([programs['fsck.fat'], '-n', '-v', fat], capture=True)
    ext_check = run([programs['e2fsck'], '-f', '-n', ext], capture=True)
    checkdir = work / 'verify'
    checkdir.mkdir()
    for name in ['config.txt', 'cmdline.txt', 'bcm2710-rpi-3-b-plus.dtb',
                 'kernel8.img', 'initramfs.img']:
        dest = checkdir / name
        run([programs['mcopy'], '-i', fat, '::/' + name, dest])
        if sha256(dest) != sha256(boot / name):
            raise ValueError(f'Boot filesystem read-back mismatch: {name}')
    root_init_dump = checkdir / 'root-init'
    run([programs['debugfs'], '-R', f'dump /usr/sbin/init {root_init_dump}', ext], capture=True)
    if sha256(root_init_dump) != sha256(root / 'usr/sbin/init'):
        raise ValueError('ext4 startup script read-back mismatch')
    repair_readback = ['usr/bin/start-mixxx', 'etc/deckshark/sway-kiosk.conf',
                       'usr/share/icons/default/index.theme',
                       'usr/share/icons/BiteDJ-Visible/index.theme',
                       'usr/share/icons/BiteDJ-Visible/cursors/left_ptr',
                       'usr/share/mixxx/controllers/Numark-NV-BiteDJ-Test.midi.xml',
                       'usr/share/mixxx/controllers/BiteDJ-Numark-NV.js',
                       'usr/share/doc/bitedj-nv-test/NV_MAPPING_NOTES.txt']
    for index, name in enumerate(repair_readback):
        dest = checkdir / f'repair-{index}'
        run([programs['debugfs'], '-R', f'dump /{name} {dest}', ext], capture=True)
        if not dest.is_file() or sha256(dest) != sha256(root / name):
            raise ValueError(f'Cursor/NV ext4 read-back mismatch: {name}')
    for name in ['/usr/bin/busybox', '/usr/bin/start-mixxx', '/usr/bin/sway',
                 '/usr/share/mixxx/mixxx', '/usr/lib/ld-linux-aarch64.so.1']:
        info = run([programs['debugfs'], '-R', 'stat ' + name, ext], capture=True)
        if 'Inode:' not in info:
            raise ValueError(f'Missing critical root file: {name}')
    dependency_check = verify_shared_libraries(root, programs['readelf'])
    kernel = gzip.decompress((boot / 'kernel8.img').read_bytes())
    if b'PREEMPT_RT' not in kernel:
        raise ValueError('Original real-time kernel signature is missing')
    restored = parse_cpio(zstandard.ZstdDecompressor().decompress((boot / 'initramfs.img').read_bytes()))
    if {x[3]: x[4] for x in restored}['init'] != modified_initramfs.encode():
        raise ValueError('Modified initramfs startup verification failed')

    print('Assembling the MBR SD-card image...', flush=True)
    image = work / (NAME + '.img')
    with image.open('wb') as f:
        f.truncate(TOTAL_SECTORS * 512)
        f.seek(0)
        f.write(disk_mbr())
        for path, start in [(fat, BOOT_START), (ext, ROOT_START)]:
            f.seek(start * 512)
            with path.open('rb') as source:
                shutil.copyfileobj(source, f, 4 * MIB)
    with image.open('rb') as f:
        mbr = f.read(512)
        assert mbr[510:512] == b'\x55\xaa'
        for i, (expected_start, expected_len) in enumerate([(BOOT_START, BOOT_SECTORS), (ROOT_START, ROOT_SECTORS)]):
            assert struct.unpack_from('<II', mbr, 454 + 16 * i) == (expected_start, expected_len)
        for partition, start in [(fat, BOOT_START), (ext, ROOT_START)]:
            h = hashlib.sha256()
            f.seek(start * 512)
            remaining = partition.stat().st_size
            while remaining:
                chunk = f.read(min(4 * MIB, remaining))
                if not chunk:
                    raise ValueError('Unexpected end of assembled disk image')
                h.update(chunk)
                remaining -= len(chunk)
            if h.hexdigest() != sha256(partition):
                raise ValueError('Assembled partition mismatch')

    print('Compressing the verified disk image...', flush=True)
    compressed = package / (NAME + '.img.xz')
    with image.open('rb') as source, lzma.open(compressed, 'wb', preset=2) as destination:
        shutil.copyfileobj(source, destination, 4 * MIB)
    raw_hash = sha256(image)
    h = hashlib.sha256()
    uncompressed_size = 0
    with lzma.open(compressed, 'rb') as f:
        for chunk in iter(lambda: f.read(4 * MIB), b''):
            h.update(chunk)
            uncompressed_size += len(chunk)
    if h.hexdigest() != raw_hash or uncompressed_size != image.stat().st_size:
        raise ValueError('Compressed image full read-back failed')
    compressed_hash = sha256(compressed)
    validation = {
        'build': NAME,
        'source_firmware_version': original_version,
        'source_archive_sha256': source_hash,
        'raw_image_sha256': raw_hash,
        'compressed_image_sha256': compressed_hash,
        'raw_size_bytes': image.stat().st_size,
        'compressed_size_bytes': compressed.stat().st_size,
        'physical_pi_boot_tested': False,
        'nv_hardware_tested': False,
        'application_recompiled': False,
        'target': 'Raspberry Pi 3 Model B+; HDMI; USB mouse; USB audio/controller',
        'partitions': [
            {'number': 1, 'type': 'FAT32 LBA', 'start_sector': BOOT_START, 'sectors': BOOT_SECTORS},
            {'number': 2, 'type': 'ext4', 'start_sector': ROOT_START, 'sectors': ROOT_SECTORS}],
        'checks': {'source_payload_sha256': 'passed', 'fat32_fsck': 'passed',
                   'ext4_fsck': 'passed', 'startup_shell_syntax': 'passed',
                   'fat_long_filename_board_file_readback': 'passed',
                   'critical_root_files': 'passed', 'modified_initramfs_readback': 'passed',
                   'core_shared_libraries': 'passed',
                   'native_visible_cursor_assets': 'passed',
                   'nv_mapping_script_simulation': 'passed',
                   'cursor_nv_ext4_readback': 'passed',
                   'assembled_partition_hashes': 'passed', 'xz_full_disk_readback': 'passed'},
        'shared_library_check': dependency_check,
        'repair_validation': repair_validation,
        'fat32_fsck_output': fat_check,
        'ext4_fsck_output': ext_check,
        'limitations': ['Physical boot, HDMI output and audio remain untested.',
                        'The previous v0.1 image booted per the user; v0.2 is not physically tested.',
                        'Original Numark NV mapping is experimental; LCDs, advanced FX, touch-EQ and Slicer are not implemented.',
                        'Jog encoding, sensitivity and audio channels need hardware confirmation.',
                        'Default HDMI mode uses monitor EDID.',
                        'Automatic USB firmware updates are disabled for this profile.'],
        'source_project': SOURCE_URL,
    }
    (package / 'README.txt').write_text(README)
    (package / 'SHA256SUMS.txt').write_text(compressed_hash + '  ' + compressed.name + '\n')
    (package / 'validation.json').write_text(json.dumps(validation, indent=2) + '\n')
    (package / 'patches.diff').write_text(''.join(patches))
    shutil.copy2(Path(__file__), package / 'build_hdmi_image.py')
    (package / 'CONVERSION_SCRIPT_LICENSE.txt').write_text(MIT)
    archive = output / (NAME + '.zip')
    if archive.exists():
        raise ValueError('Refusing to overwrite an existing output ZIP.')
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as z:
        for path in sorted(package.rglob('*')):
            if path.is_file() and not path.relative_to(package).parts[0].startswith('.'):
                z.write(path, path.relative_to(package))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError('Final ZIP CRC verification failed')
    print(json.dumps({'output': str(archive), 'size_bytes': archive.stat().st_size,
                      'zip_sha256': sha256(archive), 'checks': validation['checks']}, indent=2), flush=True)


if __name__ == '__main__':
    main()
