from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from manette import local_apps, system
from manette.app import Window
from manette.apps_page import AppsPage


class SpaceTests(unittest.TestCase):
    def test_low_space_and_duplicate_filesystems(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(system.shutil, 'disk_usage', return_value=SimpleNamespace(free=3 * 1024**3)):
            warnings = system.space_warnings([directory, Path(directory) / 'not-created-yet'])
            self.assertEqual(len(warnings), 1)
            self.assertIn('3,0 Gio', warnings[0])

    def test_enough_space_and_unknown_space(self):
        with patch.object(system.shutil, 'disk_usage', return_value=SimpleNamespace(free=5 * 1024**3)):
            self.assertEqual(system.space_warnings(['/']), [])
        with patch.object(system.shutil, 'disk_usage', side_effect=OSError('unavailable')):
            self.assertIn('impossible', system.space_warnings(['/'])[0])

    def test_low_space_requires_confirmation_before_start(self):
        window = Mock()
        window.console.busy = False
        with patch('manette.app.system.space_warnings', return_value=['/ : 3 Gio libres']):
            Window.run(window, ['apt-get'], 'Mise à jour', space_paths=['/'])
        window.console.run.assert_not_called()
        window.confirm.assert_called_once()
        window.confirm.call_args.args[3]()
        window.run.assert_called_once_with(['apt-get'], 'Mise à jour', None, None)

    def test_busy_console_does_not_launch_another_command(self):
        window = Mock()
        window.console.busy = True
        window.console.title = 'Tout mettre à jour'
        Window.run(window, ['apt'], 'Vérifier')
        window.console.run.assert_not_called()
        self.assertIn("n'a pas été lancé", window.confirm.call_args.args[1])


class LocalApplicationTests(unittest.TestCase):
    def test_real_deb_metadata_without_installing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = root / 'package' / 'DEBIAN'
            control.mkdir(parents=True)
            (control / 'control').write_text('Package: manette-test\nVersion: 1.0\nArchitecture: all\n'
                                           'Maintainer: Test <test@example.test>\nDescription: Test only\n')
            target = root / 'test avec espaces; rien.deb'
            subprocess.run(['dpkg-deb', '--build', '--root-owner-group', str(control.parent), str(target)],
                           check=True, capture_output=True)
            download = local_apps.inspect_file(str(target))
            self.assertIn('manette-test · 1.0 · all', download.description)
            self.assertEqual(download.command.argv[-1], str(target))
            self.assertIn('--no-remove', download.command.argv)

    def test_invalid_files_are_not_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(local_apps.subprocess, 'Popen') as launch:
                for name in ('fake.AppImage', 'unsupported.exe'):
                    path = root / name
                    path.write_text('not an application')
                    with self.subTest(name=name), self.assertRaises(ValueError):
                        local_apps.inspect_file(str(path))
                launch.assert_not_called()
            invalid_deb = root / 'invalid.deb'
            invalid_deb.write_text('not a package')
            with self.assertRaisesRegex(ValueError, 'pas un paquet'):
                local_apps.inspect_file(str(invalid_deb))

    def test_appimage_inspection_does_not_make_it_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'app.AppImage'
            path.write_bytes(b'\x7fELF\x02\x01\x01\x00AI\x02')
            path.chmod(0o600)
            download = local_apps.inspect_file(str(path))
            self.assertEqual(download.kind, 'appimage')
            self.assertFalse(path.stat().st_mode & stat.S_IXUSR)
            with patch.object(local_apps.subprocess, 'Popen') as launch:
                launch.return_value.wait.side_effect = subprocess.TimeoutExpired('app', 2)
                local_apps.launch_appimage(download)
                self.assertEqual(launch.call_args.args[0], [str(path)])
                self.assertTrue(path.stat().st_mode & stat.S_IXUSR)
                self.assertFalse(path.stat().st_mode & stat.S_IXGRP)

    def test_appimage_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'app.AppImage'
            path.write_bytes(b'\x7fELF\x02\x01\x01\x00AI\x02')
            download = local_apps.inspect_file(str(path))
            with patch.object(local_apps.subprocess, 'Popen') as launch:
                launch.return_value.wait.return_value = 1
                with self.assertRaisesRegex(ValueError, 'code 1'):
                    local_apps.launch_appimage(download)

    def test_flatpak_install_is_scoped_to_user(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'app.flatpakref'
            path.write_text('[Flatpak Ref]\nName=org.example.App\n')
            with patch.object(local_apps.shutil, 'which', return_value=None), self.assertRaises(ValueError):
                local_apps.inspect_file(str(path))
            with patch.object(local_apps.shutil, 'which', return_value='/usr/bin/flatpak'):
                download = local_apps.inspect_file(str(path))
            self.assertEqual(download.command.argv, ['flatpak', 'install', '--user', '-y', str(path)])

    def test_file_confirmation_does_not_start_installation(self):
        page = Mock()
        download = local_apps.Download(Path('/tmp/example.deb'), 'deb', 'Example')
        AppsPage._confirm_download(page, download, None)
        page._open_download.assert_not_called()
        page.window.confirm.call_args.args[3]()
        page._open_download.assert_called_once_with(download)

    def test_installation_uses_console_and_space_check(self):
        page = Mock()
        command = local_apps.Command(['apt-get', 'install', '/tmp/example.deb'], 'apt-get install …')
        download = local_apps.Download(Path('/tmp/example.deb'), 'deb', 'Example', command)
        AppsPage._open_download(page, download)
        self.assertEqual(page.window.run.call_args.kwargs['space_paths'], ['/', '/var/cache/apt/archives'])
        page.window.run.call_args.kwargs['on_done'](True)
        page._after_install.assert_called_once()


if __name__ == '__main__':
    unittest.main()


# Les tests historiques vérifient les messages de référence français.
def setUpModule():
    global _locale_patch
    _locale_patch = patch("manette.i18n.language", return_value="fr")
    _locale_patch.start()


def tearDownModule():
    _locale_patch.stop()
