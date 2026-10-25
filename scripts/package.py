#!/usr/bin/env python3
"""Package native executables and complete corresponding source archives."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ('README.md', 'LICENSE', 'release.json', 'install.sh', 'install-online.sh',
         'uninstall.sh', 'build-from-source.sh', 'build-offline.sh')


def skeleton(path):
    path.mkdir(parents=True, exist_ok=False)
    for name in FILES:
        shutil.copy2(ROOT / name, path / name)
    for name in ('scripts', 'patches', 'shaders', 'tests'):
        shutil.copytree(ROOT / name, path / name, ignore=shutil.ignore_patterns('__pycache__'))
    (path / 'assets').mkdir()
    shutil.copy2(ROOT / 'assets/screenshot.png', path / 'assets/screenshot.png')


def archive(path, destination):
    with tarfile.open(destination, 'w:gz', compresslevel=6) as stream:
        stream.add(path, arcname='cosmic-crystal')
    print(destination.name, flush=True)


def binaries(stage, dist, platform, version):
    source = ROOT / 'build/release' / (platform + '-' + version)
    manifest = json.loads((source / 'manifest.json').read_text())
    for name, checksum in manifest['sha256'].items():
        p = source / 'bin' / name if '/' not in name else source / name
        assert hashlib.sha256(p.read_bytes()).hexdigest() == checksum, str(p)
    target = stage / (platform + '-' + version)
    skeleton(target)
    shutil.copytree(source, target / 'build')
    archive(target, dist / f'cosmic-crystal-{platform}-cosmic-{version}-x86_64.tar.gz')


def sources(stage, dist, version):
    target = stage / ('source-' + version)
    skeleton(target)
    (target / 'source-bundle.json').write_text(json.dumps({'cosmic_version': version}) + '\n')
    for kind in ('comp', 'settings'):
        source = ROOT / 'build/sources/0.8.0' / version / kind
        shutil.copytree(source, target / 'sources' / kind,
                        ignore=shutil.ignore_patterns('.git', '.cargo', 'target', '__pycache__'))
        vendor = ROOT / 'build/source-vendor' / version / kind
        config_file = vendor.with_suffix('.toml')
        if not config_file.exists() or not config_file.read_text().strip():
            vendor.parent.mkdir(parents=True, exist_ok=True)
            temporary_config = config_file.with_suffix('.tmp')
            with temporary_config.open('w') as output:
                subprocess.run(['cargo', 'vendor', '--locked', '--versioned-dirs', str(vendor)],
                               cwd=source, stdout=output, check=True)
            temporary_config.replace(config_file)
        shutil.copytree(vendor, target / 'vendor' / kind)
        config = re.sub(r'(?m)^directory = .*$', 'directory = "@VENDOR@"', config_file.read_text())
        (target / 'vendor' / (kind + '.toml')).write_text(config)
    archive(target, dist / f'cosmic-crystal-sources-cosmic-{version}.tar.gz')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--binaries-only', action='store_true')
    group.add_argument('--sources-only', action='store_true')
    args = parser.parse_args()
    stage_root = ROOT / 'build/packages'
    stage_root.mkdir(exist_ok=True)
    # Each run owns a new staging directory; existing archives remain available.
    import tempfile
    stage = Path(tempfile.mkdtemp(prefix='package-', dir=stage_root))
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    for version in ('1.10.0', '1.11.0'):
        if not args.sources_only:
            for platform in ('arch', 'fedora', 'ubuntu'):
                binaries(stage, dist, platform, version)
        if not args.binaries_only:
            sources(stage, dist, version)
    (dist / 'SHA256SUMS').write_text(''.join(
        hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n'
        for p in sorted(dist.iterdir()) if p.is_file() and p.name != 'SHA256SUMS'))


if __name__ == '__main__':
    main()
