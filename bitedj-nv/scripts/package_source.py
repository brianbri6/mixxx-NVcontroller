#!/usr/bin/env python3
"""AI-generated documentation.
Package the committed Pi integration source without native binaries or images.
End AI-generated documentation.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
import tarfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'dist/BiteDJ_Pi4_NV_v0_5_8_Source_2026-10-20.zip'
PREFIX = 'BiteDJ_Pi4_NV_v0_5_8_Source/'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit('Refusing to overwrite a source ZIP: ' + str(output))
    if git('status', '--porcelain', '--', '.'):
        raise SystemExit('Commit project changes before packaging the source.')
    commit = git('rev-parse', 'HEAD').decode().strip()
    project = git('rev-parse', '--show-prefix').decode().strip().rstrip('/')
    treeish = commit + (':' + project if project else '')
    epoch = int(git('show', '-s', '--format=%ct', commit))
    date = time.gmtime(max(epoch, 315532800))[:6]
    remote = subprocess.run(['git', 'remote', 'get-url', 'origin'], cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    origin = {
        'kind': 'source-only', 'runtime_version': '0.5.8 experimental',
        'repository': remote.stdout.decode().strip() or None,
        'commit': commit, 'project_path': project or '.',
        'project_tree': git('rev-parse', treeish if project else commit + '^{tree}').decode().strip(),
        'upstream_repository': 'https://github.com/TeamDeckshark/bitedj.git',
        'upstream_commit': '78074e05c8bf99ede6fedd755aa68bd222ba343c',
        'instructions': 'SOURCE_README.md',
    }
    entries = {}
    repository_root = git('rev-parse', '--show-toplevel').decode().strip()
    source_tar = git('-C', repository_root, 'archive', '--format=tar', treeish)
    with tarfile.open(fileobj=io.BytesIO(source_tar)) as archive:
        for item in archive:
            if item.isdir():
                continue
            if not item.isfile() or '..' in Path(item.name).parts or Path(item.name).is_absolute():
                raise SystemExit('Unsupported source archive entry: ' + item.name)
            entries[item.name] = (archive.extractfile(item).read(), item.mode)
    tracked = {name for name in git('ls-files', '-z', '--', '.').decode().split('\0') if name}
    if not tracked or set(entries) != tracked:
        raise SystemExit('Source archive does not match all tracked project files')
    origin['source_files'] = len(entries)
    entries['SOURCE_ORIGIN.json'] = ((json.dumps(origin, indent=2) + '\n').encode(), 0o644)
    hashes = {name: hashlib.sha256(data).hexdigest() for name, (data, _) in entries.items()}
    entries['SOURCE_SHA256SUMS.txt'] = (
        ''.join(digest + '  ' + name + '\n' for name, digest in sorted(hashes.items())).encode(), 0o644)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, (data, mode) in sorted(entries.items()):
            info = zipfile.ZipInfo(PREFIX + name, date)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None or len(archive.namelist()) != len(entries):
            raise SystemExit('Source ZIP integrity check failed')
        for name, (expected, _) in entries.items():
            if archive.read(PREFIX + name) != expected:
                raise SystemExit('Source ZIP content mismatch: ' + name)
    print(json.dumps({'path': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                      'bytes': output.stat().st_size, 'source_files': origin['source_files'],
                      'commit': commit, 'project_path': origin['project_path'],
                      'verified': True}, indent=2))


if __name__ == '__main__':
    main()
