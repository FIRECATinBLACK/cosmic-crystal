import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import install
import system_packages


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='crystal tests ')
        self.root = Path(self.tmp.name)
        self.build = self.root / 'build'
        self.data, self.state = self.root / 'data', self.root / 'state'
        self.bindir, self.config = self.root / 'bin', self.root / 'config'
        (self.build / 'bin').mkdir(parents=True)
        self.bindir.mkdir()
        hashes = {}
        for name in install.PROGRAMS:
            p = self.build / 'bin' / name
            p.write_text('#!/bin/sh\nprintf "Crystal executable\\n"\n')
            p.chmod(0o755)
            hashes[name] = hashlib.sha256(p.read_bytes()).hexdigest()
        self.manifest = {'name': 'cosmic-crystal', 'version': '0.8.0',
                         'cosmic_version': '1.10.0', 'platform': 'arch',
                         'architecture': 'x86_64', 'minimum_glibc': '2.42', 'sha256': hashes}
        (self.build / 'manifest.json').write_text(json.dumps(self.manifest))
        self.original = b'#!/bin/sh\nprintf "Previous Settings\\n"\n'
        (self.bindir / 'cosmic-settings').write_bytes(self.original)
        (self.bindir / 'cosmic-settings').chmod(0o750)
        self.packages = {name: name + ' 1:1.10.0-1' for name in install.PROGRAMS}

    def tearDown(self):
        self.tmp.cleanup()

    def install(self):
        with patch.object(install, 'validate_platform', return_value=(self.packages, 'pacman')):
            install.install(self.build, self.data, self.state, self.bindir, self.config)

    def uninstall(self):
        install.uninstall(self.data, self.state, self.bindir, self.config)

    def test_install_update_remove_restores_launchers_and_keeps_user_choices(self):
        category = self.config / 'com.system76.CosmicTheme.Dark/v2/frosted_panel'
        category.parent.mkdir(parents=True)
        category.write_bytes(b'false')
        self.install()
        self.assertEqual(category.read_text().strip(), 'true')
        thickness = self.config / 'com.system76.CosmicComp/v1/crystal_thickness'
        self.assertEqual(thickness.read_text().strip(), '40')
        thickness.write_text('83')
        self.install()
        self.assertEqual(thickness.read_text(), '83')
        self.assertEqual((self.state / 'previous/cosmic-settings').read_bytes(), self.original)
        self.uninstall()
        self.assertEqual((self.bindir / 'cosmic-settings').read_bytes(), self.original)
        self.assertEqual((self.bindir / 'cosmic-settings').stat().st_mode & 0o777, 0o750)
        self.assertFalse((self.bindir / 'cosmic-comp').exists())
        self.assertEqual(category.read_bytes(), b'false')
        self.assertEqual(thickness.read_text(), '83')
        self.assertFalse((self.state / 'installation.json').exists())

    def test_native_package_upgrade_runs_previous_program(self):
        self.install()
        mockbin = self.root / 'mockbin'
        mockbin.mkdir()
        p = mockbin / 'pacman'
        p.write_text('#!/bin/sh\nprintf "cosmic-comp 1:1.11.0-1\\n"\n')
        p.chmod(0o755)
        output = subprocess.check_output([str(self.bindir / 'cosmic-settings')],
                  env=dict(os.environ, PATH=str(mockbin) + ':/usr/bin'), text=True)
        self.assertEqual(output, 'Previous Settings\n')

    def test_disable_override_uses_previous_launcher(self):
        self.install()
        output = subprocess.check_output([str(self.bindir / 'cosmic-settings')],
                  env=dict(os.environ, COSMIC_CRYSTAL_DISABLE='1'), text=True)
        self.assertEqual(output, 'Previous Settings\n')

    def test_relative_symlink_is_restored(self):
        p = self.bindir / 'cosmic-settings'
        p.rename(self.bindir / 'original-settings')
        p.symlink_to('original-settings')
        self.install()
        self.assertEqual(subprocess.check_output([str(self.state / 'previous/cosmic-settings')], text=True), 'Previous Settings\n')
        self.uninstall()
        self.assertEqual(os.readlink(p), 'original-settings')

    def test_checksum_failure_leaves_launchers_and_configuration_untouched(self):
        (self.build / 'bin/cosmic-comp').write_text('broken')
        with self.assertRaisesRegex(RuntimeError, 'Checksum mismatch'):
            self.install()
        self.assertEqual((self.bindir / 'cosmic-settings').read_bytes(), self.original)
        self.assertFalse(self.config.exists())

    def test_bundled_library_path_is_private_and_preserves_spaces(self):
        program = self.build / 'bin/cosmic-comp'
        program.write_text('#!/bin/sh\nprintf "%s" "$LD_LIBRARY_PATH"\n')
        library = self.build / 'lib/libdisplay-info.so.2'
        library.parent.mkdir()
        library.write_bytes(b'library fixture')
        self.manifest['library_files'] = ['lib/libdisplay-info.so.2']
        self.manifest['sha256']['cosmic-comp'] = hashlib.sha256(program.read_bytes()).hexdigest()
        self.manifest['sha256']['lib/libdisplay-info.so.2'] = hashlib.sha256(library.read_bytes()).hexdigest()
        (self.build / 'manifest.json').write_text(json.dumps(self.manifest))
        self.install()
        record = json.loads((self.state / 'installation.json').read_text())
        mockbin = self.root / 'mockbin'
        mockbin.mkdir()
        command = mockbin / 'pacman'
        command.write_text('#!/bin/sh\nprintf "%s 1:1.10.0-1\\n" "$2"\n')
        command.chmod(0o755)
        output = subprocess.check_output([str(self.bindir / 'cosmic-comp')],
            env=dict(os.environ, PATH=str(mockbin) + ':/usr/bin', LD_LIBRARY_PATH='/existing path'), text=True)
        self.assertEqual(output, str(Path(record['destination']) / 'lib') + ':/existing path')

    def test_corrupt_bundled_library_is_rejected_before_installation(self):
        library = self.build / 'lib/libdisplay-info.so.2'
        library.parent.mkdir()
        library.write_bytes(b'corrupt')
        self.manifest['library_files'] = ['lib/libdisplay-info.so.2']
        self.manifest['sha256']['lib/libdisplay-info.so.2'] = '0' * 64
        (self.build / 'manifest.json').write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(RuntimeError, 'Checksum mismatch'):
            self.install()
        self.assertEqual((self.bindir / 'cosmic-settings').read_bytes(), self.original)

    def test_failed_second_write_rolls_back(self):
        original = install.atomic_write
        failed = False

        def fail_once(path, *args):
            nonlocal failed
            if path == self.bindir / 'cosmic-settings' and not failed:
                failed = True
                raise OSError('simulated full disk')
            return original(path, *args)

        with patch.object(install, 'atomic_write', side_effect=fail_once):
            with self.assertRaises(OSError):
                self.install()
        self.assertEqual((self.bindir / 'cosmic-settings').read_bytes(), self.original)
        self.assertFalse((self.bindir / 'cosmic-comp').exists())
        self.install()

    def test_modified_launcher_is_preserved_on_remove_and_update(self):
        self.install()
        p = self.bindir / 'cosmic-settings'
        p.write_text('#!/bin/sh\n# A newer launcher\n')
        self.uninstall()
        self.assertEqual(p.read_text(), '#!/bin/sh\n# A newer launcher\n')
        self.assertTrue((self.state / 'installation.json').exists())
        with self.assertRaisesRegex(RuntimeError, 'changed after installation'):
            self.install()

    def test_incompatible_prototype_record_is_not_overwritten(self):
        self.state.mkdir()
        (self.state / 'installation.json').write_text('{"version": "0.8.0"}')
        with self.assertRaisesRegex(RuntimeError, 'local prototype'):
            self.install()
        self.assertEqual((self.bindir / 'cosmic-settings').read_bytes(), self.original)

    def test_archive_paths_and_symlinks_are_rejected(self):
        for name, kind in [('../escape', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE),
                           ('symlink', tarfile.SYMTYPE)]:
            archive = self.root / 'unsafe.tar.gz'
            with tarfile.open(archive, 'w:gz') as stream:
                info = tarfile.TarInfo(name)
                info.type = kind
                if kind == tarfile.SYMTYPE:
                    info.linkname = '/etc/passwd'
                stream.addfile(info, io.BytesIO(b''))
            with self.assertRaisesRegex(RuntimeError, 'Unsafe archive'):
                install.extract(archive, self.root / 'unpacked')

    def test_mismatched_cosmic_packages_and_old_runtime_are_rejected(self):
        with patch.object(system_packages, 'distribution', return_value='arch'), \
             patch.object(install.platform, 'machine', return_value='x86_64'), \
             patch.object(install.platform, 'libc_ver', return_value=('glibc', '2.41')):
            with self.assertRaisesRegex(RuntimeError, 'glibc'):
                install.validate_platform(self.manifest)
        with patch.object(system_packages, 'distribution', return_value='arch'), \
             patch.object(install.platform, 'machine', return_value='x86_64'), \
             patch.object(install.platform, 'libc_ver', return_value=('glibc', '2.44')), \
             patch.object(system_packages, 'query', return_value='cosmic-comp 1:1.11.0-1'):
            with self.assertRaises(RuntimeError):
                install.validate_platform(self.manifest)


class PackageVersionTests(unittest.TestCase):
    def test_arch_and_fedora_versions(self):
        for text in ['cosmic-comp 1:1.10.0-1', 'cosmic-comp 0:1.11.0-2.fc43.x86_64']:
            self.assertIn(system_packages.upstream_version('cosmic-comp', text), system_packages.SUPPORTED)

    def test_system76_package_versions_match_the_pinned_epoch(self):
        self.assertEqual(system_packages.upstream_version('cosmic-comp',
            'cosmic-comp 0.1~1792508925~24.04~8cb1802'), '1.11.0')
        self.assertEqual(system_packages.upstream_version('cosmic-comp',
            'cosmic-comp 0.1~1791000000~24.04~41497b4'), '1.10.0')
        self.assertEqual(system_packages.upstream_version('cosmic-settings',
            'cosmic-settings 1.11.0~1792526230~24.04~f1d00fc'), '1.11.0')

    def test_pop_uses_ubuntu_archives_and_dpkg(self):
        with patch.object(system_packages.platform, 'freedesktop_os_release', return_value={'ID': 'pop'}):
            self.assertEqual(system_packages.distribution(), 'ubuntu')
            self.assertEqual(system_packages.manager(), 'dpkg')

    def test_mixed_native_versions_are_rejected(self):
        def query(name, backend):
            return name + (' 1:1.10.0-1' if name == 'cosmic-comp' else ' 1:1.11.0-1')
        with patch.object(system_packages, 'query', side_effect=query):
            with self.assertRaises(RuntimeError):
                system_packages.installed_version('pacman')


if __name__ == '__main__':
    unittest.main()
