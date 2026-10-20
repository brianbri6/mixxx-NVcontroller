#!/usr/bin/env python3
"""Package committed sources, Git history and capture inputs for recovery."""
import hashlib
import argparse
import json
import pathlib
import subprocess
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'dist' / 'BiteDJ_NV_Recovery_Checkpoint.zip'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-native-build', action='store_true',
                        help='Preserve the verified native executable and its evidence for interrupted runs')
    parser.add_argument('--with-package', action='store_true',
                        help='Also preserve a validated initramfs and its package evidence')
    parser.add_argument('--github-source-ref',
                        help='Published commit in work/github; retain its reference instead of duplicating Git-backed files')
    args = parser.parse_args()
    if args.with_package and not args.with_native_build:
        parser.error('--with-package requires --with-native-build')
    changed = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT)
    if changed:
        raise SystemExit('Commit tracked changes before checkpointing.')
    files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    source_record = None
    if args.github_source_ref:
        github = ROOT/'work/github'
        published = subprocess.check_output(['git', 'rev-parse', args.github_source_ref], cwd=github, text=True).strip()
        source_hashes = {}
        for name in files:
            if name and (ROOT/name).is_file():
                blob = subprocess.check_output(['git', 'show', published+':bitedj-nv/'+name], cwd=github)
                if blob != (ROOT/name).read_bytes():
                    raise SystemExit('Publish the current source before checkpointing: '+name)
                source_hashes[name] = hashlib.sha256(blob).hexdigest()
        source_record = {'repository': 'https://github.com/brianbri6/mixxx-NVcontroller.git',
                         'commit': published, 'project_path': 'bitedj-nv',
                         'local_source_commit': commit, 'source_file_sha256': source_hashes}
    OUT.parent.mkdir(exist_ok=True)
    build_files = []
    if args.with_native_build:
        from native_build_evidence import verify
        native = verify(ROOT/'work/build-arm/mixxx')
        build_files = ['work/build-arm/mixxx', 'work/native-build.json']
        build_files += [str(p.relative_to(ROOT)) for pattern in
                        ('abi-audit.json', 'native-version.json', 'packages-*.json',
                         'build-arm-v054.log', 'test*v054.log', 'test*v055*.log', 'test*v056*.log', 'test*v057*.log', 'test*v058*.log', 'build-arm-v057*.log', 'toolchain-v057.log', 'capture-validation.json')
                        for p in sorted((ROOT/'work').glob(pattern))]
        if args.with_package:
            package = ROOT/'work/package'
            validation = json.loads((package/'validation.json').read_text())
            if (validation.get('native_build') != native or
                    hashlib.sha256((package/'initramfs.img').read_bytes()).hexdigest() !=
                    validation['initramfs_sha256'] or
                    validation.get('version') != '0.5.8 experimental' or
                    len(validation['actual_payload_install_idempotence_rollback']) != 58 or
                    set(validation['actual_payload_install_idempotence_rollback'].values()) != {'passed'}):
                raise SystemExit('Package evidence is incomplete or does not match the native build')
            build_files += ['work/package/initramfs.img', 'work/package/validation.json']
    pins = json.loads((ROOT/'INPUTS.json').read_text())
    attachments = [name for name in pins if name.startswith('project_sources/') and
                   pathlib.Path(name).suffix in ('.pcapng', '.pdf')]
    for name in attachments:
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != pins[name]:
            raise SystemExit('Input attachment changed: '+name)
    with tempfile.TemporaryDirectory() as tmp:
        bundle = pathlib.Path(tmp) / 'repository.bundle'
        if source_record is None:
            subprocess.run(['git', 'bundle', 'create', str(bundle), '--all'], cwd=ROOT, check=True)
        with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            if source_record is not None:
                z.writestr('GITHUB_SOURCE.json', json.dumps(source_record, indent=2)+'\n')
            else:
                z.write(bundle, 'repository.bundle')
                for name in files:
                    if name and (ROOT / name).is_file():
                        z.write(ROOT / name, 'source/' + name)
            for name in attachments:
                z.write(ROOT/name, 'source/'+name)
            for name in build_files:
                z.write(ROOT/name, 'build-artifacts/'+name)
            z.writestr('RESTORE.txt',
                       'AI-generated recovery instructions.\nCommit: ' + commit + '\n' +
                       ('Restore source at the exact repository/commit/project_path in GITHUB_SOURCE.json.\n'
                        'Source hashes are included; no Git-backed source/history is duplicated here.\n'
                        if source_record is not None else 'git clone repository.bundle bitedj-nv\n') +
                       'Copy source/project_sources/*.pcapng and *.pdf into bitedj-nv/project_sources/.\n'
                       'Read CODEX_PROGRESS.md and NEXT_TASK.md before continuing.\n' +
                       ('source/ is a directly readable copy of the committed files.\n'
                        if source_record is None else
                        'source/ contains original capture inputs; project source is on GitHub.\n') +
                       'Large baseline images and dependency trees are rebuilt/downloaded.\n' +
                       ('The verified native binary/evidence is included in build-artifacts/work/.\n'
                        'Copy build-artifacts/work/ into bitedj-nv/work/ preserving relative paths.\n'
                        'Restore pinned vendor/bitedj and run scripts/apply_native.py, then verify\n'
                        'the saved native-build.json hashes; do not blindly restamp the restored binary.\n'
                        'Only rebuild if native sources changed or binary/evidence is absent.\n'
                        'When work/package/ is included, package_release.py rechecks its hashes\n'
                        'against current sources before reusing the validated updater.\n'
                        if build_files else '') +
                       'End AI-generated recovery instructions.\n')
    print(OUT)
    print('sha256=' + hashlib.sha256(OUT.read_bytes()).hexdigest())
    print('bytes=' + str(OUT.stat().st_size))


if __name__ == '__main__':
    main()
