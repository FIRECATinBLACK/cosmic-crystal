#!/usr/bin/env python3
"""Install and remove standalone COSMIC Crystal user overrides."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

import system_packages

ROOT = Path(__file__).resolve().parents[1]
PROGRAMS = ('cosmic-comp', 'cosmic-settings')
MARKER = '# Managed by cosmic-crystal\n'


def xdg(variable, fallback):
    value = os.environ.get(variable)
    return Path(value) if value and Path(value).is_absolute() else Path.home() / fallback


def paths():
    return (xdg('XDG_DATA_HOME', '.local/share') / 'cosmic-crystal',
            xdg('XDG_STATE_HOME', '.local/state') / 'cosmic-crystal',
            Path.home() / '.local/bin', xdg('XDG_CONFIG_HOME', '.config') / 'cosmic')


def lexists(path):
    return path.exists() or path.is_symlink()


def atomic_write(path, text, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(text.encode() if isinstance(text, str) else text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def snapshot(path):
    if path.is_symlink():
        return {'symlink': os.readlink(path)}
    if path.exists():
        return {'data': base64.b64encode(path.read_bytes()).decode(),
                'mode': path.stat().st_mode & 0o777}
    return None


def restore(path, original):
    if original is None:
        path.unlink(missing_ok=True)
    elif 'symlink' in original:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name('.' + path.name + '.restore')
        if lexists(temporary):
            temporary.unlink()
        temporary.symlink_to(original['symlink'])
        os.replace(temporary, path)
    else:
        atomic_write(path, base64.b64decode(original['data']), original['mode'])


def launcher(program, binary, fallback, packages, backend, library_dir=None):
    q = shlex.quote
    checks = ' && '.join('[ "$(' + shlex.join(system_packages.query_command(name, backend)) +
                         ' 2>/dev/null)" = ' + q(value) + ' ]'
                         for name, value in sorted(packages.items()))
    invocation = q(str(binary))
    if library_dir:
        invocation = 'env LD_LIBRARY_PATH=' + q(str(library_dir)) + '${LD_LIBRARY_PATH:+:"$LD_LIBRARY_PATH"} ' + invocation
    return ('#!/bin/sh\n' + MARKER +
            f'if [ "${{COSMIC_CRYSTAL_DISABLE:-0}}" != 1 ] && {checks} && '
            f'[ -x {q(str(binary))} ] && {invocation} --version >/dev/null 2>&1; then\n'
            f'    exec {invocation} "$@"\nfi\nexec {q(str(fallback))} "$@"\n')


def validate_platform(manifest):
    distro = system_packages.distribution()
    if manifest['platform'] != distro or manifest['architecture'] != platform.machine():
        raise RuntimeError('This archive targets another distribution or architecture')
    libc, version = platform.libc_ver()
    if libc != 'glibc' or tuple(map(int, version.split('.'))) < tuple(map(int, manifest['minimum_glibc'].split('.'))):
        raise RuntimeError('This archive needs glibc ' + manifest['minimum_glibc'] + '+; build from source instead')
    backend = system_packages.manager(distro)
    packages = {name: system_packages.query(name, backend) for name in PROGRAMS}
    if any(system_packages.upstream_version(name, value) != manifest['cosmic_version']
           for name, value in packages.items()):
        raise RuntimeError('Install matching COSMIC compositor and Settings packages first')
    return packages, backend


def owned(path, expected):
    return path.is_file() and not path.is_symlink() and path.read_bytes() == expected.encode()


def read_record(state):
    path = state / 'installation.json'
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    if record.get('schema') != 1:
        raise RuntimeError('Remove the local prototype with its original uninstaller before installing this release')
    return record


def defaults(config):
    comp = config / 'com.system76.CosmicComp/v1'
    changes = {comp / 'crystal_enabled': 'true\n'}
    for key, value in {'crystal_blur_amount': '70', 'crystal_everyday': 'true',
                       'crystal_thickness': '40', 'crystal_refraction': '150',
                       'crystal_density': '100'}.items():
        if not (comp / key).exists():
            changes[comp / key] = value + '\n'
    for mode in ('Dark', 'Light'):
        for suffix in ('', '.Builder'):
            for key in ('frosted_windows', 'frosted_panel', 'frosted_applets', 'frosted_system_interface'):
                changes[config / f'com.system76.CosmicTheme.{mode}{suffix}/v2' / key] = 'true\n'
    return changes


def install(build, data, state, bindir, config):
    manifest = json.loads((build / 'manifest.json').read_text())
    if manifest.get('name') != 'cosmic-crystal' or manifest['version'] != json.loads((ROOT / 'release.json').read_text())['version']:
        raise RuntimeError('This build does not belong to this Crystal release')
    packages, backend = validate_platform(manifest)
    libraries = manifest.get('library_files', [])
    for name in libraries:
        if len(Path(name).parts) != 2 or Path(name).parts[0] != 'lib' or '..' in Path(name).parts:
            raise RuntimeError('Invalid library archive path')
        if hashlib.sha256((build / name).read_bytes()).hexdigest() != manifest['sha256'][name]:
            raise RuntimeError('Checksum mismatch: ' + name)
    for name in PROGRAMS:
        binary = build / 'bin' / name
        if hashlib.sha256(binary.read_bytes()).hexdigest() != manifest['sha256'][name]:
            raise RuntimeError('Checksum mismatch: ' + name)
        env = dict(os.environ)
        if libraries and name == 'cosmic-comp':
            env['LD_LIBRARY_PATH'] = str(build / 'lib') + (':' + env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
        subprocess.run([str(binary), '--version'], env=env, check=True, capture_output=True, timeout=15)
    old = read_record(state)
    if old:
        for name in PROGRAMS:
            if not owned(bindir / name, old['shims'][name]):
                raise RuntimeError(f'{bindir / name} changed after installation; it has been preserved')
    stamp = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:12]
    destination = data / 'versions' / (manifest['version'] + '-' + stamp)
    destination.mkdir(parents=True, exist_ok=True)
    for name in list(PROGRAMS) + libraries:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != manifest['sha256'][name]:
                raise RuntimeError('An installed immutable executable was modified: ' + str(target))
        else:
            temporary = target.with_name('.' + target.name + '.new')
            source = build / 'bin' / name if name in PROGRAMS else build / name
            shutil.copy2(source, temporary)
            temporary.chmod(0o755 if name in PROGRAMS else 0o644)
            os.replace(temporary, target)
    previous = state / 'previous'
    if not old and previous.exists():
        raise RuntimeError('Existing launcher backups need review: ' + str(previous))
    record = json.loads(json.dumps(old)) if old else {
        'schema': 1, 'previous': {}, 'originals': {}, 'config': {}, 'shims': {}}
    changes = {} if old else defaults(config)
    originals = {bindir / name: snapshot(bindir / name) for name in PROGRAMS}
    originals.update({path: snapshot(path) for path in changes})
    record_path = state / 'installation.json'
    original_record = snapshot(record_path)
    try:
        if not old:
            previous.mkdir(parents=True)
            for name in PROGRAMS:
                path, backup = bindir / name, previous / name
                original = originals[path]
                record['originals'][name] = original
                if lexists(path):
                    if path.is_symlink():
                        backup.symlink_to(path.resolve())
                    else:
                        shutil.copy2(path, backup)
                    record['previous'][name] = str(backup)
                else:
                    record['previous'][name] = None
        for name in PROGRAMS:
            fallback = Path(record['previous'][name] or ('/usr/bin/' + name))
            lib = destination / 'lib' if libraries and name == 'cosmic-comp' else None
            record['shims'][name] = launcher(name, destination / name, fallback, packages, backend, lib)
            atomic_write(bindir / name, record['shims'][name], 0o755)
        for path, value in changes.items():
            record['config'][str(path)] = {'original': originals[path], 'installed': value}
            atomic_write(path, value, 0o600)
        record.update(version=manifest['version'], cosmic_version=manifest['cosmic_version'],
                      destination=str(destination), bindir=str(bindir), packages=packages, backend=backend)
        atomic_write(record_path, json.dumps(record, indent=2) + '\n')
    except Exception:
        for path, original in originals.items():
            restore(path, original)
        restore(record_path, original_record)
        if not old:
            shutil.rmtree(previous, ignore_errors=True)
        raise
    print('Installed COSMIC Crystal ' + manifest['version'] + '. Log out and back in once.')
    print('Open Settings → Desktop → Appearance → COSMIC Crystal.')


def uninstall(data, state, bindir, config):
    record = read_record(state)
    if record is None:
        print('No COSMIC Crystal installation found.')
        return
    bindir = Path(record['bindir'])
    changed = [str(bindir / name) for name in PROGRAMS
               if not owned(bindir / name, record['shims'][name])]
    if changed:
        print('Preserved newer or modified launchers: ' + ', '.join(changed))
        print('Installation records and backups retained at ' + str(state))
        return
    for name in PROGRAMS:
        restore(bindir / name, record['originals'][name])
    for filename, entry in record['config'].items():
        path = Path(filename)
        if path.is_file() and not path.is_symlink() and path.read_bytes() == entry['installed'].encode():
            restore(path, entry['original'])
    (state / 'installation.json').unlink()
    shutil.rmtree(state / 'previous')
    print('Previous launchers and unchanged preferences restored. Log out and back in.')


def download(url, path):
    print('Downloading ' + url, flush=True)
    request = urllib.request.Request(url, headers={'User-Agent': 'cosmic-crystal-installer'})
    with urllib.request.urlopen(request, timeout=120) as response, path.open('wb') as stream:
        shutil.copyfileobj(response, stream)


def extract(archive, directory):
    with tarfile.open(archive, 'r:gz') as stream:
        for entry in stream.getmembers():
            path = Path(entry.name)
            if path.is_absolute() or '..' in path.parts or not (entry.isdir() or entry.isfile()):
                raise RuntimeError('Unsafe archive entry: ' + entry.name)
        stream.extractall(directory, filter='data')


def prebuilt(temporary):
    details = json.loads((ROOT / 'release.json').read_text())
    distro = system_packages.distribution()
    version = system_packages.installed_version()
    name = f'cosmic-crystal-{distro}-cosmic-{version}-{platform.machine()}.tar.gz'
    base = f'https://github.com/{details["repository"]}/releases/download/v{details["version"]}/'
    sums, archive = temporary / 'SHA256SUMS', temporary / name
    download(base + 'SHA256SUMS', sums)
    hashes = {line.split()[1].lstrip('*'): line.split()[0] for line in sums.read_text().splitlines() if line.strip()}
    if name not in hashes:
        raise RuntimeError('No prebuilt archive for this system; use ./build-from-source.sh')
    download(base + name, archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != hashes[name]:
        raise RuntimeError('Downloaded archive checksum mismatch')
    extract(archive, temporary / 'unpacked')
    return temporary / 'unpacked/cosmic-crystal/build'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'uninstall'))
    parser.add_argument('--build-dir', type=Path)
    parser.add_argument('--from-source', action='store_true')
    parser.add_argument('--build-only', action='store_true')
    parser.add_argument('--cosmic-version', choices=system_packages.SUPPORTED)
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--work-dir', type=Path)
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Run as your desktop user, without sudo')
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    data, state, bindir, config = paths()
    state.parent.mkdir(parents=True, exist_ok=True)
    try:
        with (state.parent / '.cosmic-crystal-install.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if args.action == 'uninstall':
                uninstall(data, state, bindir, config)
            elif args.from_source or args.build_only:
                import build
                version = args.cosmic_version or system_packages.installed_version()
                output = (args.build_dir or ROOT / 'build').resolve()
                work = (args.work_dir or ROOT / 'build/sources' / build.release()['version'] / version).resolve()
                build.build(work, output, version, args.jobs)
                if not args.build_only:
                    install(output, data, state, bindir, config)
            elif args.build_dir:
                install(args.build_dir.resolve(), data, state, bindir, config)
            elif (ROOT / 'build/manifest.json').exists():
                install(ROOT / 'build', data, state, bindir, config)
            else:
                with tempfile.TemporaryDirectory(prefix='cosmic-crystal-') as directory:
                    install(prebuilt(Path(directory)), data, state, bindir, config)
    except (OSError, ValueError, KeyError, RuntimeError, tarfile.TarError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
