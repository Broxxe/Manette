import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from manette import app_data
from manette.scanner import App, APPIMAGE, FLATPAK, LOCAL, SNAP


class AppDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.config = self.home / 'custom-config'
        self.cache = self.home / 'custom-cache'
        self.data = self.home / 'custom-data'
        patches = [patch.dict(os.environ, {'HOME': str(self.home)}),
                   patch.object(app_data.Path, 'home', return_value=self.home),
                   patch.object(app_data.GLib, 'get_user_config_dir', return_value=str(self.config)),
                   patch.object(app_data.GLib, 'get_user_cache_dir', return_value=str(self.cache)),
                   patch.object(app_data.GLib, 'get_user_data_dir', return_value=str(self.data))]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_native_detection_respects_current_user_xdg_directories(self):
        target = self.config / 'org.example.App'
        target.mkdir(parents=True)
        app = App('Example', LOCAL, 'org.example.App')
        folders = app_data.discover(app)
        self.assertEqual([f.path for f in folders], [target])
        self.assertTrue(folders[0].automatic)

    def test_appimage_identity_does_not_embed_the_user_home(self):
        app = App('Example', APPIMAGE, str(self.home / 'Applications/Example.AppImage'))
        self.assertEqual(app_data.app_key(app), 'appimage:~/Applications/Example.AppImage')

    def test_flatpak_and_snap_use_current_home(self):
        for source, ident, path in [(FLATPAK, 'org.example.App', self.home / '.var/app/org.example.App'),
                                    (SNAP, 'example', self.home / 'snap/example')]:
            with self.subTest(source=source):
                path.mkdir(parents=True)
                folders = app_data.discover(App('Example', source, ident))
                self.assertEqual([f.path for f in folders], [path])

    def test_known_lmstudio_folder_is_portable_and_bionic_does_not_claim_it_all(self):
        lm = self.home / '.lmstudio'
        bionic = lm / 'apps/bionic'
        bionic.mkdir(parents=True)
        self.assertEqual([f.path for f in app_data.discover(App('LM Studio', LOCAL, 'lmstudio'))], [lm])
        self.assertEqual([f.path for f in app_data.discover(App('Bionic', LOCAL, 'bionic'))], [bionic])

    def test_manual_association_works_for_any_application_and_removal_keeps_files(self):
        app = App('Unknown application', LOCAL, 'unknown.desktop')
        target = self.home / 'any-folder'
        target.mkdir()
        valuable = target / 'keep.txt'
        valuable.write_text('Keep my data')
        app_data.associate(app, target)
        app_data.associate(app, target)  # Aucun doublon après deux ajouts.
        folders = app_data.discover(app)
        self.assertEqual(len(folders), 1)
        self.assertFalse(folders[0].automatic)
        raw = json.loads(app_data.config_path().read_text())
        self.assertEqual(raw[app_data.app_key(app)], ['~/any-folder'])
        app_data.associate(app, target, remove=True)
        self.assertEqual(app_data.associated(app), [])
        self.assertEqual(valuable.read_text(), 'Keep my data')

    def test_corrupt_config_is_not_overwritten(self):
        path = app_data.config_path()
        path.parent.mkdir(parents=True)
        path.write_text('broken JSON')
        with self.assertRaises(ValueError):
            app_data.associate(App('Example', LOCAL, 'example'), self.home / 'data')
        self.assertEqual(path.read_text(), 'broken JSON')

    def test_nested_and_duplicate_directories_are_not_counted_twice(self):
        parent = self.home / 'models'
        child = parent / 'subfolder'
        child.mkdir(parents=True)
        (child / 'model.bin').write_bytes(b'x' * 8192)
        rows, total, complete = app_data.measure([app_data.Folder(child), app_data.Folder(parent),
                                                 app_data.Folder(parent)])
        single_rows, single_total, _ = app_data.measure([app_data.Folder(parent)])
        self.assertEqual(total, single_total)
        self.assertTrue(complete)
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(row.included_in is not None for row in rows), 2)
        self.assertGreater(total, 0)

    def test_internal_symlink_does_not_include_external_data(self):
        parent = self.home / 'models'
        parent.mkdir()
        external = self.home / 'external'
        external.mkdir()
        (external / 'large.bin').write_bytes(b'x' * 100000)
        link = parent / 'link'
        link.symlink_to(external, target_is_directory=True)
        _, total, complete = app_data.measure([app_data.Folder(parent)])
        expected = parent.lstat().st_blocks * 512 + link.lstat().st_blocks * 512
        self.assertEqual(total, expected)
        self.assertTrue(complete)

    def test_missing_folder_and_timeout_are_explicitly_incomplete(self):
        rows, _, complete = app_data.measure([app_data.Folder(self.home / 'missing')])
        self.assertIsNone(rows[0].size)
        self.assertFalse(complete)
        rows, _, complete = app_data.measure([app_data.Folder(self.home)], timeout=0)
        self.assertFalse(complete)
        self.assertFalse(rows[0].complete)

    def test_hard_links_are_counted_once(self):
        parent = self.home / 'models'
        parent.mkdir()
        first = parent / 'first.bin'
        first.write_bytes(b'x' * 8192)
        (parent / 'second.bin').hardlink_to(first)
        _, total, complete = app_data.measure([app_data.Folder(parent)])
        self.assertEqual(total, parent.stat().st_blocks * 512 + first.stat().st_blocks * 512)
        self.assertTrue(complete)


if __name__ == '__main__':
    unittest.main()
