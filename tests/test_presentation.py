from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from manette import preferences
from manette.app import Window
from manette.apps_page import AppsPage
from manette.scanner import App, APT, FLATPAK
from manette.settings_dialog import SettingsDialog


class PresentationTests(unittest.TestCase):
    def test_switching_view_keeps_search_and_filter_and_saves_choice(self):
        page = Mock(view_mode='grid', query='example', filter='updates')
        page.view_buttons = {'grid': Mock(), 'list': Mock()}
        with patch('manette.apps_page.preferences.save') as save:
            AppsPage.set_view(page, 'list')
            save.assert_called_once_with(applications_view='list')
        page.view_stack.set_visible_child_name.assert_called_once_with('list')
        self.assertEqual(page.query, 'example')
        self.assertEqual(page.filter, 'updates')

    def test_invalid_or_unchanged_view_does_not_save(self):
        page = Mock(view_mode='grid')
        with patch('manette.apps_page.preferences.save') as save:
            AppsPage.set_view(page, 'unknown')
            AppsPage.set_view(page, 'grid')
            save.assert_not_called()

    def test_large_sizes_sort_without_integer_overflow(self):
        page = Mock()
        page.sort.get_selected.return_value = 1
        large = SimpleNamespace(app=App('Large', APT, 'large', size=20 * 1024**3))
        small = SimpleNamespace(app=App('Small', APT, 'small', size=100))
        self.assertEqual(AppsPage._sort_rows(page, large, small), -1)
        self.assertEqual(AppsPage._sort_rows(page, small, large), 1)

    def test_both_presentations_receive_filter_changes_and_empty_state(self):
        page = Mock()
        page.apps = [App('Example', APT, 'example'), App('Other', FLATPAK, 'other')]
        page._matches = lambda app, key: AppsPage._matches(page, app, key)
        grid_section, list_section = Mock(apps=page.apps), Mock(apps=page.apps)
        page.sections = {'grid': [grid_section], 'list': [list_section]}
        page.filter, page.query, page.category = 'apt', 'missing', 'all'
        page._visible_app = lambda app: AppsPage._visible_app(page, app)
        AppsPage._invalidate_filter(page)
        grid_section.body.invalidate_filter.assert_called_once()
        list_section.body.invalidate_filter.assert_called_once()
        grid_section.set_visible.assert_called_with(False)
        list_section.set_visible.assert_called_with(False)
        page.grid_empty.set_visible.assert_called_with(True)
        page.query = 'example'
        AppsPage._invalidate_filter(page)
        page.grid_empty.set_visible.assert_called_with(False)
        page.list_empty.set_visible.assert_called_with(False)
        grid_section.count.set_label.assert_called_with('1')
        list_section.count.set_label.assert_called_with('1')

    def test_high_contrast_overrides_translucency(self):
        window = Mock()
        with patch('manette.app.preferences.load', return_value={'translucent': True}), \
                patch('manette.app.Adw.StyleManager.get_default') as style:
            style.return_value.get_high_contrast.return_value = True
            Window.apply_appearance(window)
        window.remove_css_class.assert_called_once_with('translucent')
        window.add_css_class.assert_not_called()

    def test_translucency_changes_background_class_without_fading_controls(self):
        window = Mock()
        with patch('manette.app.preferences.load', return_value={'translucent': True}), \
                patch('manette.app.Adw.StyleManager.get_default') as style:
            style.return_value.get_high_contrast.return_value = False
            Window.apply_appearance(window)
        window.add_css_class.assert_called_once_with('translucent')
        window.set_opacity.assert_not_called()

    def test_translucency_setting_applies_immediately(self):
        dialog, row = Mock(), Mock()
        row.get_active.return_value = False
        dialog.opacity_scale.get_value.return_value = 45
        with patch('manette.settings_dialog.preferences.save') as save:
            SettingsDialog._save_translucency(dialog, row)
            save.assert_called_once_with(translucent=False)
        dialog.window.apply_appearance.assert_called_once_with(opacity=45)
        dialog.opacity_scale.set_sensitive.assert_called_once_with(False)

    def test_background_opacity_handles_invalid_preferences_and_bounds(self):
        for value, expected in [(0, 0), (100, 100), (-20, 0), (150, 100),
                                ('35', 35), ('invalid', 78), (None, 78), (float('inf'), 78)]:
            with self.subTest(value=value):
                self.assertEqual(preferences.background_opacity({'background_opacity': value}), expected)
        self.assertEqual(preferences.background_opacity({}), 78)

    def test_opacity_preview_is_live_and_pending_save_is_flushed_on_close(self):
        dialog = Mock(_opacity_save_source=0)
        dialog.opacity_scale.get_value.return_value = 35
        with patch('manette.settings_dialog.GLib.timeout_add', return_value=123):
            SettingsDialog._preview_opacity(dialog, dialog.opacity_scale)
        dialog.window.apply_appearance.assert_called_once_with(opacity=35)
        dialog.opacity_value.set_label.assert_called_once_with('35 %')
        with patch('manette.settings_dialog.GLib.source_remove') as remove:
            SettingsDialog._closed(dialog)
            remove.assert_called_once_with(123)
        dialog._save_opacity.assert_called_once()
        with patch('manette.settings_dialog.preferences.save') as save:
            self.assertFalse(SettingsDialog._save_opacity(dialog))
            save.assert_called_once_with(background_opacity=35)


if __name__ == '__main__':
    unittest.main()
