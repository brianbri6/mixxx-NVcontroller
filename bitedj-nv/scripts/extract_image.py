#!/usr/bin/env python3
"""Extract Pi4 baseline partitions without mounting or changing the source image."""
import argparse
import hashlib
import lzma
from pathlib import Path
import struct
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('archive', type=Path)
parser.add_argument('--output', type=Path, default=Path('work/base'))
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(args.archive) as z:
    images = [n for n in z.namelist() if n.endswith('.img.xz')]
    if len(images) != 1:
        raise SystemExit('Expected one compressed disk image.')
    with z.open(images[0]) as compressed, lzma.LZMAFile(compressed) as stream:
        header = stream.read(512)
        if header[510:512] != b'\x55\xaa':
            raise SystemExit('Invalid MBR signature.')
        (args.output / 'mbr.bin').write_bytes(header)
        at = 512
        for i, name in enumerate(('boot.img', 'root.img')):
            start, count = struct.unpack_from('<II', header, 446 + 16*i + 8)
            start *= 512
            size = count * 512
            if start < at or not size:
                raise SystemExit('Unexpected partition table.')
            while at < start:
                block = stream.read(min(start-at, 1024*1024))
                if not block:
                    raise SystemExit('Truncated partition gap.')
                at += len(block)
            destination = args.output / name
            # Never silently overwrite a recovered partition.
            mode = 'rb' if destination.exists() else 'wb'
            with destination.open(mode) as target:
                left = size
                digest = hashlib.sha256()
                while left:
                    block = stream.read(min(left, 1024*1024))
                    if not block:
                        raise SystemExit('Truncated partition.')
                    if mode == 'rb':
                        if target.read(len(block)) != block:
                            raise SystemExit('Existing partition differs: ' + str(destination))
                    else:
                        target.write(block)
                    digest.update(block)
                    left -= len(block)
                    at += len(block)
                if mode == 'rb' and target.read(1):
                    raise SystemExit('Existing partition has trailing bytes.')
            print(name, digest.hexdigest(), flush=True)
