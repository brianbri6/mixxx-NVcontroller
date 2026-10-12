#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fixed NV controls-only update, run before Mixxx starts. No settings edits."""
import base64
import hashlib
import json
import os
from pathlib import Path

# Replaced by the package builder with the reviewed mapping files and hashes.
PAYLOAD = None
BACKUP = 'usr/local/share/bitedj-nv-v04-backup'
ROLLBACK = 'BiteDJ_NV_v04_rollback'
REPORT = 'BiteDJ_NV_v04_update.txt'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.nv-v04-new')
    with temporary.open('wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def update(root=Path('/')):
    root = Path(root)
    boot = root / 'boot/firmware'
    backup = root / BACKUP
    state_path = backup / 'state.json'
    log = []

    def report(message):
        print(message, flush=True)
        log.append(message)
        try:
            atomic_write(boot / REPORT, ('\n'.join(log) + '\n').encode())
        except OSError:
            # Boot console remains available if the removable BOOT cannot be written.
            pass

    try:
        if not isinstance(PAYLOAD, list) or len(PAYLOAD) != 2:
            raise ValueError('Update payload was not generated')
        if root == Path('/') and not os.path.ismount(boot):
            raise ValueError('BOOT is not mounted; mapping left unchanged')
        release = (root / 'etc/deckshark-release').read_text()
        if release.splitlines()[0] != 'BiteDJ Pi4 4GB HDMI NV Test v0.3':
            raise ValueError('This update requires the Pi4 v0.3 image')
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        # Validate ALL files before touching either mapping or its backup.
        originals = {}
        for item in PAYLOAD:
            path = root / item['path']
            old_file = backup / Path(item['path']).name
            data = path.read_bytes()
            if path.is_symlink() or digest(data) not in (item['old_sha256'], item['new_sha256']):
                raise ValueError('Mapping was edited or is a different version: ' + path.name)
            decoded = base64.b64decode(item['base64'], validate=True)
            if digest(decoded) != item['new_sha256']:
                raise ValueError('Update payload hash mismatch')
            if old_file.exists():
                old_data = old_file.read_bytes()
                if digest(old_data) != item['old_sha256']:
                    raise ValueError('Backup hash mismatch: ' + old_file.name)
            elif digest(data) == item['old_sha256']:
                old_data = data
            else:
                raise ValueError('Updated mapping exists without a usable original backup')
            originals[item['path']] = old_data

        if (boot / ROLLBACK).exists():
            for item in PAYLOAD:
                target = root / item['path']
                if digest(target.read_bytes()) != item['old_sha256']:
                    atomic_write(target, originals[item['path']])
            atomic_write(state_path, json.dumps({'installed': False, 'rolled_back': True}).encode())
            report('ROLLED BACK: original v0.3 NV mapping restored. Settings preserved.')
            return 'rolled_back'

        if state.get('installed') and all(digest((root / x['path']).read_bytes()) == x['new_sha256'] for x in PAYLOAD):
            report('INSTALLED: NV controls v0.4 already active. Settings preserved.')
            return 'already_installed'

        for item in PAYLOAD:
            old_file = backup / Path(item['path']).name
            if not old_file.exists():
                atomic_write(old_file, originals[item['path']])
        atomic_write(state_path, json.dumps({'installed': False, 'installing': True}).encode())
        for item in PAYLOAD:
            atomic_write(root / item['path'], base64.b64decode(item['base64'], validate=True))
        atomic_write(state_path, json.dumps({'installed': True, 'files': [x['new_sha256'] for x in PAYLOAD]}).encode())
        report('INSTALLED: NV controls v0.4. Platter decoder and LED test mapping updated.')
        report('Audio routing, buffer, 720p mode and saved waveform settings preserved.')
        report('NV LCD waveform output is not installed by this update.')
        return 'installed'
    except Exception as error:
        report('NOT INSTALLED: ' + str(error))
        # A partial write is recoverable: restore verified originals if the install started.
        try:
            state = json.loads(state_path.read_text()) if state_path.exists() else {}
            if state.get('installing'):
                for item in PAYLOAD:
                    old_file = backup / Path(item['path']).name
                    if old_file.exists() and digest(old_file.read_bytes()) == item['old_sha256']:
                        target = root / item['path']
                        if digest(target.read_bytes()) in (item['old_sha256'], item['new_sha256']):
                            atomic_write(target, old_file.read_bytes())
                atomic_write(state_path, json.dumps({'installed': False, 'recovered': True}).encode())
                report('Recovered the original mapping after the interrupted update.')
        except Exception as recovery_error:
            report('Recovery pending for next boot: ' + str(recovery_error))
        return 'error'


if __name__ == '__main__':
    raise SystemExit(0 if update() != 'error' else 1)
