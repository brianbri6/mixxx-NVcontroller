#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Narrow, reversible NV preferences, applied before BiteDJ opens its devices.

BOOT supplies validated JSON data only. No BOOT scripts or mapping code run.
Only two MIDI enable flags and this mapping's named tuning keys are owned.
"""
import json
import math
import os
from pathlib import Path
import re

NV_CONFIG = 'root/.mixxx/mixxx.cfg'
NV_JOURNAL = 'usr/local/share/bitedj-nv-v057-backup/settings.json'
NV_OPTIONS = 'boot/firmware/BiteDJ_NV_settings.json'
NV_STATUS = 'tmp/bitedj-nv/settings-status.json'
NV_MAPPING = '/usr/share/mixxx/controllers/Numark-NV-BiteDJ-Test.midi.xml'
NV_CONTROL_NAMES = ('NV Control MIDI 1', 'NV MIDI 1', 'Numark NV MIDI 1')
NV_DISPLAY_KEYS = ('NV_Audio_MIDI_1', 'NV_Graphics_MIDI_1')
NV_NUMBERS = {'scratchSensitivity': (0.25, 8), 'jogSensitivity': (0.05, 2),
              'vuSilenceThreshold': (0.0002, 0.1), 'vuPeakLevel': (4, 5)}
NV_NUMBERS.update({'padColor' + str(i): (0, 52) for i in range(1, 9)})
NV_PAD_PALETTE = (0, 3, 6, 12, 21, 48, 52)
NV_BOOLEANS = ('vuFollowFader', 'vuTest')


def nv_setting_group(name):
    # Pinned LegacyControllerMapping::loadSettings uses the unsanitized device
    # name and replaces the resource path INCLUDING its trailing slash.
    return '[ControllerSettings_' + name + '_%RESOURCE_PATHcontrollers/Numark-NV-BiteDJ-Test.midi.xml]'


def nv_atomic_write(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.nv-settings-new')
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


def nv_read(path):
    if path.is_symlink():
        raise ValueError('Refusing NV settings symlink: ' + str(path))
    return path.read_bytes()


def nv_config_index(text):
    lines, entries, sections, group = text.splitlines(keepends=True), {}, {}, None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            group = stripped
            sections.setdefault(group, []).append(i)
        elif group and stripped and not stripped.startswith(('#', ';')):
            parts = stripped.split(None, 1)
            entries.setdefault((group, parts[0]), []).append((i, parts[1] if len(parts) > 1 else ''))
    return lines, entries, sections


def nv_get(text, group, key):
    entries = nv_config_index(text)[1].get((group, key), [])
    if len(entries) > 1:
        raise ValueError('Duplicate NV preference: ' + key)
    return entries[0][1] if entries else None


def nv_set(text, group, key, value):
    lines, entries, sections = nv_config_index(text)
    rows = entries.get((group, key), [])
    if len(rows) > 1 or len(sections.get(group, [])) > 1:
        raise ValueError('Ambiguous NV preference section/key: ' + key)
    if rows:
        i, _ = rows[0]
        if value is None:
            del lines[i]
        else:
            ending = '\r\n' if lines[i].endswith('\r\n') else '\n' if lines[i].endswith('\n') else ''
            prefix = re.match(r'^[ \t]*\S+[ \t]*', lines[i]).group()
            if not prefix.endswith((' ', '\t')):
                prefix += ' '
            lines[i] = prefix + value + ending
        return ''.join(lines)
    if value is None:
        return text
    ending = '\r\n' if '\r\n' in text else '\n'
    if group in sections:
        lines.insert(sections[group][0] + 1, key + ' ' + value + ending)
        return ''.join(lines)
    return text + ('' if not text or text.endswith('\n') else ending) + group + ending + key + ' ' + value + ending


def nv_options(path):
    if not path.exists():
        return {}
    raw = nv_read(path)
    if len(raw) > 4096:
        raise ValueError('BiteDJ_NV_settings.json exceeds 4096 bytes')
    values = json.loads(raw)
    if not isinstance(values, dict) or set(values) - (set(NV_NUMBERS) | set(NV_BOOLEANS)):
        raise ValueError('Unknown option in BiteDJ_NV_settings.json')
    for key, value in values.items():
        if key in NV_BOOLEANS:
            valid = type(value) is bool
        else:
            low, high = NV_NUMBERS[key]
            valid = type(value) in (int, float) and math.isfinite(value) and low <= value <= high
            if key.startswith('padColor'):
                valid = valid and value in NV_PAD_PALETTE
            if key == 'vuPeakLevel':
                valid = valid and value in (4, 5)
        if not valid:
            raise ValueError('Invalid NV option: ' + key)
    return values


def nv_owned(group, key):
    return (group == '[Controller]' and key in NV_DISPLAY_KEYS) or (
        group in [nv_setting_group(name) for name in NV_CONTROL_NAMES] and
        key in set(NV_NUMBERS) | set(NV_BOOLEANS))


def nv_load_journal(root):
    path = root/NV_JOURNAL
    if not path.exists():
        return {'format': 1, 'restored': False, 'changes': [], 'created_sections': []}
    state = json.loads(nv_read(path))
    if not isinstance(state, dict) or state.get('format') != 1 or type(state.get('restored')) is not bool or not isinstance(state.get('changes'), list):
        raise ValueError('Invalid NV preference journal')
    seen = set()
    for entry in state['changes']:
        group, key = entry.get('group'), entry.get('key')
        if not nv_owned(group, key) or (group, key) in seen:
            raise ValueError('Invalid NV preference journal key')
        seen.add((group, key))
        for value in (entry.get('before'), entry.get('after')):
            if value is not None and (not isinstance(value, str) or '\n' in value or '\r' in value):
                raise ValueError('Invalid NV preference journal value')
    if not isinstance(state.get('created_sections'), list) or any(
            group not in [nv_setting_group(name) for name in NV_CONTROL_NAMES] for group in state['created_sections']):
        raise ValueError('Invalid NV preference journal sections')
    return state


def nv_apply_settings(root=Path('/'), writer=nv_atomic_write):
    root = Path(root)
    path = root/NV_CONFIG
    text = nv_read(path).decode('utf-8')
    options = nv_options(root/NV_OPTIONS)  # Reject the entire bad document before mutation.
    wanted = []
    for key in NV_DISPLAY_KEYS:
        # Never take over an unrelated controller mapping or change audio routing.
        if nv_get(text, '[ControllerPreset]', key) == NV_MAPPING and nv_get(text, '[Controller]', key) is not None:
            wanted.append(('[Controller]', key, '0'))
    for name in NV_CONTROL_NAMES:
        if nv_get(text, '[ControllerPreset]', name.replace(' ', '_')) == NV_MAPPING:
            for key, value in options.items():
                wanted.append((nv_setting_group(name), key,
                               str(value).lower() if type(value) is bool else format(value, '.12g')))
    state = nv_load_journal(root)
    if state['restored']:
        state = {'format': 1, 'restored': False, 'changes': [], 'created_sections': []}
    entries = {(e['group'], e['key']): e for e in state['changes']}
    updated = text
    for group, key, value in wanted:
        before = nv_get(updated, group, key)
        if before == value:
            continue
        if group not in nv_config_index(updated)[2] and group not in state['created_sections']:
            state['created_sections'].append(group)
        entry = entries.get((group, key))
        if entry is None:
            entry = {'group': group, 'key': key, 'before': before, 'after': value}
            entries[(group, key)] = entry
        else:
            entry['after'] = value
        updated = nv_set(updated, group, key, value)
    if updated != text:
        state['changes'] = list(entries.values())
        # Journal is durable first; rollback merges only owned keys and keeps later edits.
        writer(root/NV_JOURNAL, (json.dumps(state, indent=2) + '\n').encode(), 0o600)
        writer(path, updated.encode(), path.stat().st_mode & 0o777)
    status = {'version': '0.5.7', 'options_from_boot': options,
              'display_midi_enabled': {key: nv_get(updated, '[Controller]', key) for key in NV_DISPLAY_KEYS},
              'audio_routing_changed': False}
    writer(root/NV_STATUS, (json.dumps(status, indent=2) + '\n').encode())
    return status


def nv_restore_settings(root, writer=nv_atomic_write):
    root = Path(root)
    state = nv_load_journal(root)
    if state['restored'] or not state['changes']:
        return
    path = root/NV_CONFIG
    text = nv_read(path).decode('utf-8')
    updated = text
    for entry in state['changes']:
        group, key = entry['group'], entry['key']
        if nv_get(updated, group, key) == entry['after']:
            updated = nv_set(updated, group, key, entry['before'])
    # Remove only headers we created, and only if the section is now empty.
    for group in state['created_sections']:
        lines, entries, sections = nv_config_index(updated)
        if len(sections.get(group, [])) == 1 and not any(g == group for g, _ in entries):
            del lines[sections[group][0]]
            updated = ''.join(lines)
    if updated != text:
        writer(path, updated.encode(), path.stat().st_mode & 0o777)
    state['restored'] = True
    writer(root/NV_JOURNAL, (json.dumps(state, indent=2) + '\n').encode(), 0o600)


if __name__ == '__main__':
    try:
        print('BiteDJ NV settings: ' + json.dumps(nv_apply_settings()), flush=True)
    except Exception as error:
        status = {'version': '0.5.7', 'error': str(error), 'previous_settings_retained': True}
        print('BiteDJ NV settings: ' + json.dumps(status), flush=True)
        try:
            nv_atomic_write(Path('/')/NV_STATUS, json.dumps(status).encode())
        except OSError:
            pass
        raise SystemExit(1)
