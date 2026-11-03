from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from gi.repository import GLib

from manette import storage, system
from manette.storage_dialog import StorageDialog
from manette.system_page import SystemPage


class StorageTests(unittest.TestCase):
    def test_summary_is_sorted_and_does_not_count_home_twice(self):
        home = Path('/home/test')
        output = b'200\t/home/test/small\0' + b'700\t/home/test/.large\0' + b'1000\t/home/test\0'
        summary = storage.parse_usage(home, output)
        self.assertEqual(summary.total, 1000)
        self.assertEqual([entry.size for entry in summary.entries], [700, 200, 100])
        self.assertEqual(sum(entry.size for entry in summary.entries), 1000)
        self.assertTrue(summary.entries[-1].direct_files)
        self.assertEqual(summary.entries[-1].path, home)

    def test_null_separators_preserve_special_folder_names(self):
        summary = storage.parse_usage(Path('/home/test'),
            b'100\t/home/test/folder\twith\nnewlines\0' + b'100\t/home/test\0')
        self.assertEqual(summary.entries[0].path.name, 'folder\twith\nnewlines')

    def test_incomplete_output_is_not_presented_as_complete(self):
        summary = storage.parse_usage(Path('/home/test'), b'100\t/home/test/folder\0')
        self.assertEqual(summary.total, 100)
        self.assertTrue(summary.warning)
        with self.assertRaises(ValueError):
            storage.parse_usage(Path('/home/test'), b'')

    def test_timeout_keeps_partial_results_and_error_exit_is_visible(self):
        output = b'100\t/home/test/folder\0'
        with patch.object(storage.subprocess, 'run', side_effect=subprocess.TimeoutExpired('du', 60, output=output)):
            summary = storage.analyze(Path('/home/test'))
            self.assertIn('une minute', summary.warning)
        with patch.object(storage.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, output, b'Permission denied')):
            self.assertTrue(storage.analyze(Path('/home/test')).warning)

    def test_missing_du_has_actionable_error(self):
        with patch.object(storage.subprocess, 'run', side_effect=FileNotFoundError('du')):
            with self.assertRaisesRegex(ValueError, "Impossible de lancer"):
                storage.analyze(Path('/home/test'))

    def test_real_analysis_includes_hidden_folders_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            folder = home / '.hidden'
            folder.mkdir()
            data = folder / 'keep.bin'
            data.write_bytes(b'x' * 16384)
            (home / 'document.txt').write_text('keep')
            summary = storage.analyze(home)
            self.assertFalse(summary.warning)
            self.assertEqual(summary.home, home)
            self.assertTrue(any(entry.path == folder for entry in summary.entries))
            self.assertEqual(sum(entry.size for entry in summary.entries), summary.total)
            self.assertEqual(data.read_bytes(), b'x' * 16384)
            self.assertEqual((home / 'document.txt').read_text(), 'keep')

    def test_analysis_uses_current_home_and_no_shell_or_admin_rights(self):
        with patch.object(storage.Path, 'home', return_value=Path('/home/another-user')), \
                patch.object(storage.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0,
                            b'4096\t/home/another-user\0', b'')) as run:
            storage.analyze()
            self.assertEqual(run.call_args.args[0],
                             ['du', '-x', '-B1', '--max-depth=1', '--null', '--', '/home/another-user'])
            self.assertNotIn('shell', run.call_args.kwargs)


class StorageViewTests(unittest.TestCase):
    def test_system_button_opens_graphical_dialog_instead_of_console(self):
        action = next(action for _, _, actions in system.action_groups() for action in actions if action.view == 'storage')
        page = Mock()
        with patch('manette.system_page.StorageDialog') as dialog:
            SystemPage._run(page, action)
            dialog.assert_called_once_with(page.window)
            dialog.return_value.present.assert_called_once_with(page.window)
        page.window.run.assert_not_called()

    def test_summary_and_partial_warning_are_shown(self):
        dialog = Mock()
        dialog.generation = 1
        home = Path('/home/test')
        summary = storage.Summary(home, 1000, [storage.Entry(home / '.large', 900),
                                  storage.Entry(home, 100, True)], 'Analyse partielle')
        StorageDialog._populate(dialog, 1, summary, None)
        dialog.count_card.set.assert_called_with('1', 'dossiers cachés inclus')
        dialog.largest_card.set.assert_called_with(GLib.format_size(900), '.large')
        dialog.warning.set_visible.assert_called_with(True)
        dialog.stack.set_visible_child_name.assert_called_with('results')
        self.assertEqual(dialog.list.append.call_count, 2)

    def test_closed_dialog_ignores_late_results(self):
        dialog = Mock()
        dialog.generation = 2
        StorageDialog._populate(dialog, 1, None, 'Error')
        dialog.stack.set_visible_child_name.assert_not_called()

    def test_analysis_errors_offer_retry(self):
        dialog = Mock()
        dialog.generation = 1
        StorageDialog._populate(dialog, 1, None, 'Permission denied')
        dialog.refresh_button.set_sensitive.assert_called_with(True)
        dialog.error_page.set_description.assert_called_with('Permission denied')
        dialog.stack.set_visible_child_name.assert_called_with('error')

    def test_open_uses_file_manager_and_encodes_special_characters(self):
        dialog = Mock()
        with patch('manette.storage_dialog.Gio.AppInfo.launch_default_for_uri') as launch:
            StorageDialog._open(dialog, Path('/home/test/folder #1'))
            launch.assert_called_once_with('file:///home/test/folder%20%231', None)


if __name__ == '__main__':
    unittest.main()
