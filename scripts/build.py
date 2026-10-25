#!/usr/bin/env python3
"""Build the standalone Crystal compositor and Settings from pinned sources."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess

import system_packages

ROOT = Path(__file__).resolve().parents[1]
PROGRAMS = ('cosmic-comp', 'cosmic-settings')


def run(*command, **kwargs):
    subprocess.run(command, check=True, **kwargs)


def release():
    return json.loads((ROOT / 'release.json').read_text())


def prepare(work, version, offline=False):
    details = release()
    sources = {}
    for kind in ('comp', 'settings'):
        source = work / kind
        pin = details['source_versions'][version][kind]
        patch = ROOT / 'patches' / f'cosmic-{kind}-crystal.patch'
        expected = {'commit': pin, 'release': details['version'], 'build_schema': 1,
                    'patch_sha256': hashlib.sha256(patch.read_bytes()).hexdigest()}
        marker = source / '.crystal-source.json'
        if marker.exists():
            if json.loads(marker.read_text()) != expected:
                raise RuntimeError(f'Source options changed: choose a fresh --work-dir for {source}')
            sources[kind] = source
            continue
        if not (source / '.git').exists():
            if offline:
                raise RuntimeError(f'Missing offline source: {source}')
            source.mkdir(parents=True, exist_ok=True)
            run('git', 'init', '--quiet', str(source))
            run('git', 'fetch', '--depth', '1', details['upstreams'][kind], pin, cwd=source)
            run('git', 'checkout', '--detach', 'FETCH_HEAD', cwd=source)
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
        if head != pin:
            raise RuntimeError(f'Unexpected upstream revision: {source}')
        run('git', 'apply', '--check', str(patch), cwd=source)
        run('git', 'apply', str(patch), cwd=source)
        # Keep version metadata reproducible in the complete source archive too.
        if kind == 'comp':
            (source / 'build.rs').write_text(
                '// SPDX-License-Identifier: GPL-3.0-only\n'
                'fn main() {\n'
                '    println!("cargo:rerun-if-env-changed=CRYSTAL_UPSTREAM_COMMIT");\n'
                f'    let pin = std::env::var("CRYSTAL_UPSTREAM_COMMIT").unwrap_or_else(|_| "{pin}".to_string());\n'
                '    println!("cargo:rustc-env=GIT_HASH={}", pin);\n}\n')
        else:
            main = source / 'cosmic-settings/src/main.rs'
            text, count = re.subn(
                r'#\[command\(author, version, about, long_about = None\)\]',
                f'#[command(author, version = "{version} + COSMIC Crystal {details["version"]}", about, long_about = None)]',
                main.read_text(), count=1)
            if count != 1:
                raise RuntimeError('Cannot set the Settings release version')
            main.write_text(text)
        marker.write_text(json.dumps(expected, indent=2) + '\n')
        sources[kind] = source
    return sources


def manifest(output, version, distro):
    library_files = []
    if distro in ('fedora', 'ubuntu'):
        # Supported distributions ship different SONAMEs. Carry the MIT-licensed
        # parser used by this build; graphics drivers remain system supplied.
        linked = subprocess.check_output(['ldd', str(output / 'bin/cosmic-comp')], text=True)
        match = re.search(r'(libdisplay-info\.so\.\d+) => (\S+)', linked)
        if not match:
            raise RuntimeError('Cannot find the linked libdisplay-info runtime')
        (output / 'lib').mkdir(exist_ok=True)
        shutil.copy2(match[2], output / 'lib' / match[1])
        license_file = Path('/usr/share/licenses/libdisplay-info/LICENSE')
        if distro == 'ubuntu':
            license_file = Path('/usr/share/doc') / ('libdisplay-info' + match[1].split('.so.')[-1]) / 'copyright'
        if not license_file.exists():
            raise RuntimeError('Missing libdisplay-info license')
        shutil.copy2(license_file, output / 'lib/LICENSE.libdisplay-info')
        library_files = ['lib/' + match[1], 'lib/LICENSE.libdisplay-info']
    result = {'name': 'cosmic-crystal', 'version': release()['version'],
              'cosmic_version': version, 'platform': distro,
              'architecture': platform.machine(), 'minimum_glibc': platform.libc_ver()[1],
              'library_files': library_files,
              'sha256': {name: hashlib.sha256((output / 'bin' / name).read_bytes()).hexdigest()
                         for name in PROGRAMS}}
    for name in library_files:
        result['sha256'][name] = hashlib.sha256((output / name).read_bytes()).hexdigest()
    (output / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def compile_sources(sources, output, version, jobs=4, offline=False):
    (output / 'bin').mkdir(parents=True, exist_ok=True)
    for kind, program in zip(('comp', 'settings'), PROGRAMS):
        source = sources[kind]
        target = Path(os.environ.get(f'CRYSTAL_{kind.upper()}_TARGET',
                                    ROOT / 'build' / ('target-' + kind + '-' + version))).resolve()
        env = dict(os.environ, CARGO_TARGET_DIR=str(target),
                   CRYSTAL_UPSTREAM_COMMIT=release()['source_versions'][version]['comp'])
        env.setdefault('CARGO_PROFILE_RELEASE_LTO', 'thin')
        command = ['cargo', 'build', '--release', '--locked', '-j', str(jobs)]
        command += ['--bin', program] if kind == 'comp' else ['-p', program]
        if offline:
            command.append('--offline')
        run(*command, cwd=source, env=env)
        temporary = output / 'bin' / ('.' + program + '.new')
        shutil.copy2(target / 'release' / program, temporary)
        run('strip', '--strip-unneeded', str(temporary))
        os.replace(temporary, output / 'bin' / program)
        result = subprocess.check_output([str(output / 'bin' / program), '--version'], text=True, timeout=15)
        expected = release()['source_versions'][version]['comp'] if kind == 'comp' else version
        if expected not in result:
            raise RuntimeError('Stale build metadata: use a fresh target directory for ' + program)
        print(result.strip(), flush=True)
    manifest(output, version, system_packages.distribution())
    return output


def build(work, output, version, jobs=4, offline=False):
    return compile_sources(prepare(work, version, offline), output, version, jobs, offline)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cosmic-version', choices=system_packages.SUPPORTED)
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--work-dir', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'build')
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    version = args.cosmic_version or system_packages.installed_version()
    work = args.work_dir or ROOT / 'build/sources' / release()['version'] / version
    try:
        build(work.resolve(), args.output.resolve(), version, args.jobs, args.offline)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + '\n')
    print('Build ready. Run ./install.sh --build-dir ' + str(args.output.resolve()))


if __name__ == '__main__':
    main()
