from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from manette import app_data, categories, preferences
from manette.apps_page import AppsPage
from manette.scanner import App, APT, APPIMAGE, DEB, FLATPAK, LOCAL, SNAP


def info(tags):
    return SimpleNamespace(get_categories=lambda: tags, get_id=lambda: 'org.example.App.desktop')


class CategoryTests(unittest.TestCase):
    def test_main_desktop_categories_are_organized_by_purpose(self):
        cases = {'Game;': ('games',), 'Office;': ('work',), 'Graphics;': ('creation',),
                 'Development;': ('development',), 'Network;': ('internet',),
                 'AudioVideo;': ('multimedia',), 'Education;Science;': ('education',),
                 'System;Settings;Utility;': ('system',), 'Utility;': ('utilities',)}
        for tags, expected in cases.items():
            with self.subTest(tags=tags):
                self.assertEqual(categories.detect(info(tags)), expected)

    def test_multiple_categories_are_kept_without_duplicates(self):
        self.assertEqual(categories.detect(info('AudioVideo;Audio;AudioVideoEditing;AudioVideo;Utility;')),
                         ('creation', 'multimedia'))

    def test_unknown_missing_or_invalid_metadata_does_not_guess_from_name(self):
        for source in (None, info(None), info(''), info('X-Vendor-Thing;'), info('game;'), info(42)):
            self.assertEqual(categories.detect(source), ('other',))
        self.assertEqual(App('Super Game Office', LOCAL, 'game-office').category_ids, ('other',))

    def test_classification_is_independent_of_installation_method(self):
        for source in (APT, DEB, FLATPAK, SNAP, LOCAL, APPIMAGE):
            with self.subTest(source=source):
                app = App('Example', source, 'org.example.App', info=info('Game;'))
                self.assertEqual(app.category_ids, ('games',))

    def test_loaded_category_metadata_is_cached_per_scan_object(self):
        desktop = Mock()
        desktop.get_categories.return_value = 'Development;'
        app = App('Example', APT, 'example', info=desktop)
        self.assertEqual(app.category_ids, ('development',))
        self.assertEqual(app.category_ids, ('development',))
        desktop.get_categories.assert_called_once()

    def test_real_desktop_file_metadata_is_read_without_running_the_program(self):
        from gi.repository import Gio
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'example.desktop'
            file.write_text('[Desktop Entry]\nType=Application\nName=Example\nExec=/bin/false\nCategories=Graphics;3DGraphics;\n')
            desktop = Gio.DesktopAppInfo.new_from_filename(str(file))
            self.assertEqual(categories.detect(desktop), ('creation',))

    def test_visual_groups_show_each_app_once_and_keep_category_order(self):
        editor = App('Editor', APT, 'editor', info=info('Development;TextEditor;Utility;'))
        audio = App('Audio editor', APT, 'audio', info=info('AudioVideo;AudioVideoEditing;'))
        game = App('Game', APT, 'game', info=info('Game;'))
        unknown = App('Unknown', LOCAL, 'unknown')
        groups = categories.grouped([editor, audio, game, unknown], lambda app: app.category_ids)
        self.assertEqual([key for key, _ in groups], ['games', 'creation', 'development', 'other'])
        flattened = [app.ident for _, apps in groups for app in apps]
        self.assertEqual(sorted(flattened), ['audio', 'editor', 'game', 'unknown'])
        self.assertEqual(len(flattened), len(set(flattened)))

    def test_secondary_category_filter_places_apps_under_the_selected_heading(self):
        editor = App('Audio editor', APT, 'audio', info=info('AudioVideo;AudioVideoEditing;'))
        game = App('Game', APT, 'game', info=info('Game;'))
        groups = categories.grouped([editor, game], lambda app: app.category_ids, 'multimedia')
        self.assertEqual(groups, [('multimedia', [editor])])

    def test_personal_choice_changes_the_visual_group(self):
        app = App('Example', APT, 'example', info=info('Game;'))
        overrides = {app_data.app_key(app): 'work'}
        groups = categories.grouped([app], lambda app: categories.for_app(app, overrides))
        self.assertEqual(groups, [('work', [app])])
        self.assertEqual(categories.grouped([], lambda app: app.category_ids), [])


class PersonalCategoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        item = patch.object(preferences, 'path', return_value=Path(self.temp.name) / 'preferences.json')
        item.start()
        self.addCleanup(item.stop)
        self.app = App('Example', APT, 'example', info=info('Utility;'))

    def test_personal_choice_persists_and_auto_restores_desktop_metadata(self):
        preferences.save(favorites=['app:apt:example'], background_opacity=40)
        choices = categories.save_choice(self.app, 'work')
        self.assertEqual(categories.for_app(self.app, choices), ('work',))
        self.assertEqual(categories.overrides_from(preferences.load()), choices)
        self.assertEqual(preferences.load()['favorites'], ['app:apt:example'])
        choices = categories.save_choice(self.app, 'auto')
        self.assertEqual(categories.for_app(self.app, choices), ('utilities',))
        self.assertNotIn(app_data.app_key(self.app), choices)
        self.assertEqual(preferences.load()['background_opacity'], 40)

    def test_invalid_json_is_never_overwritten(self):
        preferences.path().write_text('broken json')
        with self.assertRaises(ValueError):
            categories.save_choice(self.app, 'games')
        self.assertEqual(preferences.path().read_text(), 'broken json')

    def test_invalid_category_values_do_not_hide_apps_or_write_preferences(self):
        raw = {'application_categories': {'good': 'games', 'bad': ['work'], 'unknown': 'made-up'}}
        self.assertEqual(categories.overrides_from(raw), {'good': 'games'})
        self.assertEqual(categories.overrides_from({'application_categories': []}), {})
        with patch.object(preferences, 'save') as save, self.assertRaises(ValueError):
            categories.save_choice(self.app, 'made-up')
        save.assert_not_called()

    def test_appimage_choice_uses_a_portable_home_relative_identifier(self):
        self.app = App('Example', APPIMAGE, str(Path.home() / 'Applications/Example.AppImage'))
        choices = categories.save_choice(self.app, 'games')
        self.assertIn('appimage:~/Applications/Example.AppImage', choices)

    def test_collapsed_categories_ignore_invalid_saved_values(self):
        self.assertEqual(categories.collapsed_from({'collapsed_categories': ['games', None, [], 'invalid']}), {'games'})
        self.assertEqual(categories.collapsed_from({'collapsed_categories': 'games'}), set())
        self.assertEqual(categories.collapsed_from({}), set())

    def test_collapsing_syncs_both_views_and_survives_reload_without_losing_preferences(self):
        preferences.save(background_opacity=45, favorites=['app:apt:example'])
        grid, listing, other = Mock(key='games'), Mock(key='games'), Mock(key='work')
        page = SimpleNamespace(collapsed_categories=set(),
            sections={'grid': [grid, other], 'list': [listing]}, window=Mock())
        AppsPage.set_category_collapsed(page, 'games', True)
        self.assertEqual(page.collapsed_categories, {'games'})
        grid.set_expanded.assert_called_once_with(False)
        listing.set_expanded.assert_called_once_with(False)
        other.set_expanded.assert_not_called()
        self.assertEqual(categories.collapsed_from(preferences.load()), {'games'})
        self.assertEqual(preferences.load()['background_opacity'], 45)
        self.assertEqual(preferences.load()['favorites'], ['app:apt:example'])
        AppsPage.set_category_collapsed(page, 'games', False)
        self.assertEqual(categories.collapsed_from(preferences.load()), set())
        grid.set_expanded.assert_called_with(True)
        listing.set_expanded.assert_called_with(True)

    def test_syncing_an_unchanged_state_does_not_save_recursively(self):
        page = SimpleNamespace(collapsed_categories={'games'}, sections={}, window=Mock())
        with patch.object(preferences, 'save') as save:
            AppsPage.set_category_collapsed(page, 'games', True)
            AppsPage.set_category_collapsed(page, 'missing', True)
            save.assert_not_called()

    def test_failed_state_save_keeps_ui_usable_and_reports_the_problem(self):
        section = Mock(key='games')
        page = SimpleNamespace(collapsed_categories=set(), sections={'grid': [section]}, window=Mock())
        with patch.object(preferences, 'save', side_effect=OSError('disk full')):
            AppsPage.set_category_collapsed(page, 'games', True)
        section.set_expanded.assert_called_once_with(False)
        page.window.toast.assert_called_once()


class CategoryFilterTests(unittest.TestCase):
    def page(self, category='all', query='', source='all'):
        page = SimpleNamespace(category=category, query=query, filter=source, category_overrides={})
        page.is_favorite = lambda app: app.ident == 'favorite'
        page.categories_for = lambda app: categories.for_app(app, page.category_overrides)
        page.category_labels = lambda app: categories.labels(page.categories_for(app))
        page._matches = lambda app, key: AppsPage._matches(page, app, key)
        return page

    def test_category_source_favorites_and_search_are_combined(self):
        app = App('Example', FLATPAK, 'favorite', info=info('Game;'))
        page = self.page(category='games', query='example', source='favorites')
        self.assertTrue(AppsPage._visible_app(page, app))
        page.category = 'work'
        self.assertFalse(AppsPage._visible_app(page, app))
        page.category, page.filter = 'games', 'apt'
        self.assertFalse(AppsPage._visible_app(page, app))
        page.filter, page.query = 'all', 'missing'
        self.assertFalse(AppsPage._visible_app(page, app))

    def test_category_names_are_searchable_without_accents(self):
        page = self.page(query='creation')
        with patch('manette.categories.CATEGORIES', {**categories.CATEGORIES, 'creation': 'Création et graphisme'}):
            self.assertTrue(AppsPage._visible_app(page, App('Example', APT, 'example', info=info('Graphics;'))))

    def test_overrides_affect_filters_without_changing_source_or_safety(self):
        page = self.page(category='system')
        app = App('Example', LOCAL, 'example', info=info('Game;'))
        page.category_overrides = {app_data.app_key(app): 'system'}
        self.assertTrue(AppsPage._visible_app(page, app))
        self.assertEqual(app.source, LOCAL)
        self.assertEqual(app.category_ids, ('games',))

    def test_sort_within_category_keeps_favorites_first(self):
        page = self.page()
        page.sort = Mock()
        page.sort.get_selected.return_value = 0
        favorite = SimpleNamespace(app=App('Z', APT, 'favorite', info=info('Game;')))
        other = SimpleNamespace(app=App('A', APT, 'other', info=info('Graphics;')))
        self.assertEqual(AppsPage._sort_rows(page, favorite, other), -1)
        page.is_favorite = lambda app: False
        self.assertEqual(AppsPage._sort_rows(page, favorite, other), 1)


if __name__ == '__main__':
    unittest.main()
