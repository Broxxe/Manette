"""Exercise persistence and safeguards without touching packages or user data."""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from manette import app_data, diagnostics, favorites, history, preferences, search, space
from manette.app import Window
from manette.apps_page import AppsPage
from manette.console import Console
from manette.data_dialog import DataDialog
from manette.scanner import App, APT, FLATPAK, LOCAL
from manette.space_dialog import SpaceDialog


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / 'state' / 'operations.sqlite3'
        item = patch.object(history, 'path', return_value=self.file)
        item.start()
        self.addCleanup(item.stop)

    def test_start_finish_private_persistence_and_bounded_report(self):
        ident = history.start('Install <example>', 'apt install example')
        self.assertEqual(history.entries()[0]['status'], 'running')
        history.finish(ident, 1, 'x' * history.MAX_OUTPUT + 'download timed out')
        entry = history.entries()[0]
        self.assertEqual(entry['command'], 'apt install example')
        self.assertEqual(entry['status'], 'failed')
        self.assertTrue(entry['output'].endswith('download timed out'))
        self.assertEqual(len(entry['output']), history.MAX_OUTPUT)
        self.assertIsNotNone(entry['finished'])
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)

    def test_recovery_does_not_claim_an_old_process_succeeded(self):
        history.record('Finished')
        history.start('Running during crash')
        history.recover()
        self.assertEqual([item['status'] for item in history.entries()], ['unknown', 'success'])

    def test_history_limit_and_clear_preserve_running_operations(self):
        with patch.object(history, 'MAX_ENTRIES', 3):
            for value in range(5):
                history.record(str(value))
            history.start('Current')
        self.assertEqual([item['title'] for item in history.entries()], ['Current', '4', '3'])
        history.clear()
        self.assertEqual([item['title'] for item in history.entries()], ['Current'])

    def test_unicode_report_limit_counts_bytes_and_keeps_early_errors(self):
        history.record('Unicode', output='é' * history.MAX_OUTPUT)
        self.assertLessEqual(len(history.entries()[0]['output'].encode('utf-8')), history.MAX_OUTPUT)
        console = Mock(operation_id=2, operation_output='Progress\n' * 20000,
                       operation_errors='E: download timed out', recording=True)
        with patch('manette.console.history.finish') as finish:
            Console._record_finished(console, 1)
        output = finish.call_args.args[2]
        self.assertIn('E: download timed out', output)
        self.assertLessEqual(len(output.encode('utf-8')), history.MAX_OUTPUT)

    def test_terminal_outcomes_are_explicitly_untracked(self):
        history.record('Interactive command', status='external')
        history.recover()
        self.assertEqual(history.entries()[0]['status'], 'external')

    def test_history_write_failure_does_not_break_console_completion(self):
        console = Mock(operation_id=1, operation_output='failure', operation_errors='', recording=True)
        with patch('manette.console.history.finish', side_effect=sqlite3.OperationalError('disk full')):
            Console._record_finished(console, 1)
        self.assertFalse(console.recording)
        self.assertIsNone(console.operation_id)
        console._write.assert_called_once()


class FavoriteAndSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        item = patch.object(preferences, 'path', return_value=Path(self.temp.name) / 'preferences.json')
        item.start()
        self.addCleanup(item.stop)

    def test_favorites_survive_other_preference_changes_and_toggle_off(self):
        app = App('Example', APT, 'example')
        key = favorites.application_key(app)
        favorites.toggle(key)
        preferences.save(background_opacity=44)
        self.assertIn(key, favorites.load())
        self.assertEqual(preferences.load()['background_opacity'], 44)
        favorites.toggle(key)
        self.assertNotIn(key, favorites.load())

    def test_app_and_command_names_do_not_collide(self):
        self.assertNotEqual(favorites.application_key(App('Example', LOCAL, 'example')),
                            favorites.command_key(SimpleNamespace(id='example')))

    def test_invalid_favorite_values_are_ignored_without_losing_valid_keys(self):
        preferences.save(favorites=[1, 'app:apt:example', None])
        self.assertEqual(favorites.load(), {'app:apt:example'})
        preferences.save(favorites='invalid')
        self.assertEqual(favorites.load(), set())

    def test_accent_case_and_multiword_search_include_folder_paths_and_commands(self):
        items = [search.Item('Vérifier les mises à jour', 'Actualise les paquets', 'system'),
                 search.Item('/home/alice/Models', 'LM Studio', 'folder'),
                 search.Item('Mon réseau', 'ip -br address', 'command')]
        self.assertEqual(search.find(items, 'VERIFIER paquets')[0], [items[0]])
        self.assertEqual(search.find(items, 'models studio')[0], [items[1]])
        self.assertEqual(search.find(items, 'ip address')[0], [items[2]])
        self.assertEqual(search.find(items, 'studio network')[1], 0)

    def test_empty_search_shows_favorites_and_navigation_and_limits_results(self):
        items = [search.Item(str(i), '', 'app', favorite=i == 10) for i in range(100)]
        items.append(search.Item('Settings', '', 'navigation'))
        matches, count = search.find(items, '')
        self.assertEqual(count, 2)
        self.assertTrue(matches[0].favorite)
        matches, count = search.find(items, '1', limit=3)
        self.assertEqual(len(matches), 3)
        self.assertGreater(count, 3)
        self.assertEqual(matches[0].title, '10')

    def test_favorite_filter_does_not_replace_other_filters(self):
        app = App('Example', APT, 'example', update='2.0')
        page = SimpleNamespace(is_favorite=lambda app: True)
        self.assertTrue(AppsPage._matches(page, app, 'favorites'))
        self.assertTrue(AppsPage._matches(page, app, 'updates'))
        self.assertFalse(AppsPage._matches(page, app, 'flatpak'))


class DiagnosticTests(unittest.TestCase):
    def test_actual_timeout_log_explains_download_failure(self):
        output = 'E: Impossible de récupérer https://example.test/file.deb Délai de connexion dépassé [IP : 1.2.3.4 443]'
        findings = diagnostics.analyze(output)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].action, 'updates')

    def test_distinguishes_failures_and_preserves_multiple_causes(self):
        with patch('manette.i18n.language', return_value='en'):
            cases = {'No space left on device': 'Not enough disk space',
                     'Temporary failure resolving example.test': 'Network name resolution failed',
                     'Could not get lock /var/lib/dpkg/lock': 'Package manager busy',
                     'dpkg was interrupted': 'Package configuration interrupted',
                     'Unmet dependencies': 'Dependencies need attention',
                     'NO_PUBKEY abc123': 'Repository needs attention',
                     'Certificate verification failed': 'Secure connection failed',
                     'Permission denied': 'Authorization denied'}
            for message, title in cases.items():
                with self.subTest(message=message):
                    self.assertEqual(diagnostics.analyze(message)[0].title, title)
            self.assertEqual(len(diagnostics.analyze('No space left on device\nDownload timed out')), 2)
            self.assertEqual(diagnostics.analyze('unrecognized failure')[0].title, 'Unknown cause')


class SpaceEstimateTests(unittest.TestCase):
    def probe(self, request=space.Request('apt-install', 'example'), free=10**10):
        result = SimpleNamespace(returncode=0, stdout=json.dumps({'download': 100, 'unpacked': 200, 'net': 50}), stderr='')
        with patch.object(space.subprocess, 'run', return_value=result) as run, \
                patch.object(space.shutil, 'disk_usage', return_value=SimpleNamespace(free=free)):
            estimate = space.inspect(request, ['/', '/var/cache/apt/archives'])
        return estimate, run

    def test_peak_space_combines_download_and_unpacked_on_same_filesystem(self):
        estimate, run = self.probe()
        self.assertFalse(estimate.partial)
        self.assertFalse(estimate.blocked)
        self.assertEqual(estimate.filesystems[0].required, space.RESERVE + 300)
        self.assertEqual(estimate.net, 50)
        self.assertEqual(run.call_args.kwargs['timeout'], 30)
        self.assertNotIn('pkexec', run.call_args.args[0])

    def test_separate_filesystems_are_not_conflated(self):
        original = space.Path.stat
        def stat(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            # Simulate /var/cache/apt on a separate disk without mounting anything.
            return SimpleNamespace(st_dev=2 if str(path).startswith('/var') else 1)
        with patch.object(space.Path, 'exists', return_value=True), \
                patch.object(space.Path, 'stat', stat):
            estimate, _ = self.probe()
        self.assertEqual(len(estimate.filesystems), 2)
        self.assertEqual(sorted(fs.required for fs in estimate.filesystems),
                         [space.RESERVE + 100, space.RESERVE + 200])

    def test_insufficient_space_blocks_known_requirements(self):
        estimate, _ = self.probe(free=100)
        self.assertTrue(estimate.blocked)

    def test_unknown_sources_and_failed_probes_do_not_invent_sizes(self):
        with patch.object(space.subprocess, 'run') as run:
            estimate = space.inspect(space.Request(), ['/'])
            run.assert_not_called()
        self.assertTrue(estimate.partial)
        self.assertIsNone(estimate.download)
        for outcome in [subprocess.TimeoutExpired('probe', 30), OSError('missing python'),
                        SimpleNamespace(stdout='invalid json', returncode=1, stderr='broken')]:
            kwargs = {'side_effect': outcome} if isinstance(outcome, Exception) else {'return_value': outcome}
            with patch.object(space.subprocess, 'run', **kwargs):
                estimate = space.inspect(space.Request('apt-upgrade'), ['/'])
            self.assertTrue(estimate.partial)
            self.assertIsNone(estimate.unpacked)
            self.assertTrue(estimate.note)

    def test_application_preflight_targets_exact_selected_apt_packages(self):
        request = AppsPage._space_request([App('One', APT, 'one'), App('Two', APT, 'two'),
                                           App('Other', FLATPAK, 'org.example.Other')])
        self.assertEqual(request.kind, 'apt-install')
        self.assertEqual(request.target, ['one', 'two'])
        self.assertTrue(request.partial)

    def test_preflight_does_not_start_installation_until_user_proceeds(self):
        window = Mock(_space_check_pending=False)
        window.console.busy = False
        with patch('manette.app.SpaceDialog') as dialog:
            Window.run(window, ['apt-get'], 'Install', space_request=space.Request())
            window.console.run.assert_not_called()
            self.assertTrue(window._space_check_pending)
            dialog.call_args.args[3]()
        window.run.assert_called_once_with(['apt-get'], 'Install', None, None)

    def test_disk_is_rechecked_when_user_proceeds(self):
        dialog = Mock(estimate=space.Estimate(10, 10, 10,
            [space.Filesystem(Path('/'), 100, 50, [Path('/')])], False))
        with patch('shutil.disk_usage', return_value=SimpleNamespace(free=20)):
            SpaceDialog._proceed(dialog)
        dialog.proceed.assert_not_called()
        dialog._calculate.assert_called_once()

    def test_confirmed_operation_can_start_before_dialog_close_animation_ends(self):
        window = SimpleNamespace(_space_check_pending=True)
        dialog = Mock(window=window, estimate=space.Estimate(None, None, None, [], True))
        dialog.proceed.side_effect = lambda: self.assertFalse(window._space_check_pending)
        SpaceDialog._proceed(dialog)
        dialog.close.assert_called_once()
        dialog.proceed.assert_called_once()


class RemovalSummarySafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.app = App('Example', LOCAL, 'example')
        for name in ('.config', '.cache', '.local/share', '.local/state', 'Documents', '.ssh/keys'):
            (self.home / name).mkdir(parents=True)
        patches = [patch.object(app_data.Path, 'home', return_value=self.home),
                   patch.object(app_data.GLib, 'get_user_config_dir', return_value=str(self.home / '.config')),
                   patch.object(app_data.GLib, 'get_user_cache_dir', return_value=str(self.home / '.cache')),
                   patch.object(app_data.GLib, 'get_user_data_dir', return_value=str(self.home / '.local/share')),
                   patch.object(app_data.GLib, 'get_user_state_dir', return_value=str(self.home / '.local/state')),
                   patch.object(app_data.GLib, 'get_user_special_dir', return_value=str(self.home / 'Documents'))]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_specific_user_folder_allowed_but_home_containers_and_credentials_blocked(self):
        folder = self.home / '.config/example'
        folder.mkdir()
        self.assertEqual(app_data.trash_candidate(folder, self.app, []), folder)
        for name in ('', '.config', '.cache', '.local', '.local/share', 'Documents', '.ssh', '.ssh/keys'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                app_data.trash_candidate(self.home / name, self.app, [])

    def test_symlinks_and_paths_outside_home_blocked(self):
        target = self.home / '.config/example'
        target.mkdir()
        link = self.home / 'link'
        link.symlink_to(target, target_is_directory=True)
        for path in (link, Path('/tmp'), self.home / 'absent'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                app_data.trash_candidate(path, self.app, [])

    def test_shared_folder_and_its_parent_or_child_blocked(self):
        parent = self.home / 'models'
        child = parent / 'specific'
        child.mkdir(parents=True)
        other = App('Other', LOCAL, 'other')
        with patch.object(app_data, 'discover', return_value=[app_data.Folder(child)]):
            for path in (parent, child):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    app_data.trash_candidate(path, self.app, [other])
        with patch.object(app_data, 'discover', return_value=[app_data.Folder(parent)]), self.assertRaises(ValueError):
            app_data.trash_candidate(child, self.app, [other])

    def test_folder_containing_another_program_is_blocked(self):
        target = self.home / 'app-installation'
        target.mkdir()
        program = target / 'other-program'
        program.write_text('test program')
        other = App('Other', LOCAL, 'other', info=SimpleNamespace(get_id=lambda: 'other.desktop', get_commandline=lambda: str(program)))
        with patch.object(app_data, 'discover', return_value=[]), self.assertRaises(ValueError):
            app_data.trash_candidate(target, self.app, [other])

    def test_changed_directory_after_confirmation_is_not_trashed(self):
        target = self.home / '.config/example'
        target.mkdir()
        dialog = Mock(app=self.app, window=Mock())
        dialog.window.apps_page.apps = []
        DataDialog._confirm_trash(dialog, target)
        callback = dialog.window.confirm.call_args.args[3]
        target.rename(target.with_name('old-example'))
        target.mkdir()
        with patch('manette.data_dialog.Gio.File.new_for_path') as file:
            callback()
            file.assert_not_called()
        self.assertTrue(target.exists())
        dialog.message.set_text.assert_called_once()

    def test_failed_uninstall_does_not_offer_data_removal(self):
        page = Mock()
        with patch('manette.apps_page.DataDialog') as dialog:
            AppsPage._after_remove(page, self.app, False)
            dialog.assert_not_called()
        page.scan.assert_called_once()


if __name__ == '__main__':
    unittest.main()
