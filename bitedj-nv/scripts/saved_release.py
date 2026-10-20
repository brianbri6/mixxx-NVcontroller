#!/usr/bin/env python3
"""Read hash-pinned previous releases without needing a native rebuild."""
import ast
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile
import zstandard

ROOT = Path(__file__).resolve().parents[1]
V05_PATH = ROOT/'baseline/mixxx numark nv/BiteDJ_Pi4_NV_Display_Test_v0_5.zip'
V051_PATH = ROOT/'baseline/mixxx numark nv/BiteDJ_Pi4_NV_Display_Test_v0_5_1.zip'
V052_PATH = ROOT/'baseline/mixxx numark nv/BiteDJ_Pi4_NV_Display_Test_v0_5_2.zip'
V053_PATH = ROOT/'baseline/mixxx numark nv/BiteDJ_Pi4_NV_Display_Test_v0_5_3.zip'
V054_PATH = ROOT/'baseline/mixxx numark nv/BiteDJ_Pi4_NV_Display_Test_v0_5_4.zip'
V055_PATH = ROOT/'baseline/mixxx numark nv/BiteDJ_Pi4_NV_Display_Test_v0_5_5.zip'
sys.path.insert(0, str(ROOT/'baseline_sources/v04/sources'))
from build_update import parse_cpio, encode_cpio


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_release(path, pinned_path, updater_name):
    blob = Path(path).read_bytes()
    expected = json.loads((ROOT/'INPUTS.json').read_text())[str(pinned_path.relative_to(ROOT))]
    if sha(blob) != expected:
        raise ValueError('Saved release hash mismatch')
    archive = zipfile.ZipFile(io.BytesIO(blob))
    image = archive.read('install/initramfs.img')
    validation = json.loads(archive.read('validation/package.json'))
    if sha(image) != validation['initramfs_sha256']:
        raise ValueError('Saved initramfs hash mismatch')
    records = parse_cpio(zstandard.ZstdDecompressor().decompress(image))
    source = next(r[4] for r in records if r[3] == updater_name).decode()
    values = {}
    for statement in ast.parse(source).body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
            if isinstance(target, ast.Name) and target.id in ('PAYLOAD', 'COMPATIBILITY'):
                values[target.id] = ast.literal_eval(statement.value)
    if set(values) != {'PAYLOAD', 'COMPATIBILITY'}:
        raise ValueError('Saved updater constants missing')
    for entry in values['PAYLOAD']:
        if sha(base64.b64decode(entry['base64'], validate=True)) != entry['new_sha256']:
            raise ValueError('Saved payload hash mismatch: ' + entry['path'])
    return archive, source, values['PAYLOAD'], values['COMPATIBILITY']


def load_v05(path=V05_PATH):
    return load_release(path, V05_PATH, 'bitedj-nv-v05.py')


def load_v051(path=V051_PATH):
    return load_release(path, V051_PATH, 'bitedj-nv-v051.py')


def load_v052(path=V052_PATH):
    return load_release(path, V052_PATH, 'bitedj-nv-v052.py')


def load_v053(path=V053_PATH):
    return load_release(path, V053_PATH, 'bitedj-nv-v053.py')


def load_v054(path=V054_PATH):
    return load_release(path, V054_PATH, 'bitedj-nv-v054.py')


def load_v055(path=V055_PATH):
    return load_release(path, V055_PATH, 'bitedj-nv-v055.py')

V056_PATH = ROOT/'baseline/mixxx numark nv/BiteDJ_Pi4_NV_Display_Test_v0_5_6.zip'

def load_v056(path=V056_PATH):
    return load_release(path, V056_PATH, 'bitedj-nv-v056.py')

V057_PATH = ROOT/'baseline/mixxx numark nv/BiteDJ_Pi4_NV_Display_Test_v0_5_7.zip'

def load_v057(path=V057_PATH):
    return load_release(path, V057_PATH, 'bitedj-nv-v057.py')
