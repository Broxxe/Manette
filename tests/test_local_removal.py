from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from gi.repository import Gio

from manette import local_removal, scanner
from manette.apps_page import AppsPage


class LocalRemovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.data = self.home / '.local/share'
        self.launchers = self.data / 'applications'
        self.launchers.mkdir(parents=True)
        patches = [patch.object(local_removal.Path, 'home', return_value=self.home),
                   patch.object(local_removal.GLib, 'get_user_data_dir', return_value=str(self.data)),
                   patch.object(local_removal.GLib, 'get_user_special_dir', return_value=None),
                   patch.object(local_removal.Gio.AppInfo, 'get_all', return_value=[])]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def application(self, root, kind='portable', name='example'):
        root.mkdir(parents=True, exist_ok=True)
        binary = root / root.name if kind == 'pyinstaller' else root / name
        binary.write_text('#!/bin/sh\nexit 0\n')
        binary.chmod(0o755)
        if kind == 'pyinstaller':
            (root / '_internal').mkdir()
        elif kind == 'appimage':
            (root / 'AppRun').write_text('launcher')
            (root / 'internal.desktop').write_text('marker')
        launcher = self.launchers / f'{name}.desktop'
        launcher.write_text(f'[Desktop Entry]\nType=Application\nName={name}\nExec="{binary}"\n')
        info = Gio.DesktopAppInfo.new_from_filename(str(launcher))
        self.assertIsNotNone(info)
        return scanner.App(name, scanner.LOCAL, launcher.name, info=info)

    def test_portable_bundle_recognition_is_generic(self):
        for kind in ('appimage', 'pyinstaller'):
            with self.subTest(kind=kind):
                root = self.home / 'Applications' / kind
                app = self.application(root, kind, name=kind)
                self.assertEqual(local_removal.preview(app).bundle, root)

    def test_unknown_app_does_not_guess_a_folder(self):
        app = self.application(self.home / 'Applications/unknown')
        self.assertIsNone(local_removal.preview(app).bundle)

    def test_manual_folder_supports_unknown_installations(self):
        root = self.home / 'custom-location/app'
        app = self.application(root)
        plan = local_removal.preview(app, root)
        self.assertTrue(plan.manual)
        self.assertEqual(plan.bundle, root)
        trash = Mock()
        local_removal.execute(app, plan, trash)
        self.assertEqual([call.args[0] for call in trash.call_args_list], [root, plan.launcher])
        self.assertTrue(root.exists())  # La doublure n'a rien supprimé.

    def test_protected_and_unrelated_folders_are_rejected(self):
        app = self.application(self.home / 'Applications/unknown')
        unrelated = self.home / 'unrelated'
        unrelated.mkdir()
        for root in (self.home, self.home / 'Applications', Path('/'), unrelated):
            with self.subTest(root=root), self.assertRaises(ValueError):
                local_removal.preview(app, root)

    def test_symbolic_links_do_not_enable_deleting_another_folder(self):
        root = self.home / 'custom/app'
        app = self.application(root)
        link = self.home / 'linked'
        link.symlink_to(root, target_is_directory=True)
        with self.assertRaises(ValueError):
            local_removal.preview(app, link)

    def test_shared_installation_is_blocked(self):
        root = self.home / 'Applications/shared'
        app = self.application(root, 'appimage', 'first')
        other = self.application(root, name='second')
        with patch.object(local_removal.Gio.AppInfo, 'get_all', return_value=[app.info, other.info]):
            self.assertIsNone(local_removal.preview(app).bundle)
            with self.assertRaises(ValueError):
                local_removal.preview(app, root)

    def test_modified_launcher_blocks_all_removals(self):
        root = self.home / 'Applications/bundle'
        app = self.application(root, 'appimage')
        plan = local_removal.preview(app)
        plan.launcher.write_text(plan.launcher.read_text() + '\nComment=changed\n')
        trash = Mock()
        with self.assertRaisesRegex(ValueError, 'changé'):
            local_removal.execute(app, plan, trash)
        trash.assert_not_called()

    def test_copied_desktop_file_is_associated_with_its_package(self):
        root = self.home / 'Applications/managed'
        app = self.application(root)
        system_data = self.home / 'system-share'
        original = system_data / 'applications' / app.info.get_id()
        original.parent.mkdir(parents=True)
        original.write_text(Path(app.info.get_filename()).read_text())
        def output(*args, **kwargs):
            if args[:2] == ('dpkg', '-S'):
                return f'example-package: {original}\n'
            if args[0] == 'dpkg-query':
                return 'example-package\t1.0\t50\t\n'
            return ''
        with patch.object(scanner.GLib, 'get_system_data_dirs', return_value=[str(system_data)]), \
                patch.object(scanner, '_run', side_effect=output), \
                patch.object(scanner, '_manual_packages', return_value=set()), \
                patch.object(scanner, '_apt_upgradable', return_value={}):
            apps = scanner._scan_debs({app.info.get_filename(): app.info}, [])
        self.assertEqual(apps[0].source, scanner.APT)
        self.assertEqual(apps[0].ident, 'example-package')
        self.assertEqual(apps[0].local_launchers, [app.info.get_filename()])

    def test_failed_package_removal_keeps_personal_launcher(self):
        page = Mock()
        app = self.application(self.home / 'Applications/managed')
        app.local_launchers = [app.info.get_filename()]
        with patch('manette.apps_page.Gio.File.new_for_path') as file:
            AppsPage._after_remove(page, app, False)
            file.assert_not_called()
        self.assertTrue(Path(app.info.get_filename()).exists())

    def test_local_removal_requires_confirmation(self):
        page = Mock()
        app = self.application(self.home / 'Applications/bundle', 'appimage')
        AppsPage._remove_local(page, app)
        page._trash_local.assert_not_called()
        plan = page._confirm_local_plan.call_args.args[1]
        AppsPage._confirm_local_plan(page, app, plan)
        self.assertIn(str(plan.bundle), page.window.confirm.call_args.args[1])
        page._trash_local.assert_not_called()
        page.window.confirm.call_args.args[3]()
        page._trash_local.assert_called_once_with(app, plan)

    def test_unknown_installation_requires_an_explicit_choice(self):
        page = Mock()
        app = self.application(self.home / 'Applications/unknown')
        with patch('manette.apps_page.Adw.AlertDialog') as constructor:
            AppsPage._remove_local(page, app)
            dialog = constructor.return_value
            callback = dialog.connect.call_args.args[1]
            callback(dialog, 'cancel')
            page._confirm_local_plan.assert_not_called()
            page._choose_local_folder.assert_not_called()
            page._trash_local.assert_not_called()
            callback(dialog, 'folder')
            page._choose_local_folder.assert_called_once_with(app)
            page._trash_local.assert_not_called()

    def test_appimage_scan_preserves_personal_launcher_for_cleanup(self):
        app = self.application(self.home / 'Applications/single')
        binary = self.home / 'Applications/Example.AppImage'
        binary.write_bytes(b'example')
        with patch.object(scanner, 'APPIMAGE_DIRS', ()):
            scanned = scanner._scan_appimages({str(binary): app.info})
        self.assertEqual(scanned[0].local_launchers, [app.info.get_filename()])


if __name__ == '__main__':
    unittest.main()
