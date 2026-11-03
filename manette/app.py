"""Fenêtre principale de Manette."""

import sys
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from .apps_page import AppsPage
from .console import Console
from .custom_page import CustomPage
from .monitor_page import MonitorPage
from .system_page import SystemPage
from . import system

APP_ID = "local.Manette"
HERE = Path(__file__).parent


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Manette", default_width=1280, default_height=840,
                         width_request=360, height_request=480)
        self.console = Console(on_finished=self._on_finished)

        self.stack = Adw.ViewStack()
        self.apps_page = AppsPage(self)
        self.system_page = SystemPage(self)
        self.monitor_page = MonitorPage(self)
        self.custom_page = CustomPage(self)
        self.stack.add_titled_with_icon(self.apps_page, "apps", "Applications", "view-app-grid-symbolic")
        self.stack.add_titled_with_icon(self.system_page, "system", "Système", "computer-symbolic")
        self.stack.add_titled_with_icon(self.monitor_page, "monitor", "Moniteur", "utilities-system-monitor-symbolic")
        self.stack.add_titled_with_icon(self.custom_page, "custom", "Mes commandes", "utilities-terminal-symbolic")
        self.stack.connect("notify::visible-child-name", lambda *_: self._on_page_changed())

        header = Adw.HeaderBar(title_widget=Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE))
        self.refresh_button = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Tout réanalyser (Ctrl+R)",
                                         action_name="win.refresh")
        header.pack_start(self.refresh_button)
        menu = Gio.Menu()
        menu.append("Ouvrir le fichier des commandes", "win.open-config")
        menu.append("À propos de Manette", "app.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True,
                                       tooltip_text="Menu"))
        console_toggle = Gtk.ToggleButton(icon_name="utilities-terminal-symbolic", tooltip_text="Console (Ctrl+J)")
        header.pack_end(console_toggle)

        main = Adw.ToolbarView(content=self.stack, top_bar_style=Adw.ToolbarStyle.RAISED_BORDER)
        main.add_top_bar(header)
        self.split = Adw.OverlaySplitView(content=main, sidebar=self.console, sidebar_position=Gtk.PackType.END,
                                          show_sidebar=False, min_sidebar_width=380, max_sidebar_width=600,
                                          sidebar_width_fraction=0.42)
        self.split.bind_property("show-sidebar", console_toggle, "active",
                                 GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        self.toasts = Adw.ToastOverlay(child=self.split)
        self.set_content(self.toasts)

        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 900sp"))
        breakpoint.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(breakpoint)

        for name, callback in (("refresh", self.refresh), ("open-config", self._open_config),
                               ("toggle-console", lambda: self.split.set_show_sidebar(not self.split.get_show_sidebar()))):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_, cb=callback: cb())
            self.add_action(action)

        self.refresh()

    def _on_page_changed(self):
        if self.stack.get_visible_child_name() == "monitor":
            self.monitor_page.start()
        else:
            self.monitor_page.stop()

    def refresh(self):
        self.apps_page.scan()
        self.system_page.refresh()

    def set_scanning(self, scanning: bool):
        self.refresh_button.set_sensitive(not scanning)
        self.refresh_button.set_child(Adw.Spinner() if scanning else Gtk.Image(icon_name="view-refresh-symbolic"))

    def run(self, argv, title, display=None, on_done=None, space_paths=None):
        if self.console.busy:
            self.split.set_show_sidebar(True)
            self.confirm("Une opération est déjà en cours", f"« {self.console.title} » continue. "
                         f"« {title} » n'a pas été lancé. Attends la fin de l'opération.",
                         "Compris", lambda: None, destructive=False)
            return
        if space_paths is not None:
            warnings = system.space_warnings(space_paths)
            if warnings:
                body = "\n".join(warnings) + ("\n\nLibère de la place dans Système → Nettoyage avant de continuer. "
                        "Ce seuil de précaution ne garantit pas l'espace nécessaire au téléchargement "
                        "et à l'installation.")
                self.confirm("Espace disque faible ou inconnu", body, "Continuer quand même",
                             lambda: self.run(argv, title, display, on_done), destructive=False)
                return
        self.split.set_show_sidebar(True)
        self.console.run(argv, title, display, on_done)

    def toast(self, message: str):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(message), timeout=4))

    def confirm(self, heading, body, label, callback, destructive=True):
        dialog = Adw.AlertDialog(heading=heading, body=body, default_response="cancel", close_response="cancel")
        dialog.add_response("cancel", "Annuler")
        dialog.add_response("ok", label)
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE if destructive
                                       else Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", lambda _d, response: response == "ok" and callback())
        dialog.present(self)

    def _on_finished(self, title, ok):
        self.toast(f"{'✔' if ok else '✘'} {title} : {'terminé' if ok else 'échec'}")
        if not self.is_active():
            notification = Gio.Notification.new(f"{title} : {'terminé' if ok else 'échec'}")
            notification.set_body("Le détail est dans la console de Manette.")
            self.get_application().send_notification("command-finished", notification)

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
        self.set_accels_for_action("win.toggle-console", ["<Control>j"])

    def do_activate(self):
        window = self.props.active_window or Window(self)
        window.present()

    def _about(self):
        Adw.AboutDialog(application_name="Manette", application_icon=APP_ID, version="0.1",
                        comments="Tes applications, ton système et tes commandes, en boutons.").present(
            self.props.active_window)


def main() -> int:
    return ManetteApp().run(sys.argv)
