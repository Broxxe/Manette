import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from manette import scanner, system
from manette.apps_page import AppsPage
from manette.monitor_page import MonitorPage


class ScannerTests(unittest.TestCase):
    def test_only_installed_version_determines_origin(self):
        policy = """local-app:
  Installed: 2.0
  Candidate: 2.0
  Version table:
 *** 2.0 100
        100 /var/lib/dpkg/status
     1.0 500
        500 http://example.test/ubuntu stable/main amd64 Packages
repo-app:
  Installed: 1.0
  Candidate: 2.0
  Version table:
     2.0 500
        500 http://example.test/ubuntu stable/main amd64 Packages
 *** 1.0 500
        500 http://example.test/ubuntu stable/main amd64 Packages
        100 /var/lib/dpkg/status
"""
        with patch.object(scanner, '_run', return_value=policy):
            self.assertEqual(scanner._manual_packages(['local-app', 'repo-app']), {'local-app'})

    def test_failed_checks_report_unknown_instead_of_empty_success(self):
        failures = [FileNotFoundError('absent'), subprocess.TimeoutExpired('apt', 30),
                    subprocess.CompletedProcess(['apt'], 1, 'partial output', 'network unavailable')]
        for failure in failures:
            with self.subTest(failure=failure):
                kwargs = {'side_effect': failure} if isinstance(failure, Exception) else {'return_value': failure}
                warnings = []
                with patch.object(scanner.subprocess, 'run', **kwargs):
                    self.assertEqual(scanner._apt_upgradable(warnings), {})
                self.assertTrue(warnings)

    def test_absent_unused_flatpak_is_not_a_failure(self):
        with patch.object(scanner.shutil, 'which', return_value=None), patch.object(scanner, '_run') as run:
            warnings = []
            self.assertEqual(scanner._scan_flatpaks({}, warnings), [])
            self.assertEqual(warnings, [])
            run.assert_not_called()
            scanner._scan_flatpaks({'app': Mock()}, warnings)
            self.assertTrue(warnings)


class UpdateScriptsTests(unittest.TestCase):
    def run_script(self, script, installed=(), failing=''):
        # PATH contient uniquement nos doublures : aucune maintenance réelle.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'bash').symlink_to('/bin/bash')
            scripts = {'pkexec': 'exec "$@"', 'apt-get': 'exit "${APT_STATUS:-0}"',
                       'apt': 'exit "${APT_STATUS:-0}"'}
            scripts.update({name: f'exit "${{{name.upper()}_STATUS:-0}}"' for name in installed})
            for name, body in scripts.items():
                path = root / name
                path.write_text('#!/bin/bash\n' + body + '\n')
                path.chmod(0o755)
            env = {**os.environ, 'PATH': directory, 'APT_STATUS': '0', 'SNAP_STATUS': '0', 'FLATPAK_STATUS': '0'}
            if failing:
                env[f'{failing}_STATUS'] = '1'
            return subprocess.run(['/bin/bash', '-c', script], env=env, capture_output=True, text=True, timeout=5)

    def test_optional_managers_and_failures(self):
        for script in (system.CHECK_UPDATES, system.UPDATE_ALL):
            for installed in ((), ('snap',), ('flatpak',), ('snap', 'flatpak')):
                with self.subTest(script=script, installed=installed):
                    self.assertEqual(self.run_script(script, installed).returncode, 0)
                    self.assertNotEqual(self.run_script(script, installed, 'APT').returncode, 0)
                    for name in installed:
                        self.assertNotEqual(self.run_script(script, installed, name.upper()).returncode, 0)


class UiCallbacksTests(unittest.TestCase):
    def test_scan_warning_and_recovery(self):
        page = Mock()
        page.apps = []
        AppsPage._populate(page, scanner.ScanResult([], ['APT indisponible']))
        page.card_updates.set.assert_called_with('Inconnu', 'Vérification incomplète')
        page.scan_warning.set_visible.assert_called_with(True)
        AppsPage._populate(page, scanner.ScanResult([]))
        page.card_updates.set.assert_called_with('Aucune', 'Aucune mise à jour détectée')
        page.scan_warning.set_visible.assert_called_with(False)

    def test_initial_scan_failure_leaves_loading_state(self):
        page = Mock()
        page.apps = []
        AppsPage._populate(page, None)
        page.stack.set_visible_child_name.assert_called_with('error')

    def test_close_reports_actual_outcome_on_main_loop(self):
        usage = SimpleNamespace(name='Example', units=['app-example-123.scope'])
        page = Mock()
        cases = [(subprocess.CompletedProcess([], 0, '', ''), 'Example est fermée'),
                 (subprocess.CompletedProcess([], 1, '', 'access denied'), 'Impossible de fermer'),
                 (FileNotFoundError('systemctl'), 'Impossible de fermer'),
                 (subprocess.TimeoutExpired('systemctl', 30), 'non confirmée')]
        for outcome, expected in cases:
            kwargs = {'side_effect': outcome} if isinstance(outcome, Exception) else {'return_value': outcome}
            with patch('manette.monitor_page.subprocess.run', **kwargs), \
                    patch('manette.monitor_page.GLib.idle_add') as idle:
                MonitorPage._close_app(page, usage)
                self.assertEqual(idle.call_args.args[0], page.window.toast)
                self.assertIn(expected, idle.call_args.args[1])

    def test_close_starts_worker_after_confirmation(self):
        page = Mock()
        usage = SimpleNamespace(name='Example', processes=2, units=['app-example-123.scope'])
        with patch('manette.monitor_page.threading.Thread') as thread:
            MonitorPage.close_app(page, usage)
            thread.assert_not_called()
            page.window.confirm.call_args.args[3]()
            thread.assert_called_once_with(target=page._close_app, args=(usage,), daemon=True)
            thread.return_value.start.assert_called_once()


if __name__ == '__main__':
    unittest.main()


# Les tests historiques vérifient les messages de référence français.
def setUpModule():
    global _locale_patch
    _locale_patch = patch("manette.i18n.language", return_value="fr")
    _locale_patch.start()


def tearDownModule():
    _locale_patch.stop()
