import subprocess
import unittest
from unittest.mock import Mock, patch

from manette import commands, scanner, system
from manette.app import Window
from manette.apps_page import AppsPage
from manette.custom_page import CommandDialog, CustomPage
from manette.system_page import SystemPage


class RemovalTests(unittest.TestCase):
    def test_preview_errors_never_become_empty_success(self):
        outcomes = [FileNotFoundError('apt-get'), subprocess.TimeoutExpired('apt-get', 30),
                    subprocess.CompletedProcess([], 100, 'Remv partial\n', 'broken dependencies')]
        for outcome in outcomes:
            kwargs = {'side_effect': outcome} if isinstance(outcome, Exception) else {'return_value': outcome}
            with self.subTest(outcome=outcome), patch.object(scanner.subprocess, 'run', **kwargs), \
                    self.assertRaises(scanner.RemovalPreviewError):
                scanner.apt_removal_preview('autoremove')

    def test_simulation_has_no_privileged_command(self):
        output = 'Remv target [1.0]\nRemv dependency:amd64 [2.0]\n'
        app = scanner.App('Target', scanner.APT, 'target')
        with patch.object(scanner.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, '')) as run:
            self.assertEqual(scanner.removal_preview(app), ['target', 'dependency:amd64'])
            self.assertEqual(run.call_args.args[0], ['apt-get', '-s', 'remove', 'target'])

    def test_failed_app_simulation_blocks_removal(self):
        page = Mock()
        app = scanner.App('Target', scanner.APT, 'target')
        with patch.object(scanner, 'removal_preview', side_effect=scanner.RemovalPreviewError('APT error')), \
                patch('manette.apps_page.GLib.idle_add', side_effect=lambda callback, *args: callback(*args)):
            page._confirm_apt.side_effect = lambda *args: AppsPage._confirm_apt(page, *args)
            AppsPage._preview_removal(page, app)
        page._confirm_remove.assert_not_called()
        page.window.run.assert_not_called()
        page.window.confirm.call_args.args[3]()  # Le bouton « Compris » ne supprime rien.
        page.window.run.assert_not_called()

    def test_full_dependency_list_is_shown(self):
        page = Mock()
        app = scanner.App('Target', scanner.APT, 'target')
        others = [f'dependency-{i}' for i in range(20)]
        AppsPage._confirm_apt(page, app, ['target', *others])
        body = page._confirm_remove.call_args.args[1]
        for package in others:
            self.assertIn(f'• {package}\n', body + '\n')


class CleanupTests(unittest.TestCase):
    def test_every_cleanup_requires_confirmation(self):
        cleanups = next(actions for title, _, actions in system.action_groups() if title == 'Nettoyage')
        for action in cleanups:
            with self.subTest(action=action.title):
                self.assertTrue(action.confirm)
                self.assertTrue(action.destructive)
                self.assertTrue(action.confirmation or action.preview_autoremove)

    def test_cleanup_does_not_run_before_confirmation(self):
        action = next(actions for title, _, actions in system.action_groups() if title == 'Nettoyage')[1]
        page = Mock()
        SystemPage._run(page, action)
        page.window.run.assert_not_called()
        self.assertEqual(page.window.confirm.call_args.args[1], action.confirmation)
        self.assertTrue(page.window.confirm.call_args.kwargs['destructive'])
        page.window.confirm.call_args.args[3]()
        page.window.run.assert_called_once()

    def test_autoremove_failure_and_no_packages_do_not_run(self):
        action = system.Action('Nettoyage', '', '', 'apt-get autoremove', preview_autoremove=True)
        for packages, error in [(None, 'APT error'), ([], None)]:
            with self.subTest(error=error):
                page = Mock()
                SystemPage._confirm_autoremove(page, action, packages, error)
                page._run.assert_not_called()
                page.window.run.assert_not_called()

    def test_autoremove_success_requires_confirmation_with_packages(self):
        action = next(actions for title, _, actions in system.action_groups() if title == 'Nettoyage')[0]
        page = Mock()
        SystemPage._confirm_autoremove(page, action, ['old-kernel', 'old-dependency'], None)
        prepared = page._run.call_args.args[0]
        self.assertFalse(prepared.preview_autoremove)
        self.assertIn('• old-kernel', prepared.confirmation)
        self.assertIn('• old-dependency', prepared.confirmation)
        SystemPage._run(page, prepared)
        page.window.run.assert_not_called()
        page.window.confirm.call_args.args[3]()
        page.window.run.assert_called_once()


class ConfirmationTests(unittest.TestCase):
    def test_root_custom_command_requires_confirmation_even_for_legacy_config(self):
        for terminal in (False, True):
            page = Mock()
            item = commands.Custom('Admin', 'echo test', root=True, confirm=False, terminal=terminal)
            with patch('manette.custom_page.subprocess.Popen') as launch, \
                    patch.object(commands, 'terminal_argv', return_value=['terminal', 'echo', 'test']):
                CustomPage.run(page, item)
                page.window.run.assert_not_called()
                launch.assert_not_called()
                self.assertIn('droits administrateur', page.window.confirm.call_args.args[1])
                page.window.confirm.call_args.args[3]()
                if terminal:
                    launch.assert_called_once()
                else:
                    page.window.run.assert_called_once()

    def test_new_custom_commands_default_to_confirmation(self):
        self.assertTrue(commands.Custom('Example', 'echo test').confirm)

    def test_root_option_forces_confirmation_switch(self):
        dialog = Mock()
        dialog.root.get_active.return_value = True
        CommandDialog._sync_confirmation(dialog)
        dialog.confirm.set_active.assert_called_once_with(True)
        dialog.confirm.set_sensitive.assert_called_once_with(False)

    def test_cancel_never_calls_action(self):
        window, action = Mock(), Mock()
        with patch('manette.app.Adw.AlertDialog') as constructor:
            Window.confirm(window, 'Supprimer ?', 'Test', 'Supprimer', action)
            self.assertEqual(constructor.call_args.kwargs['default_response'], 'cancel')
            self.assertEqual(constructor.call_args.kwargs['close_response'], 'cancel')
            dialog = constructor.return_value
            callback = dialog.connect.call_args.args[1]
            callback(dialog, 'cancel')
            action.assert_not_called()
            callback(dialog, 'ok')
            action.assert_called_once()

    def test_single_app_update_does_not_run_without_confirmation(self):
        page = Mock()
        app = scanner.App('Example', scanner.APT, 'example', version='1', update='2')
        AppsPage.update(page, app)
        page.window.run.assert_not_called()
        page.window.confirm.call_args.args[3]()
        page.window.run.assert_called_once()


if __name__ == '__main__':
    unittest.main()


# Les tests historiques vérifient les messages de référence français.
def setUpModule():
    global _locale_patch
    _locale_patch = patch("manette.i18n.language", return_value="fr")
    _locale_patch.start()


def tearDownModule():
    _locale_patch.stop()
