#!/usr/bin/env python3
"""Bundle the checked updater, sources/patch, evidence, and instructions."""
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile
from saved_release import load_v05
from native_build_evidence import verify as verify_native

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'dist/BiteDJ_Pi4_NV_Display_Test_v0_5_7.zip'
PIN = '78074e05c8bf99ede6fedd755aa68bd222ba343c'


def main():
    if OUT.exists():
        raise SystemExit('Refusing to overwrite an existing release ZIP: '+str(OUT))
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT):
        raise SystemExit('Commit source and documentation before packaging.')
    package = ROOT/'work/package'
    validation = json.loads((package/'validation.json').read_text())
    image = (package/'initramfs.img').read_bytes()
    if hashlib.sha256(image).hexdigest() != validation['initramfs_sha256']:
        raise SystemExit('Initramfs differs from the validated package')
    checks = ('v03', 'v04', 'v05_from_v03', 'v05_from_v04',
              'v051_from_v03', 'v051_from_v04', 'v051_from_v05',
              'v052_from_v03', 'v052_from_v04', 'v052_from_v05', 'v052_from_v051',
              'v052_from_v051:write_error', 'v052_from_v051:power_loss',
              'v053_from_v03', 'v053_from_v04', 'v053_from_v05', 'v053_from_v051', 'v053_from_v052',
              'v053_from_v052:write_error', 'v053_from_v052:power_loss',
              'v054_from_v03', 'v054_from_v04', 'v054_from_v05', 'v054_from_v051', 'v054_from_v052', 'v054_from_v053',
              'v054_from_v053:write_error', 'v054_from_v053:power_loss',
              'v055_from_v03', 'v055_from_v04', 'v055_from_v05', 'v055_from_v051', 'v055_from_v052', 'v055_from_v053', 'v055_from_v054',
              'v055_from_v054:write_error', 'v055_from_v054:power_loss', 'v056_from_v03', 'v056_from_v04', 'v056_from_v05', 'v056_from_v051', 'v056_from_v052', 'v056_from_v053', 'v056_from_v054', 'v056_from_v055', 'v056_from_v055:write_error', 'v056_from_v055:power_loss')
    if validation['actual_payload_install_idempotence_rollback'] != dict.fromkeys(checks, 'passed'):
        raise SystemExit('Direct install, upgrade, fault recovery and rollback must pass validation')
    if validation['version'] != '0.5.7 experimental':
        raise SystemExit('Expected the v0.5.7 validation record')
    native = verify_native(ROOT/'work/build-arm/mixxx')
    if (validation.get('native_build') != native or validation['native_reused_from_v05'] or
            validation.get('native_reused_from_v054')):
        raise SystemExit('This browser update requires a fresh source-verified native build')
    for name in ('abi-audit.json', 'native-version.json'):
        result = json.loads((ROOT/'work'/name).read_text())
        if result['native_sha256'] != native['native_sha256']:
            raise SystemExit('Native validation refers to a different executable: '+name)
        if result.get('missing') or result.get('passed') is False:
            raise SystemExit('Native validation failed: '+name)
    for name, expected in validation['build_sources'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != expected:
            raise SystemExit('Rebuild changed installer source: '+name)
    # Refuse stale generated payloads after an unrebuilt source edit.
    current_sources = {
        'runtime/launch.sh': 'usr/local/lib/bitedj-nv-v057/launch.sh',
        'runtime/nv_settings.py': 'usr/local/lib/bitedj-nv-v057/nv_settings.py',
        'runtime/sd_music.py': 'usr/local/lib/bitedj-nv-v057/sd_music.py',
        **{'nvdisplay/'+name: 'usr/local/lib/bitedj-nv-v057/nvdisplay/'+name for name in
           ('__init__.py', 'framing.py', 'protocol.py', 'transport.py', 'service.py', 'palette.bin')},
        **{'controller/'+name: 'usr/share/mixxx/controllers/'+name for name in
           ('BiteDJ-Numark-NV.js', 'Numark-NV-BiteDJ-Test.midi.xml')}
    }
    hashes = {item['path']: item['new_sha256'] for item in validation['payload']}
    for source_name, target in current_sources.items():
        if hashlib.sha256((ROOT/source_name).read_bytes()).hexdigest() != hashes[target]:
            raise SystemExit('Rebuild changed payload source: '+source_name)
    previous, _, _, _ = load_v05()
    source = ROOT/'vendor/bitedj'
    patch = []
    native_files = () if validation['native_reused_from_v05'] else (
        'CMakeLists.txt', 'src/coreservices.cpp', 'src/library/library.h', 'src/library/library.cpp',
        'src/controllers/numarknvexporter.h', 'src/controllers/numarknvexporter.cpp',
        'src/library/sidebarmodel.cpp', 'src/widget/wlibrarysidebar.cpp')
    for name in native_files:
        if name.startswith('src/controllers/numarknvexporter'):
            before = ''
            origin = '/dev/null'
        else:
            before = subprocess.check_output(['git', '-C', str(source), 'show', PIN+':'+name], text=True)
            origin = 'a/'+name
        after = (source/name).read_text()
        patch.extend(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                          fromfile=origin, tofile='b/'+name))
    patch_text = (previous.read('source/bitedj-nv.patch').decode() if validation['native_reused_from_v05']
                  else ''.join(patch))
    (package/'bitedj-nv.patch').write_text(patch_text)
    attribution = f'''BiteDJ official source: https://github.com/TeamDeckshark/bitedj
Base commit: {PIN}
Upstream Mixxx base: 2.5.6
Apply source/bitedj-nv.patch to this exact source revision.
Native integration files and reproducible build scripts are in source/project/.
libkeyfinder 2.2.8 source is included; it was built statically by BiteDJ CMake.
Its source archive SHA-256: 4f10e9e5673d948776e47e78273fa4d61408155cb0e210af1538c83222f285d4
Binary links against the unmodified Pi4 runtime libraries; no runtime shared libraries are replaced.
The original image and mapping authors retain their licenses and attribution.
Generated Python bridge/integration code: MIT. Native exporter: GPL-2.0-or-later.
Full project Git history and supplied captures are in BiteDJ_NV_Recovery_Checkpoint.zip.
v0.5.7 fixes native mixed-folder activation and adds Shift-navigation expansion.
Retains v0.5.6 controls and the user-confirmed v0.5.5 SD MUSIC fix.
It retains bounded native FX-name/metaknob and active HDMI browser export.
The renderer populates capture-grounded 0A/21/22/24 text fields and clears stale rows.
The freshly built v0.5.7 ARM64 executable is bound to its source hashes and checked against the
original runtime libraries. Current native ABI/version evidence is in validation/;
earlier evidence remains labelled prior-v05. No sound routing or DSP code changed.
Full waveform mode, VU clearing, adjustable scratch and diagnostic input observer
remain from v0.5.3. Existing BOOT mode/settings files are honored.
The optional browser-view test uses captured B0 16 00/01; preserve is the default.
v0.5.7 has its own slot and journal. Rollback returns to the previous version,
including v0.5.6. No physical NV/Pi test was performed. D. VIEW cycling, cue/loop
overlays, detailed LCD FX enable/parameter graphics and artwork remain unresolved.
'''
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    OUT.parent.mkdir(exist_ok=True)
    manifest = {}
    with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        def put(name, data):
            z.writestr(name, data)
            manifest[name] = hashlib.sha256(data).hexdigest()
        put('README_FIRST.md', (ROOT/'README.md').read_bytes())
        put('CODEX_PROGRESS.md', (ROOT/'CODEX_PROGRESS.md').read_bytes())
        put('NEXT_TASK.md', (ROOT/'NEXT_TASK.md').read_bytes())
        put('install/initramfs.img', image)
        # The mode file is optional: copy only initramfs for an SD-only update.
        # Existing BOOT mode and SD options stay user-owned.
        put('install/BiteDJ_NV_display_mode.txt', b'full\n')
        put('rollback/BiteDJ_NV_v057_rollback', b'')
        put('settings/BiteDJ_NV_settings.json', (ROOT/'controller/BiteDJ_NV_settings.json').read_bytes())
        lamp_test = json.loads((ROOT/'controller/BiteDJ_NV_settings.json').read_text())
        lamp_test['vuTest'] = True
        put('settings/lamp-test/BiteDJ_NV_settings.json', (json.dumps(lamp_test, indent=2)+'\n').encode())
        for mode in ('info', 'overview', 'full', 'off'):
            put('mode-examples/'+mode+'/BiteDJ_NV_display_mode.txt', (mode+'\n').encode())
        for mode in ('auto', 'off'):
            put('sd-music-examples/'+mode+'/BiteDJ_SD_music.txt', (mode+'\n').encode())
        for mode in ('preserve', 'performance', 'left', 'right', 'both'):
            put('browser-view-examples/'+mode+'/BiteDJ_NV_browser_view.txt', (mode+'\n').encode())
        put('validation/package.json', (package/'validation.json').read_bytes())
        for name in ('capture-validation.json', 'test-v057.log', 'test-controller-v057.log',
                     'test-package-v057.log', 'test-sd-music-v057.log', 'native-build.json', 'abi-audit.json', 'native-version.json',
                     'build-arm-v054.log', 'build-arm-v057.log', 'packages-arm64.json', 'packages-amd64.json'):
            file = ROOT/'work'/name
            if file.exists():
                put('validation/'+name, file.read_bytes())
        for name in previous.namelist():
            if name.startswith('validation/'):
                put('validation/prior-v05/'+name[len('validation/'):], previous.read(name))
        put('source/bitedj-nv.patch', patch_text.encode())
        put('SOURCE_ATTRIBUTION.txt', attribution.encode())
        put('LICENSES/GPL-2.0.txt', (ROOT/'baseline_sources/v04/GPL-2.0.txt').read_bytes())
        put('LICENSES/MIT.txt', (ROOT/'baseline_sources/v04/MIT_LICENSE.txt').read_bytes())
        put('LICENSES/BiteDJ-LICENSE.txt', previous.read('LICENSES/BiteDJ-LICENSE.txt'))
        put('source/libkeyfinder-2.2.8.zip', previous.read('source/libkeyfinder-2.2.8.zip'))
        for name in paths:
            if name and (ROOT/name).is_file():
                put('source/project/'+name, (ROOT/name).read_bytes())
        z.writestr('SHA256SUMS.txt', ''.join(value+'  '+name+'\n' for name, value in sorted(manifest.items())))
    with zipfile.ZipFile(OUT) as z:
        if z.testzip() is not None:
            raise SystemExit('Release ZIP integrity check failed')
        for name, expected in manifest.items():
            if hashlib.sha256(z.read(name)).hexdigest() != expected:
                raise SystemExit('Archive content mismatch: '+name)
    print(OUT)
    print('sha256='+hashlib.sha256(OUT.read_bytes()).hexdigest())
    print('bytes='+str(OUT.stat().st_size))


if __name__ == '__main__':
    main()

