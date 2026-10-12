#!/usr/bin/env python3
"""Extract regular partition files from the preserved v0.2 disk-image ZIP."""
import argparse
import lzma
from pathlib import Path,PurePosixPath
import struct
import zipfile


def extract(archive,output):
    output=Path(output).resolve()
    if output.exists() and any(output.iterdir()):raise ValueError('Base output must be empty or absent')
    output.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        images=[n for n in z.namelist() if n.endswith('.img.xz')]
        if len(images)!=1:raise ValueError('Expected one v0.2 .img.xz file')
        for name in z.namelist():
            if name==images[0]:continue
            parsed=PurePosixPath(name)
            if parsed.is_absolute() or '..' in parsed.parts:raise ValueError('Unsafe archive path')
            z.extract(name,output/'package')
        with z.open(images[0]) as member,lzma.LZMAFile(member) as source:
            header=source.read(512)
            if header[510:512]!=b'\x55\xaa':raise ValueError('Invalid disk header')
            (output/'mbr.bin').write_bytes(header);at=512
            for number in range(2):
                start,count=struct.unpack_from('<II',header,446+number*16+8);start*=512;size=count*512
                if start<at or not size:raise ValueError('Invalid partition bounds')
                skip=start-at
                while skip:
                    data=source.read(min(skip,4*1024*1024))
                    if not data:raise ValueError('Truncated image')
                    at+=len(data);skip-=len(data)
                destination=output/('boot.img' if number==0 else 'root.img')
                with destination.open('wb') as target:
                    left=size
                    while left:
                        data=source.read(min(left,4*1024*1024))
                        if not data:raise ValueError('Truncated partition')
                        if any(data):target.write(data)
                        else:target.seek(len(data),1)
                        left-=len(data);at+=len(data)
                    target.truncate(size)
                print('Extracted '+str(destination),flush=True)
            if source.read(1):raise ValueError('Unexpected data beyond the root partition')
    if not (output/'package/build_hdmi_image.py').exists():raise ValueError('Expected v0.2 base tools were not found')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',required=True)
    parser.add_argument('--output',default=str(Path(__file__).resolve().parent/'base'))
    args=parser.parse_args();extract(args.input,args.output)
