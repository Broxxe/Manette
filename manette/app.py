"""Fenêtre principale de Manette."""

from .i18n import _ as tr

import sys
import os
import sqlite3
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from .apps_page import AppsPage
from .console import Console
from .custom_page import CustomPage
from .monitor_page import MonitorPage
from .system_page import SystemPage
from . import history, preferences, system, updater
from .history_dialog import HistoryDialog, DiagnosticDialog
from .space_dialog import SpaceDialog
from .settings_dialog import SettingsDialog, automatic_check, periodic_check

APP_ID = "local.Manette"
HERE = Path(__file__).parent


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Manette", default_width=1280, default_height=840,
                         width_request=360, height_request=480)
        self._space_check_pending = False
        try:
            history.recover()
        except (OSError, sqlite3.Error):
            pass
        self.console = Console(on_finished=self._on_finished)

        self.stack = Adw.ViewStack()
        self.apps_page = AppsPage(self)
        self.system_page = SystemPage(self)
        self.monitor_page = MonitorPage(self)
        self.custom_page = CustomPage(self)
        self.stack.add_titled_with_icon(self.apps_page, "apps", tr('Applications'), "view-app-grid-symbolic")
        self.stack.add_titled_with_icon(self.system_page, "system", tr('Système'), "computer-symbolic")
        self.stack.add_titled_with_icon(self.monitor_page, "monitor", tr('Moniteur'), "utilities-system-monitor-symbolic")
        self.stack.add_titled_with_icon(self.custom_page, "custom", tr('Mes commandes'), "utilities-terminal-symbolic")
        self.stack.connect("notify::visible-child-name", lambda *_: self._on_page_changed())

        header = Adw.HeaderBar(title_widget=Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE))
        self.refresh_button = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text=tr('Tout réanalyser (Ctrl+R)'),
                                         action_name="win.refresh")
        header.pack_start(self.refresh_button)
        menu = Gio.Menu()
        menu.append(tr('Historique des opérations'), 'win.history')
        menu.append(tr('Diagnostic des mises à jour'), 'win.diagnostics')
        menu.append(tr('Recherche globale'), 'win.search')
        menu.append(tr('Préférences et mises à jour'), "win.settings")
        menu.append(tr('Ouvrir le fichier des commandes'), "win.open-config")
        menu.append(tr('À propos de Manette'), "app.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True,
                                       tooltip_text=tr('Menu')))
        header.pack_end(Gtk.Button(icon_name='emblem-system-symbolic', action_name='win.settings',
                                    tooltip_text=tr('Réglages de Manette'), css_classes=['flat', 'circular']))
        console_toggle = Gtk.ToggleButton(icon_name="utilities-terminal-symbolic", tooltip_text=tr('Console (Ctrl+J)'))
        header.pack_end(console_toggle)
        header.pack_start(Gtk.Button(icon_name='edit-find-symbolic', action_name='win.search',
                                     tooltip_text=tr('Recherche globale (Ctrl+K)'), css_classes=['flat']))
        header.pack_end(Gtk.Button(icon_name='document-open-recent-symbolic', action_name='win.history',
                                   tooltip_text=tr('Historique des opérations'), css_classes=['flat']))

        main = Adw.ToolbarView(content=self.stack, top_bar_style=Adw.ToolbarStyle.RAISED_BORDER)
        main.add_css_class('manette-content')
        self.console.toolbar.add_css_class('manette-content')
        main.add_top_bar(header)
        self.split = Adw.OverlaySplitView(content=main, sidebar=self.console, sidebar_position=Gtk.PackType.END,
                                          show_sidebar=False, min_sidebar_width=380, max_sidebar_width=600,
                                          sidebar_width_fraction=0.42)
        self.split.bind_property("show-sidebar", console_toggle, "active",
                                 GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        self.toasts = Adw.ToastOverlay(child=self.split)
        self.set_content(self.toasts)
        self.add_css_class('manette-window')
        self._appearance_css = Gtk.CssProvider()
        self.get_style_context().add_provider(self._appearance_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.apply_appearance()
        Adw.StyleManager.get_default().connect('notify::high-contrast', lambda *_: self.apply_appearance())

        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 900sp"))
        breakpoint.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(breakpoint)

        for name, callback in (("refresh", self.refresh), ("open-config", self._open_config),
                               ("settings", lambda: SettingsDialog(self).present(self)),
                               ('history', lambda: HistoryDialog(self).present(self)),
                               ('diagnostics', lambda: DiagnosticDialog(self).present(self)),
                               ('search', self._search),
                               ("toggle-console", lambda: self.split.set_show_sidebar(not self.split.get_show_sidebar()))):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_, cb=callback: cb())
            self.add_action(action)

        self.refresh()
        GLib.timeout_add_seconds(5, automatic_check, self)
        GLib.timeout_add_seconds(86400, periodic_check, self)
        GLib.idle_add(self._show_rollback_notice)
        # Assez tôt pour une vraie utilisation, assez tard pour qu'un plantage au démarrage soit détecté.
        GLib.timeout_add_seconds(8, self._confirm_started)

    def _show_rollback_notice(self):
        if bad := updater.rollback_notice():
            self.toast(tr('Nouvelle version écartée : elle ne démarrait pas. Retour à la version précédente.'))
            self.record_operation(tr('Mise à jour de Manette'), False,
                                  tr('La version {value0} quittait en erreur au démarrage. Manette est revenue automatiquement à la version précédente et ne réinstallera pas celle-ci.', value0=bad[:12]))
        return False

    def _confirm_started(self):
        try:
            updater.confirm_started()
        except (OSError, ValueError):
            pass  # nouvelle tentative au prochain lancement
        return False

    def _on_page_changed(self):
        if self.stack.get_visible_child_name() == "monitor":
            self.monitor_page.start()
        else:
            self.monitor_page.stop()

    def apply_appearance(self, opacity=None):
        try:
            settings = preferences.load()
            enabled = bool(settings.get('translucent', True))
        except (OSError, ValueError):
            settings, enabled = {}, False
        amount = preferences.background_opacity(settings if opacity is None else {'background_opacity': opacity})
        self._appearance_css.load_from_string(
            f"window.manette-window {{ --manette-background-opacity: {amount}%; }}")
        enabled = enabled and not Adw.StyleManager.get_default().get_high_contrast()
        if enabled:
            self.add_css_class('translucent')
        else:
            self.remove_css_class('translucent')

    def refresh(self):
        self.apps_page.scan()
        self.system_page.refresh()

    def set_scanning(self, scanning: bool):
        self.refresh_button.set_sensitive(not scanning)
        self.refresh_button.set_child(Adw.Spinner() if scanning else Gtk.Image(icon_name="view-refresh-symbolic"))

    def run(self, argv, title, display=None, on_done=None, space_paths=None, space_request=None):
        if self.console.busy:
            self.split.set_show_sidebar(True)
            self.confirm(tr('Une opération est déjà en cours'), tr("« {value0} » continue. « {value1} » n'a pas été lancé. Attendez la fin de l'opération.", value0=self.console.title, value1=title),
                         tr('Compris'), lambda: None, destructive=False)
            return
        if self._space_check_pending:
            self.toast(tr('Un contrôle d’espace est déjà ouvert.'))
            return
        if space_request is not None:
            self._space_check_pending = True
            SpaceDialog(self, space_request, space_paths or [],
                        lambda: self.run(argv, title, display, on_done)).present(self)
            return
        if space_paths is not None:
            warnings = system.space_warnings(space_paths)
            if warnings:
                body = "\n".join(warnings) + (tr("\n\nLibérez de la place dans Système → Nettoyage avant de continuer. Ce seuil de précaution ne garantit pas l'espace nécessaire au téléchargement et à l'installation."))
                self.confirm(tr('Espace disque faible ou inconnu'), body, tr('Continuer quand même'),
                             lambda: self.run(argv, title, display, on_done), destructive=False)
                return
        self.split.set_show_sidebar(True)
        self.console.run(argv, title, display, on_done)

    def toast(self, message: str):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(message), timeout=4))

    def confirm(self, heading, body, label, callback, destructive=True):
        dialog = Adw.AlertDialog(heading=heading, body=body, default_response="cancel", close_response="cancel")
        dialog.add_response("cancel", tr('Annuler'))
        dialog.add_response("ok", label)
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE if destructive
                                       else Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", lambda _d, response: response == "ok" and callback())
        dialog.present(self)

    def _on_finished(self, title, ok):
        self.toast(f"{'✔' if ok else '✘'} {title} : {tr('terminé') if ok else tr('échec')}")
        if not self.is_active():
            notification = Gio.Notification.new(f"{title} : {tr('terminé') if ok else tr('échec')}")
            notification.set_body(tr('Le détail est dans la console de Manette.'))
            self.get_application().send_notification("command-finished", notification)

    def _search(self):
        from .search_dialog import SearchDialog
        SearchDialog(self).present(self)

    def record_operation(self, title, ok=True, output='', command='', status=None):
        try:
            history.record(title, 0 if ok else 1, output, command, status)
        except (OSError, sqlite3.Error):
            self.toast(tr('Historique indisponible'))

    def _open_config(self):
        from . import commands
        commands.PATH.parent.mkdir(parents=True, exist_ok=True)
        Gio.AppInfo.launch_default_for_uri(GLib.filename_to_uri(str(commands.PATH.parent), None), None)


class ManetteApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self):
        Adw.Application.do_startup(self)
        Gtk.Window.set_default_icon_name(APP_ID)
        css = Gtk.CssProvider()
        css.load_from_path(str(HERE / "style.css"))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", lambda *_: self._about())
        self.add_action(about)
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Control>q"])
        self.set_accels_for_action("win.refresh", ["<Control>r"])
        self.set_accels_for_action('win.search', ['<Control>k'])
        self.set_accels_for_action('win.history', ['<Control>h'])
        self.set_accels_for_action("win.toggle-console", ["<Control>j"])

    def do_activate(self):
        window = self.props.active_window or Window(self)
        window.present()

    def _about(self):
        Adw.AboutDialog(application_name="Manette", application_icon=APP_ID, version=updater.installed_version() or "dev",
                        license_type=Gtk.License.GPL_3_0_ONLY, copyright="© 2026 Broxxe",
                        comments=tr('Applications, système et commandes accessibles en quelques clics.')).present(
            self.props.active_window)


def main() -> int:
    from .i18n import language
    os.environ['LANGUAGE'] = language()
    return ManetteApp().run(sys.argv)
