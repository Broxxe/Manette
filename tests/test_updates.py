import fcntl
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from manette import preferences, updater
from manette.settings_dialog import automatic_check


REVISION = 'a' * 40
NEXT = 'b' * 40


def archive(extra=None):
    files = {
        'manette/__init__.py': '', 'manette/__main__.py': '', 'manette/app.py': 'VERSION = "new"\n',
        'bin/manette': '#!/bin/sh\nexit 0\n', 'data/local.Manette.svg': '<svg/>',
        'data/local.Manette.desktop.in': '[Desktop Entry]\nName=Manette\nExec=@EXEC@\n',
    }
    files.update(extra or {})
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as zip:
        for name, value in files.items():
            zip.writestr('repository-root/' + name, value)
    return data.getvalue()


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.data = self.home / 'share'
        self.config = self.home / 'config'
        for item in [patch.object(updater.Path, 'home', return_value=self.home),
                     patch.object(updater.GLib, 'get_user_data_dir', return_value=str(self.data)),
                     patch.object(updater.GLib, 'get_user_config_dir', return_value=str(self.config)),
                     patch.object(updater, '_revision', return_value=REVISION)]:
            item.start()
            self.addCleanup(item.stop)

    def install(self):
        source = Path(__file__).resolve().parent.parent
        return updater.install_local(source)

    def test_bootstrap_preserves_source_and_user_preferences(self):
        source = Path(__file__).resolve().parent.parent
        before = (source / 'manette/app.py').read_bytes()
        preferences.save(language='en')
        commands = self.config / 'manette/commandes.json'
        commands.write_text('[{"name":"Personal"}]')
        destination = self.install()
        self.assertEqual((source / 'manette/app.py').read_bytes(), before)
        self.assertEqual(commands.read_text(), '[{"name":"Personal"}]')
        self.assertEqual(preferences.load()['language'], 'en')
        self.assertTrue(preferences.load()['automatic_updates'])
        self.assertEqual((updater.root() / 'current').resolve(), destination)
        launcher = self.home / '.local/bin/manette'
        self.assertTrue(launcher.is_symlink())
        self.assertEqual(launcher.resolve(), destination / 'bin/manette')
        self.assertTrue((destination / 'bin/manette').stat().st_mode & stat.S_IXUSR)

    def test_valid_update_keeps_previous_version_and_changes_only_active_link(self):
        previous = self.install()
        destination = updater.stage_archive(archive(), NEXT)
        self.assertEqual((updater.root() / 'current').resolve(), destination)
        self.assertEqual((updater.root() / 'previous').resolve(), previous)
        self.assertTrue(previous.is_dir())
        self.assertEqual(json.loads((destination / 'installation.json').read_text())['revision'], NEXT)

    def test_invalid_archive_never_replaces_active_version(self):
        previous = self.install()
        for content in (b'not a zip', archive({'manette/app.py': 'invalid Python !'}),
                        archive({'../outside.txt': 'unsafe'})):
            with self.subTest(content=content[:16]), self.assertRaises((ValueError, SyntaxError, zipfile.BadZipFile)):
                updater.stage_archive(content, NEXT)
            self.assertEqual((updater.root() / 'current').resolve(), previous)
        self.assertFalse((updater.root() / 'outside.txt').exists())

    def test_symlinks_in_archives_are_rejected(self):
        previous = self.install()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as zip:
            link = zipfile.ZipInfo('repo/manette/link')
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            zip.writestr(link, '/etc/passwd')
        with self.assertRaises(ValueError):
            updater.stage_archive(buffer.getvalue(), NEXT)
        self.assertEqual((updater.root() / 'current').resolve(), previous)

    def test_archive_size_and_revision_are_checked(self):
        previous = self.install()
        with patch.object(updater, 'LIMIT', 32), self.assertRaises(ValueError):
            updater.stage_archive(archive(), NEXT)
        with self.assertRaises(ValueError):
            updater.stage_archive(archive(), '../invalid')
        self.assertEqual((updater.root() / 'current').resolve(), previous)

    def test_failed_network_check_preserves_active_installation(self):
        previous = self.install()
        with patch.object(updater, 'managed', return_value=True), \
                patch.object(updater, 'request', side_effect=OSError('offline')):
            with self.assertRaises(OSError):
                updater.check(force=True)
        self.assertEqual((updater.root() / 'current').resolve(), previous)

    def test_update_checks_revision_and_requires_forward_history(self):
        previous = self.install()
        responses = [json.dumps({'default_branch': 'main'}).encode(), json.dumps({'sha': NEXT}).encode(),
                     json.dumps({'status': 'behind'}).encode()]
        with patch.object(updater, 'managed', return_value=True), \
                patch.object(updater, 'request', side_effect=responses) as request:
            with self.assertRaises(ValueError):
                updater.check(force=True)
            self.assertEqual(request.call_count, 3)
        self.assertEqual((updater.root() / 'current').resolve(), previous)

    def test_forward_update_is_staged_and_repeated_checks_are_limited(self):
        self.install()
        responses = [json.dumps({'default_branch': 'main'}).encode(), json.dumps({'sha': NEXT}).encode(),
                     json.dumps({'status': 'ahead'}).encode(), archive()]
        with patch.object(updater, 'managed', return_value=True), \
                patch.object(updater, 'request', side_effect=responses) as request:
            self.assertEqual(updater.check(force=True), 'updated')
            self.assertEqual(updater.check(), 'skipped')
            self.assertEqual(request.call_count, 4)
        self.assertEqual((updater.root() / 'current').resolve().name, NEXT)

    def test_concurrent_updates_are_blocked(self):
        updater.root().mkdir(parents=True)
        with (updater.root() / 'update.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(ValueError):
                updater.install_local()

    def test_existing_regular_launcher_is_not_overwritten(self):
        executable = self.home / '.local/bin/manette'
        executable.parent.mkdir(parents=True)
        executable.write_text('existing program')
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(executable.read_text(), 'existing program')
        self.assertFalse((updater.root() / 'current').exists())

    def test_disabled_automatic_updates_make_no_request(self):
        preferences.save(automatic_updates=False)
        with patch.object(updater, 'managed', return_value=True), \
                patch('manette.settings_dialog.threading.Thread') as thread:
            self.assertFalse(automatic_check(Mock()))
            thread.assert_not_called()


if __name__ == '__main__':
    unittest.main()
