#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fixed, hash-gated NV v0.5.6 update; invoked before BiteDJ starts."""
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil

from runtime.nv_settings import nv_restore_settings

PAYLOAD = None
COMPATIBILITY = None
BACKUP = 'usr/local/share/bitedj-nv-v056-backup'
LEGACY_BACKUPS = ('usr/local/share/bitedj-nv-v05-backup', 'usr/local/share/bitedj-nv-v051-backup',
                  'usr/local/share/bitedj-nv-v052-backup', 'usr/local/share/bitedj-nv-v053-backup',
                  'usr/local/share/bitedj-nv-v054-backup', 'usr/local/share/bitedj-nv-v055-backup')
ROLLBACK = 'BiteDJ_NV_v056_rollback'
REPORT = 'BiteDJ_NV_v056_update.txt'
RELEASE = 'BiteDJ Pi4 4GB HDMI NV Test v0.3'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def current_hash(path):
    if path.is_symlink():
        raise ValueError('Refusing symlink target: ' + str(path))
    return digest(path.read_bytes()) if path.exists() else None


def atomic_write(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.nv-v056-new')
    with temporary.open('wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)
    sync_directory(path.parent)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def validate_state(state, payload):
    expected = {item['path']: item for item in payload}
    if not isinstance(state, dict) or state.get('format') != 1 or not isinstance(state.get('files'), list):
        raise ValueError('Invalid backup state')
    if len(state['files']) != len(expected) or {x.get('path') for x in state['files']} != set(expected):
        raise ValueError('Backup file list mismatch')
    for item in state['files']:
        match = expected[item['path']]
        if item.get('new') != match['new_sha256'] or item.get('old') not in match['old_sha256']:
            raise ValueError('Backup belongs to another payload')
        if item['old'] is not None and (type(item.get('old_mode')) is not int or not 0 <= item['old_mode'] <= 0o777):
            raise ValueError('Invalid backup mode')


def restore(root, backup, state):
    # Validate the entire rollback before restoring the first file.
    for item in state['files']:
        target = root/item['path']
        current = current_hash(target)
        if current not in (item['old'], item['new'], None):
            raise ValueError('Rollback target was edited: ' + item['path'])
        if item['old'] is not None and current_hash(backup/'files'/item['path']) != item['old']:
            raise ValueError('Invalid rollback backup: ' + item['path'])
    nv_restore_settings(root, writer=atomic_write)
    for item in state['files']:
        target = root/item['path']
        if item['old'] is None:
            if target.exists():
                target.unlink()
                sync_directory(target.parent)
        elif current_hash(target) != item['old']:
            atomic_write(target, (backup/'files'/item['path']).read_bytes(), item['old_mode'])
    state.update(installed=False, installing=False, rolled_back=True)
    atomic_write(backup/'state.json', json.dumps(state, indent=2).encode())


def update(root=Path('/')):
    root = Path(root)
    boot = root/'boot/firmware'
    backup = root/BACKUP
    state_path = backup/'state.json'
    state = None
    def report(text):
        print(text, flush=True)
        try:
            atomic_write(boot/REPORT, (text+'\n').encode())
        except OSError:
            pass
    try:
        if root == Path('/') and not os.path.ismount(boot):
            raise ValueError('BOOT is not mounted')
        if (root/'etc/deckshark-release').read_text().splitlines()[0] != RELEASE:
            raise ValueError('Requires Pi4 v0.3 base (v0.4 controls or v0.5 displays may be installed)')
        if not isinstance(PAYLOAD, list) or not PAYLOAD:
            raise ValueError('Payload is not generated')
        if not isinstance(COMPATIBILITY, dict):
            raise ValueError('Compatibility manifest is not generated')
        for name, expected in COMPATIBILITY.items():
            if current_hash(root/name) != expected:
                raise ValueError('Base application/runtime differs: ' + name)
        if state_path.exists():
            current_hash(state_path)  # reject a symlink instead of following it
            state = json.loads(state_path.read_text())
            validate_state(state, PAYLOAD)
        if (boot/ROLLBACK).exists():
            if state is not None:
                restore(root, backup, state)
            report('ROLLED BACK / DISABLED: pre-v0.5.6 launcher and mapping restored; settings preserved.\n'
                   'Returns to the previously installed version; owned NV preferences restored, later user edits kept.')
            return 'rolled_back'
        for legacy_backup in LEGACY_BACKUPS:
            legacy_state = root/legacy_backup/'state.json'
            if state is None and legacy_state.exists():
                current_hash(legacy_state)
                if json.loads(legacy_state.read_text()).get('installing'):
                    raise ValueError('Interrupted older NV install: boot its saved updater to recover before upgrading')
        if state is not None and state.get('installing'):
            restore(root, backup, state)
        previous = {x['path']: x for x in state['files']} if state else {}
        files, seen, required_space = [], set(), 0
        for item in PAYLOAD:
            name = item['path']
            parsed = PurePosixPath(name)
            if parsed.is_absolute() or '..' in parsed.parts or name in seen:
                raise ValueError('Invalid payload path')
            seen.add(name)
            data = base64.b64decode(item['base64'], validate=True)
            if digest(data) != item['new_sha256']:
                raise ValueError('Payload hash mismatch: ' + name)
            target = root/name
            current = current_hash(target)
            old = previous.get(name)
            if old:
                if old['new'] != item['new_sha256'] or old['old'] not in item['old_sha256']:
                    raise ValueError('Backup belongs to another update: ' + name)
                if old['old'] is not None and current_hash(backup/'files'/name) != old['old']:
                    raise ValueError('Backup hash mismatch: ' + name)
                if current not in (old['old'], old['new']):
                    raise ValueError('Installed file was edited: ' + name)
                entry = dict(old)
            else:
                if current not in item['old_sha256']:
                    raise ValueError('Unrecognized existing file: ' + name)
                entry = {'path': name, 'old': current, 'new': item['new_sha256'],
                         'old_mode': target.stat().st_mode & 0o777 if current is not None else None}
                existing_backup = backup/'files'/name
                if existing_backup.exists() and current_hash(existing_backup) != current:
                    raise ValueError('Incomplete backup differs from original: ' + name)
                if current is not None:
                    required_space += target.stat().st_size
            files.append(entry)
            required_space += len(data)
        if state and state.get('installed') and all(current_hash(root/x['path']) == x['new'] for x in files):
            report('ALREADY INSTALLED: NV v0.5.6 experimental display bridge; NV startup tuning enabled.')
            return 'already_installed'
        if shutil.disk_usage(root).free < required_space + 8*1024*1024:
            raise OSError('Insufficient root partition space for update and backups')
        # All compatibility checks have passed. Complete backups before any overwrite.
        for item in files:
            dest = backup/'files'/item['path']
            if item['old'] is not None and not dest.exists():
                atomic_write(dest, (root/item['path']).read_bytes(), item['old_mode'])
        state = {'format': 1, 'installed': False, 'installing': True, 'files': files}
        atomic_write(state_path, json.dumps(state, indent=2).encode())
        for item in PAYLOAD:
            atomic_write(root/item['path'], base64.b64decode(item['base64'], validate=True), item['mode'])
        state.update(installed=True, installing=False)
        atomic_write(state_path, json.dumps(state, indent=2).encode())
        report('INSTALLED: NV v0.5.6 experimental display bridge. Default mode: full (an existing BOOT mode file takes precedence).\n'
               'Sound routing/HDMI preserved. Startup reserves display MIDI ports and applies BOOT NV tuning.\n'
               'BOOT/BiteDJ_NV_display_mode.txt accepts info, overview, full, off.\n'
               'BOOT/BiteDJ_SD_music.txt accepts auto (default) or off; SD mount status is in F12 diagnostics.\n'
               'Artwork and physical NV behavior remain unverified.')
        return 'installed'
    except Exception as error:
        recovery = ''
        try:
            if state and state.get('installing'):
                restore(root, backup, state)
                recovery = '\nRestored originals after incomplete installation.'
        except Exception as restore_error:
            recovery = '\nRecovery pending: ' + str(restore_error)
        report('NOT INSTALLED: ' + str(error) + recovery)
        return 'error'


if __name__ == '__main__':
    raise SystemExit(0 if update() != 'error' else 1)
