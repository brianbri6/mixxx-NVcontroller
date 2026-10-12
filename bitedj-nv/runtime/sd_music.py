#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Mount a labelled music partition on the appliance's own MMC card.

Called after PID1 creates /media, before the application opens its library.
No formatting, partition editing, remounting, fsck or library/settings edits.
"""
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

OPTION = 'boot/firmware/BiteDJ_SD_music.txt'
STATUS = 'tmp/bitedj-nv/sd-music-status.json'
TARGET = '/media/MUSIC'
FILESYSTEMS = ('exfat', 'vfat', 'ext4')


def unescape(value):
    return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), value)


def mount_table(text):
    rows = []
    for line in text.splitlines():
        before, separator, after = line.partition(' - ')
        a, b = before.split(), after.split()
        if not separator or len(a) < 6 or len(b) < 3:
            raise ValueError('Invalid mountinfo record')
        rows.append(dict(device_id=a[2], root=unescape(a[3]), target=unescape(a[4]),
                         options=a[5].split(','), fstype=b[0], source=unescape(b[1])))
    return rows


class System:
    def __init__(self, root=Path('/')):
        self.root = Path(root)
        self.deadline = time.monotonic() + 12

    def path(self, name):
        return self.root/name.lstrip('/')

    def mounts(self):
        return mount_table(self.path('/proc/self/mountinfo').read_text())

    def run(self, args, timeout=2):
        budget = self.deadline-time.monotonic()
        if budget <= 0:
            raise TimeoutError('SD music startup deadline reached')
        return subprocess.run(args, capture_output=True, text=True,
                              timeout=min(timeout, budget), check=False)

    def root_card(self, mounts):
        roots = [m for m in mounts if m['target'] == '/']
        if len(roots) != 1 or roots[0]['root'] != '/':
            raise ValueError('Cannot identify the appliance root partition')
        root = roots[0]
        # Kernel device number works with /dev/root and UUID-based boot names.
        name = self.path('/sys/dev/block/'+root['device_id']).resolve(strict=True).name
        match = re.fullmatch(r'(mmcblk[0-9]+)p2', name)
        if not match or root['fstype'] != 'ext4':
            raise ValueError('Automatic SD music mount requires an MMC p2 ext4 root')
        return match[1]

    def block_matches(self, candidate):
        path = self.path('/dev/'+candidate['name'])
        if path.is_symlink():
            return False
        try:
            info = path.stat()
            return stat.S_ISBLK(info.st_mode) and candidate['device_id'] == (
                str(os.major(info.st_rdev))+':'+str(os.minor(info.st_rdev)))
        except OSError:
            return False

    def partitions(self, card):
        paths = sorted(self.path('/sys/class/block').glob(card+'p*'))
        if len(paths) > 16:
            raise ValueError('Unexpectedly many partitions on the OS SD card')
        rows = []
        for path in paths:
            match = re.fullmatch(re.escape(card)+r'p([0-9]+)', path.name)
            if not match or int(match[1]) <= 2:
                continue
            if int((path/'partition').read_text().strip()) != int(match[1]):
                raise ValueError('Inconsistent partition identity')
            candidate = dict(name=path.name, device_id=(path/'dev').read_text().strip())
            if not self.block_matches(candidate):
                raise ValueError('SD partition device identity changed')
            probe = self.run(['/usr/sbin/blkid', '-p', '-o', 'export', '/dev/'+path.name])
            if probe.returncode == 2:  # No recognized filesystem/signature.
                candidate.update(label='', fstype='', uuid='')
            elif probe.returncode:
                raise ValueError('Cannot identify SD filesystem: '+probe.stderr.strip()[:300])
            else:
                fields = dict(line.split('=', 1) for line in probe.stdout.splitlines() if '=' in line)
                candidate.update(label=fields.get('LABEL', ''), fstype=fields.get('TYPE', ''),
                                 uuid=fields.get('UUID', ''))
            rows.append(candidate)
        return rows


def existing_mount(candidate, mounts):
    # Preserve a prior path (including one outside /media) and read-only state.
    # A bind of a subdirectory alone is not the whole music filesystem.
    return next((m for m in mounts if m['device_id'] == candidate['device_id'] and m['root'] == '/'), None)


def mount_music(system):
    result = {'version': '0.5.6', 'mode': 'auto', 'status': 'skipped', 'target': TARGET,
              'hardware_verified': False, 'formatted_or_repartitioned': False}
    option = system.path(OPTION)
    try:
        if option.is_symlink():
            raise ValueError('SD music option must be a regular file')
        if option.exists():
            if not stat.S_ISREG(option.stat().st_mode):
                raise ValueError('SD music option must be a regular file')
            if option.stat().st_size > 32:
                raise ValueError('SD music option is too long')
            result['mode'] = option.read_text().strip().lower()
        if result['mode'] not in ('auto', 'off'):
            raise ValueError('BiteDJ_SD_music.txt accepts only auto or off')
        if result['mode'] == 'off':
            result.update(status='disabled', reason='Automatic SD mounting disabled; existing mounts unchanged')
            return result
        mounts = system.mounts()
        card = system.root_card(mounts)
        result['root_card'] = card
        parts = system.partitions(card)
        result['partitions'] = parts
        candidates = [p for p in parts if p['label'].casefold() == 'music']
        if not candidates:
            result['reason'] = 'No MUSIC-labelled extra partition on the OS SD card'
            return result
        if len(candidates) != 1:
            raise ValueError('Multiple MUSIC-labelled SD partitions; refusing to choose')
        candidate = candidates[0]
        result['device'] = '/dev/'+candidate['name']
        prior = existing_mount(candidate, mounts)
        if prior:
            result.update(status='already_mounted', target=prior['target'],
                          mount_options=prior['options'], reason='Existing path and mount options preserved')
            return result
        if candidate['fstype'] not in FILESYSTEMS:
            raise ValueError('Unsupported MUSIC filesystem: '+candidate['fstype'])
        if not any(m['target'] == '/media' and m['fstype'] == 'tmpfs' for m in mounts):
            raise ValueError('/media tmpfs is not ready; refusing an early mount that would be hidden')
        target = system.path(TARGET)
        if system.path('/media').is_symlink() or target.is_symlink():
            raise ValueError('Refusing a symlink music mount path')
        if any(m['target'] == TARGET for m in mounts):
            raise ValueError('/media/MUSIC is already occupied by another mount')
        if target.exists() and (not target.is_dir() or next(target.iterdir(), None) is not None):
            raise ValueError('/media/MUSIC is not an empty directory')
        # Recheck immediately before mounting; never cover a newly appeared mount.
        latest = system.mounts()
        if latest != mounts or not system.block_matches(candidate):
            raise ValueError('Mount/device state changed; retry at next startup')
        created = not target.exists()
        target.mkdir(mode=0o755, exist_ok=True)
        try:
            command = ['/usr/bin/mount', '-t', candidate['fstype'],
                       '-o', 'rw,nosuid,nodev,noexec,noatime', result['device'], TARGET]
            mounted = system.run(command, timeout=8)
            actual = next((m for m in system.mounts() if m['target'] == TARGET and
                           m['root'] == '/' and m['device_id'] == candidate['device_id']), None)
            if mounted.returncode or not actual:
                raise ValueError('SD mount failed: '+(mounted.stderr.strip()[:500] or
                                                     'filesystem not present at target after mount'))
            result.update(status='mounted', mount_options=actual['options'],
                          reason='MUSIC available in the browser at /media/MUSIC')
        except Exception:
            # rmdir only removes an empty, unmounted directory; never unmount.
            try:
                if created:
                    target.rmdir()
            except OSError:
                pass
            raise
    except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired) as error:
        result.update(status='error', reason=str(error)[:600])
    return result


def main():
    system = System()
    path = system.path(STATUS)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Serializes this helper; duplicate launches must not race mount().
    fd = os.open('/run/bitedj-sd-music.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('SD music helper already running', flush=True)
            return
        result = mount_music(system)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(result, indent=2)+'\n')
        temporary.replace(path)
        print('BiteDJ SD music: '+json.dumps(result), flush=True)
    finally:
        os.close(fd)


if __name__ == '__main__':
    main()
