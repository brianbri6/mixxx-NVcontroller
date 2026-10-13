#!/usr/bin/env python3
"""Build v0.5.7 from the exact Pi4 base and source-verified native executable."""
import argparse
import base64
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest import mock
import zstandard

from saved_release import ROOT, V05_PATH, V051_PATH, V052_PATH, V053_PATH, V054_PATH, V055_PATH, V056_PATH, load_v05, load_v051, load_v052, load_v053, load_v054, load_v055, load_v056, sha, parse_cpio, encode_cpio
from native_build_evidence import verify as verify_native
sys.path.insert(0, str(ROOT/'baseline_sources/v03/sources'))
from fat32 import Fat32
from patch_runtime import make as patch_runtime

OUT = ROOT/'work/package'
PAYLOAD = ROOT/'work/payload'
BASE = ROOT/'work/rootfs'
SLOT = 'usr/local/lib/bitedj-nv-v057'


def generated_namespace(source, name):
    namespace = {'__name__': name}
    exec(compile(source, name+'.py', 'exec'), namespace)
    return namespace


def validate_install(source, legacy_source, source_v051, source_v052, source_v053, source_v054, source_v055, source_v056, entries, compatibility):
    result = {}
    versions = ('v03', 'v04', 'v05_from_v03', 'v05_from_v04',
                'v051_from_v03', 'v051_from_v04', 'v051_from_v05',
                'v052_from_v03', 'v052_from_v04', 'v052_from_v05', 'v052_from_v051',
                'v053_from_v03', 'v053_from_v04', 'v053_from_v05', 'v053_from_v051', 'v053_from_v052',
                'v054_from_v03', 'v054_from_v04', 'v054_from_v05', 'v054_from_v051', 'v054_from_v052', 'v054_from_v053',
                'v055_from_v03', 'v055_from_v04', 'v055_from_v05', 'v055_from_v051', 'v055_from_v052', 'v055_from_v053', 'v055_from_v054', 'v056_from_v03', 'v056_from_v04', 'v056_from_v05', 'v056_from_v051', 'v056_from_v052', 'v056_from_v053', 'v056_from_v054', 'v056_from_v055')
    for version in versions:
        trials = ('normal', 'write_error', 'power_loss') if version in ('v052_from_v051', 'v053_from_v052', 'v054_from_v053', 'v055_from_v054', 'v056_from_v055') else ('normal',)
        for trial in trials:
            current = generated_namespace(source, 'nv_v057_validation')
            v05 = generated_namespace(legacy_source, 'nv_v05_validation')
            v051 = generated_namespace(source_v051, 'nv_v051_validation')
            v052 = generated_namespace(source_v052, 'nv_v052_validation')
            v053 = generated_namespace(source_v053, 'nv_v053_validation')
            v054 = generated_namespace(source_v054, 'nv_v054_validation')
            v055 = generated_namespace(source_v055, 'nv_v055_validation')
            v056 = generated_namespace(source_v056, 'nv_v056_validation')
            with tempfile.TemporaryDirectory(dir=ROOT/'work') as temporary:
                root = Path(temporary)
                paths = ['etc/deckshark-release', *compatibility,
                         *[e['path'] for e in entries if (BASE/e['path']).exists()]]
                for path in paths:
                    target = root/path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(BASE/path, target)
                boot = root/'boot/firmware'
                boot.mkdir(parents=True)
                config = ('[Soundcard]\nlatency 128\nNV_Audio_output 3\n[ControllerPreset]\n' +
                          ''.join(key+' '+current['NV_MAPPING']+'\n' for key in
                                  ('NV_Control_MIDI_1', 'NV_Audio_MIDI_1', 'NV_Graphics_MIDI_1')) +
                          '[Controller]\nNV_Control_MIDI_1 1\nNV_Audio_MIDI_1 1\nNV_Graphics_MIDI_1 1\n'
                          '[Channel1]\nrateRange 0.9\n[Waveform]\nType 0\n')
                settings = {'root/.mixxx/mixxx.cfg': config.encode(),
                            'boot/firmware/config.txt': b'EXACT USER HDMI CONFIGURATION\n',
                            'boot/firmware/BiteDJ_NV_display_mode.txt': b'overview\n',
                            'boot/firmware/BiteDJ_NV_browser_view.txt': b'right\n',
                            'boot/firmware/BiteDJ_SD_music.txt': b'off\n',
                            'boot/firmware/BiteDJ_NV_settings.json': b'{"scratchSensitivity":4,"vuTest":true}\n'}
                for name, data in settings.items():
                    target = root/name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                if version.endswith('v04') or version == 'v051_from_v05':
                    for name in ('BiteDJ-Numark-NV.js', 'Numark-NV-BiteDJ-Test.midi.xml'):
                        shutil.copy2(ROOT/'baseline_sources/v04/sources/payload'/name,
                                     root/'usr/share/mixxx/controllers'/name)
                old_updates = []
                versions_in_order = ['v05', 'v051', 'v052', 'v053', 'v054', 'v055', 'v056']
                target_version, _, previous_version = version.partition('_from_')
                chain = []
                if previous_version in versions_in_order:
                    chain = versions_in_order[:versions_in_order.index(previous_version)+1]
                if target_version in versions_in_order:
                    chain.append(target_version)
                for old_version in chain:
                    old = {'v05': v05, 'v051': v051, 'v052': v052, 'v053': v053, 'v054': v054, 'v055': v055, 'v056': v056}[old_version]
                    assert old['update'](root) == 'installed'
                    if old_version in ('v052', 'v053', 'v054', 'v055', 'v056'):
                        # Simulate startup, including the older preference journal.
                        old['nv_apply_settings'](root)
                        settings['root/.mixxx/mixxx.cfg'] = (root/'root/.mixxx/mixxx.cfg').read_bytes()
                    old_updates.append(old)
                originals = {entry['path']: ((root/entry['path']).read_bytes(),
                                             (root/entry['path']).stat().st_mode & 0o777)
                             if (root/entry['path']).exists() else None for entry in entries}
                legacy_untouched = {str(f.relative_to(root)): f.read_bytes()
                                    for prefix in ('usr/local/lib/bitedj-nv-v05', v05['BACKUP'],
                                                   'usr/local/lib/bitedj-nv-v051', v051['BACKUP'],
                                                   'usr/local/lib/bitedj-nv-v052', v052['BACKUP'],
                                                   'usr/local/lib/bitedj-nv-v053', v053['BACKUP'],
                                                   'usr/local/lib/bitedj-nv-v054', v054['BACKUP'],
                                                   'usr/local/lib/bitedj-nv-v055', v055['BACKUP'],
                                                   'usr/local/lib/bitedj-nv-v056', v056['BACKUP'])
                                    for f in (root/prefix).rglob('*') if f.is_file()}

                def check_restored():
                    for name, old in originals.items():
                        if old is None:
                            assert not (root/name).exists(), name
                        else:
                            assert (root/name).read_bytes() == old[0], name
                            assert (root/name).stat().st_mode & 0o777 == old[1], name
                    for name, data in settings.items():
                        assert (root/name).read_bytes() == data, name

                if trial != 'normal':
                    writer = current['atomic_write']
                    failed = False
                    def fail_once(path, data, mode=0o644):
                        nonlocal failed
                        if path == root/'usr/share/mixxx/controllers/BiteDJ-Numark-NV.js' and not failed:
                            failed = True
                            if trial == 'power_loss':
                                raise KeyboardInterrupt('simulated abrupt termination during '+version)
                            raise OSError('simulated write error during '+version)
                        return writer(path, data, mode)
                    with mock.patch.dict(current, {'atomic_write': fail_once}):
                        if trial == 'power_loss':
                            try:
                                current['update'](root)
                            except KeyboardInterrupt:
                                pass
                            else:
                                raise AssertionError('Expected interruption was not injected')
                        else:
                            assert current['update'](root) == 'error'
                            check_restored()
                assert current['update'](root) == 'installed'
                mtimes = [(root/e['path']).stat().st_mtime_ns for e in entries]
                assert current['update'](root) == 'already_installed'
                assert mtimes == [(root/e['path']).stat().st_mtime_ns for e in entries]
                for entry in entries:
                    assert sha((root/entry['path']).read_bytes()) == entry['new_sha256']
                # Exercise the exact installed preflight, not just the template.
                preflight = generated_namespace((root/SLOT/'nv_settings.py').read_text(), 'nv_startup_validation')
                assert preflight['NV_JOURNAL'] == current['NV_JOURNAL'] == current['BACKUP']+'/settings.json'
                preflight['nv_apply_settings'](root)
                cfg_path = root/'root/.mixxx/mixxx.cfg'
                expected_prefix = settings['root/.mixxx/mixxx.cfg'].decode().split('[ControllerSettings_', 1)[0].replace('NV_Audio_MIDI_1 1', 'NV_Audio_MIDI_1 0').replace('NV_Graphics_MIDI_1 1', 'NV_Graphics_MIDI_1 0')
                assert cfg_path.read_text().split('[ControllerSettings_', 1)[0] == expected_prefix
                group = preflight['nv_setting_group']('NV Control MIDI 1')
                assert preflight['nv_get'](cfg_path.read_text(), group, 'scratchSensitivity') == '4'
                assert preflight['nv_get'](cfg_path.read_text(), group, 'vuTest') == 'true'
                stamp = cfg_path.stat().st_mtime_ns
                preflight['nv_apply_settings'](root)
                assert cfg_path.stat().st_mtime_ns == stamp
                for name, data in {**settings, **legacy_untouched}.items():
                    if name != 'root/.mixxx/mixxx.cfg':
                        assert (root/name).read_bytes() == data, name
                (boot/current['ROLLBACK']).touch()
                assert current['update'](root) == 'rolled_back'
                assert current['update'](root) == 'rolled_back'
                check_restored()
                for name, data in legacy_untouched.items():
                    assert (root/name).read_bytes() == data, name
                for name, expected in compatibility.items():
                    assert sha((root/name).read_bytes()) == expected
                # Walk backward through each saved updater; none of its journals
                # or slots may have been taken over by the newer update.
                for previous_update in reversed(old_updates):
                    (boot/previous_update['ROLLBACK']).touch()
                    assert previous_update['update'](root) == 'rolled_back'
                assert (root/'usr/bin/start-mixxx').read_bytes() == (BASE/'usr/bin/start-mixxx').read_bytes()
                assert (root/'root/.mixxx/mixxx.cfg').read_bytes() == config.encode()
                result[version + (':' + trial if trial != 'normal' else '')] = 'passed'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--v05-release', type=Path, default=V05_PATH)
    parser.add_argument('--v051-release', type=Path, default=V051_PATH)
    parser.add_argument('--v052-release', type=Path, default=V052_PATH)
    parser.add_argument('--v053-release', type=Path, default=V053_PATH)
    parser.add_argument('--v054-release', type=Path, default=V054_PATH)
    parser.add_argument('--v055-release', type=Path, default=V055_PATH)
    parser.add_argument('--v056-release', type=Path, default=V056_PATH)
    parser.add_argument('--native-binary', type=Path, required=True, help='Native binary with matching source/build evidence')
    args = parser.parse_args()
    native_evidence = verify_native(args.native_binary)
    archive, legacy_source, legacy_payload, compatibility = load_v05(args.v05_release)
    archive_v051, source_v051, payload_v051, compatibility_v051 = load_v051(args.v051_release)
    archive_v052, source_v052, payload_v052, compatibility_v052 = load_v052(args.v052_release)
    archive_v053, source_v053, payload_v053, compatibility_v053 = load_v053(args.v053_release)
    archive_v054, source_v054, payload_v054, compatibility_v054 = load_v054(args.v054_release)
    archive_v055, source_v055, payload_v055, compatibility_v055 = load_v055(args.v055_release)
    archive_v056, source_v056, payload_v056, compatibility_v056 = load_v056(args.v056_release)
    assert compatibility_v056 == compatibility, 'Previous runtime compatibility differs'
    assert compatibility_v055 == compatibility, 'Previous runtime compatibility differs'
    assert compatibility_v051 == compatibility, 'Previous runtime compatibility differs'
    assert compatibility_v052 == compatibility, 'Previous runtime compatibility differs'
    assert compatibility_v053 == compatibility, 'Previous runtime compatibility differs'
    assert compatibility_v054 == compatibility, 'Previous runtime compatibility differs'
    previous = {e['path']: e for e in legacy_payload}
    previous_v051 = {e['path']: e for e in payload_v051}
    previous_v052 = {e['path']: e for e in payload_v052}
    previous_v053 = {e['path']: e for e in payload_v053}
    previous_v054 = {e['path']: e for e in payload_v054}
    previous_v055 = {e['path']: e for e in payload_v055}
    previous_v056 = {e['path']: e for e in payload_v056}
    OUT.mkdir(parents=True, exist_ok=True)
    # PAYLOAD is generated output. Never merge obsolete version slots into it.
    if PAYLOAD.exists():
        shutil.rmtree(PAYLOAD)
    patch_runtime()
    slot = PAYLOAD/SLOT
    (slot/'nvdisplay').mkdir(parents=True)
    for name in ('__init__.py', 'framing.py', 'protocol.py', 'transport.py', 'service.py', 'palette.bin'):
        shutil.copy2(ROOT/'nvdisplay'/name, slot/'nvdisplay'/name)
    shutil.copy2(ROOT/'runtime/launch.sh', slot/'launch.sh')
    shutil.copy2(ROOT/'runtime/nv_settings.py', slot/'nv_settings.py')
    shutil.copy2(ROOT/'runtime/sd_music.py', slot/'sd_music.py')
    (slot/'launch.sh').chmod(0o755)
    validated_v054 = json.loads(archive_v054.read('validation/package.json'))
    reused_v054 = native_evidence == validated_v054['native_build']
    if reused_v054:
        # Runtime-only update: preserve the exact validated executable without
        # needing to reconstruct a cross-toolchain just to strip it again.
        native = previous_v054['usr/local/lib/bitedj-nv-v054/bitedj']
        data = base64.b64decode(native['base64'], validate=True)
        assert sha(data) == validated_v054['native_sha256'] == native['new_sha256']
        (slot/'bitedj').write_bytes(data)
    else:
        subprocess.run(['sh', str(ROOT/'work/build-env.sh'), 'aarch64-linux-gnu-strip',
                        '-o', str(slot/'bitedj'), str(args.native_binary)], check=True)
    (slot/'bitedj').chmod(0o755)
    for name in ('BiteDJ-Numark-NV.js', 'Numark-NV-BiteDJ-Test.midi.xml'):
        dest = PAYLOAD/'usr/share/mixxx/controllers'/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        origin = ROOT/'controller'/name
        shutil.copy2(origin, dest)
    entries = []
    for file in sorted(PAYLOAD.rglob('*')):
        if not file.is_file():
            continue
        name = str(file.relative_to(PAYLOAD))
        original = BASE/name
        allowed = [sha(original.read_bytes())] if original.exists() else [None]
        if name in previous:
            allowed.append(previous[name]['new_sha256'])  # v0.5/v0.4
        if name in previous_v051:
            allowed.append(previous_v051[name]['new_sha256'])
        if name in previous_v052:
            allowed.append(previous_v052[name]['new_sha256'])
        if name in previous_v053:
            allowed.append(previous_v053[name]['new_sha256'])
        if name in previous_v054:
            allowed.append(previous_v054[name]['new_sha256'])
        if name in previous_v056:
            allowed.append(previous_v056[name]['new_sha256'])
        if name in previous_v055:
            allowed.append(previous_v055[name]['new_sha256'])
        entries.append({'path': name, 'old_sha256': list(dict.fromkeys(allowed)),
                        'new_sha256': sha(file.read_bytes()), 'mode': file.stat().st_mode & 0o777,
                        'base64': base64.b64encode(file.read_bytes()).decode()})
    for name, expected in compatibility.items():
        assert sha((BASE/name).read_bytes()) == expected, 'Base application differs'
    source = (ROOT/'runtime/update_installer.py').read_text()
    helper = (ROOT/'runtime/nv_settings.py').read_text().split("\nif __name__ == '__main__':", 1)[0]
    marker_import = 'from runtime.nv_settings import nv_restore_settings'
    assert source.count(marker_import) == 1
    source = source.replace(marker_import, helper)
    assert source.count('PAYLOAD = None') == source.count('COMPATIBILITY = None') == 1
    source = source.replace('PAYLOAD = None', 'PAYLOAD = ' + repr(entries))
    source = source.replace('COMPATIBILITY = None', 'COMPATIBILITY = ' + repr(compatibility))
    compile(source, 'nv_v057_generated.py', 'exec')
    (OUT/'nv_v057_generated.py').write_text(source)
    fat = Fat32(ROOT/'work/base/boot.img')
    item = next(e for e in fat.entries() if e['name'].casefold() == 'initramfs.img')
    original = fat.chain(item['cluster'])[:item['size']]
    prior_validation = json.loads(archive.read('validation/package.json'))
    assert sha(original) == prior_validation['base_initramfs_sha256']
    records = parse_cpio(zstandard.ZstdDecompressor().decompress(original))
    before = copy.deepcopy({r[3]: r for r in records})
    init = next(r for r in records if r[3] == 'init')
    marker = b'exec /bin/busybox switch_root /newroot /sbin/init'
    assert init[4].count(marker) == 1
    block = b'''# Fixed NV v0.5.7 update; never executes commands or Python supplied on BOOT.
if /bin/busybox chroot /newroot /usr/bin/python3 - < /bitedj-nv-v057.py; then
    echo "BiteDJ: NV v0.5.7 update checked"
else
    echo "BiteDJ: NV v0.5.7 update skipped; see BOOT/BiteDJ_NV_v057_update.txt" >&2
fi

'''
    init[4] = init[4].replace(marker, block+marker)
    (OUT/'initramfs-init.sh').write_bytes(init[4])
    for script in (OUT/'initramfs-init.sh', slot/'launch.sh', PAYLOAD/'usr/bin/start-mixxx'):
        subprocess.run(['sh', '-n', str(script)], check=True)
    name = b'bitedj-nv-v057.py\0'
    data = source.encode()
    fields = [max(r[1][0] for r in records)+1, 0o100644, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(name), 0]
    records.insert(len(records)-1, [b'070701', fields, name, name[:-1].decode(), data])
    packed = zstandard.ZstdCompressor(level=10).compress(encode_cpio(records))
    restored = {r[3]: r for r in parse_cpio(zstandard.ZstdDecompressor().decompress(packed))}
    assert len(restored) == len(before)+1
    for name, record in before.items():
        if name == 'init':
            assert restored[name][4].replace(block, b'') == record[4]
        else:
            assert restored[name] == record, name
    assert restored['bitedj-nv-v057.py'][4] == data
    (OUT/'initramfs.img').write_bytes(packed)
    fat.replace('initramfs.img', packed)
    fat_stats = fat.validate()
    install_results = validate_install(source, legacy_source, source_v051, source_v052, source_v053, source_v054, source_v055, source_v056, entries, compatibility)
    native_sha = sha((slot/'bitedj').read_bytes())
    result = {'version': '0.5.7 experimental', 'source_commit': prior_validation['source_commit'],
              'native_sha256': native_sha,
              'native_build': native_evidence,
              'native_reused_from_v054': reused_v054,
              'build_sources': {p: sha((ROOT/p).read_bytes()) for p in
                                ('scripts/build_update.py', 'scripts/patch_runtime.py', 'runtime/update_installer.py')},
              'native_reused_from_v05': native_sha == previous['usr/local/lib/bitedj-nv-v05/bitedj']['new_sha256'],
              'initramfs_sha256': sha(packed), 'initramfs_bytes': len(packed),
              'base_initramfs_sha256': sha(original), 'preserved_cpio_members': len(before)-1,
              'added_cpio_members': 1, 'shell_syntax': 'passed', 'fat_validation': fat_stats,
              'actual_payload_install_idempotence_rollback': install_results,
              'unrelated_settings_bytes_preserved': True, 'owned_nv_preferences_reversible': True, 'hardware_tested': False,
              'live_socket_test': 'not repeated; blocked by execution environment in v0.5',
              'payload': [{k: v for k, v in e.items() if k != 'base64'} for e in entries],
              'compatibility': compatibility}
    (OUT/'validation.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'payload'}, indent=2))


if __name__ == '__main__':
    main()
