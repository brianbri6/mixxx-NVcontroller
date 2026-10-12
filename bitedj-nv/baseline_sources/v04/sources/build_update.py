#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Generate a controls-only initramfs update from the exact Pi4 v0.3 image."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import zstandard


def parse_cpio(data):
    records = []
    offset = 0
    while offset + 110 <= len(data):
        magic = data[offset:offset+6]
        if magic not in (b'070701', b'070702'):
            raise ValueError('Unsupported cpio header')
        fields = [int(data[offset+6+i*8:offset+14+i*8], 16) for i in range(13)]
        size, namesize = fields[6], fields[11]
        name = data[offset+110:offset+110+namesize]
        begin = (offset+110+namesize+3) & ~3
        records.append([magic, fields, name, name[:-1].decode(), data[begin:begin+size]])
        offset = (begin+size+3) & ~3
        if name == b'TRAILER!!!\0':
            break
    return records


def encode_cpio(records):
    data = bytearray()
    for magic, fields, name, _, payload in records:
        fields = fields.copy()
        fields[6] = len(payload)
        if magic == b'070702':
            fields[12] = sum(payload) & 0xffffffff
        data += magic + b''.join(('%08x' % value).encode() for value in fields) + name
        data += b'\0' * (-len(data) % 4)
        data += payload
        data += b'\0' * (-len(data) % 4)
    data += b'\0' * (-len(data) % 512)
    return bytes(data)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build(original_initramfs, original_mappings, work, output):
    original_initramfs, original_mappings, work, output = map(Path, (original_initramfs, original_mappings, work, output))
    output.mkdir(parents=True, exist_ok=True)
    original = original_initramfs.read_bytes()
    records = parse_cpio(zstandard.ZstdDecompressor().decompress(original))
    before = {r[3]: r for r in records}
    payload = []
    for name in ('BiteDJ-Numark-NV.js', 'Numark-NV-BiteDJ-Test.midi.xml'):
        old = (original_mappings / name).read_bytes()
        new = (work / 'payload' / name).read_bytes()
        payload.append(dict(path='usr/share/mixxx/controllers/' + name, old_sha256=sha(old),
                            new_sha256=sha(new), base64=base64.b64encode(new).decode()))
    source = (work / 'update_installer.py').read_text()
    assert source.count('PAYLOAD = None') == 1
    source = source.replace('PAYLOAD = None', 'PAYLOAD = ' + repr(payload))
    compile(source, 'nv_update_generated.py', 'exec')
    (output / 'nv_update_generated.py').write_text(source)
    init = next(r for r in records if r[3] == 'init')
    old_init = init[4]
    insertion = b'exec /bin/busybox switch_root /newroot /sbin/init'
    assert old_init.count(insertion) == 1
    block = b'''# Fixed NV controls update: reviewed payload only; never executes files from BOOT.
if /bin/busybox chroot /newroot /usr/bin/python3 - < /bitedj-nv-v04.py; then
    echo "BiteDJ: NV controls update checked"
else
    echo "BiteDJ: NV update skipped; see BOOT/BiteDJ_NV_v04_update.txt" >&2
fi

'''
    init[4] = old_init.replace(insertion, block + insertion)
    script_path = output / 'initramfs-init.sh'
    script_path.write_bytes(init[4])
    subprocess.run(['sh', '-n', str(script_path)], check=True)
    index = max(r[1][0] for r in records) + 1
    name = b'bitedj-nv-v04.py\0'
    fields = [index, 0o100644, 0, 0, 1, 0, len(source.encode()), 0, 0, 0, 0, len(name), 0]
    records.insert(len(records)-1, [b'070701', fields, name, name[:-1].decode(), source.encode()])
    packed = zstandard.ZstdCompressor(level=10).compress(encode_cpio(records))
    restored = {r[3]: r for r in parse_cpio(zstandard.ZstdDecompressor().decompress(packed))}
    for name, record in before.items():
        if name == 'init':
            assert restored[name][4].replace(block, b'') == old_init
        else:
            assert restored[name] == record, name
    assert len(restored) == len(before) + 1
    assert restored['bitedj-nv-v04.py'][4] == source.encode()
    (output / 'initramfs.img').write_bytes(packed)
    validation = dict(base_initramfs_sha256=sha(original), update_initramfs_sha256=sha(packed),
                      original_members_preserved=len(before)-1, added_members=1,
                      shell_syntax='passed', cpio_roundtrip='passed',
                      payload=[{k:v for k,v in p.items() if k != 'base64'} for p in payload],
                      preserves_settings=True, hardware_tested=False)
    (output / 'build_validation.json').write_text(json.dumps(validation, indent=2) + '\n')
    return validation


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-initramfs', required=True)
    parser.add_argument('--original-mappings', required=True)
    parser.add_argument('--work', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.original_initramfs, args.original_mappings, args.work, args.output), indent=2))
