"""Page Applications : ce qui est installé, comment, et les boutons qui vont avec."""

import threading
import traceback

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import scanner
from .scanner import APPIMAGE, APT, DEB, SOURCES
from .widgets import StatCard, page_box, page_scroller, plural, stat_grid

FILTERS = [("all", "Toutes"), ("updates", "Mises à jour"), *SOURCES.items()]
REMOVABLE = {APT, DEB, scanner.FLATPAK, scanner.SNAP, APPIMAGE}


class AppsPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.apps: list[scanner.App] = []
        self.filter = "all"
        self.query = ""
        self.scanning = False

        self.banner = Adw.Banner(button_label="Tout mettre à jour", button_style=Adw.BannerButtonStyle.SUGGESTED)
        self.banner.connect("button-clicked", lambda *_: self.update_all())
        self.append(self.banner)

        self.stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(Adw.StatusPage(title="Analyse en cours…",
                                            description="Je repère tes applications et la façon dont elles sont installées.",
                                            child=Adw.Spinner(width_request=40, height_request=40)), "loading")
        self.append(self.stack)

        content = page_box()
        self.card_count = StatCard("Applications", "view-app-grid-symbolic")
        self.card_updates = StatCard("Mises à jour", "software-update-available-symbolic")
        self.card_size = StatCard("Espace occupé", "drive-harddisk-symbolic")
        content.append(stat_grid(self.card_count, self.card_updates, self.card_size))

        tools = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        search_row = Gtk.Box(spacing=8)
        self.search = Gtk.SearchEntry(placeholder_text="Rechercher une application…", hexpand=True)
        self.search.connect("search-changed", self._on_search)
        self.sort = Gtk.DropDown.new_from_strings(["Trier par nom", "Trier par taille"])
        self.sort.connect("notify::selected", lambda *_: self.list.invalidate_sort())
        search_row.append(self.search)
        search_row.append(self.sort)
        tools.append(search_row)
        self.chips = Adw.WrapBox(child_spacing=6, line_spacing=6)
        tools.append(self.chips)
        content.append(tools)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        self.list.set_placeholder(Gtk.Label(label="Aucune application ne correspond.", margin_top=24,
                                            margin_bottom=24, css_classes=["dim-label"]))
        self.list.set_filter_func(self._filter_row)
        self.list.set_sort_func(self._sort_rows)
        content.append(self.list)
        self.stack.add_named(page_scroller(content), "list")

    # --- Analyse ----------------------------------------------------------

    def scan(self):
        if self.scanning:
            return
        self.scanning = True
        self.window.set_scanning(True)
        if not self.apps:
            self.stack.set_visible_child_name("loading")
        threading.Thread(target=self._scan_thread, daemon=True).start()

    def _scan_thread(self):
        try:
            apps = scanner.scan()
        except Exception:
            traceback.print_exc()
            apps = None
        GLib.idle_add(self._populate, apps)

    def _populate(self, apps):
        self.scanning = False
        self.window.set_scanning(False)
        if apps is None:
            self.window.toast("L'analyse des applications a échoué (détails dans le terminal).")
            return
        self.apps = apps
        self.list.remove_all()
        for app in apps:
            self.list.append(AppRow(app, self))

        updates = [a for a in apps if a.update]
        total = sum(a.size or 0 for a in apps)
        self.card_count.set(str(len(apps)), " · ".join(
            f"{sum(a.source == s for a in apps)} {label}" for s, label in SOURCES.items()
            if any(a.source == s for a in apps))[:80])
        self.card_updates.set(str(len(updates)) if updates else "Aucune",
                              "prêtes à installer" if updates else "Tout est à jour")
        self.card_size.set(GLib.format_size(total), "par les applications listées")
        self.banner.set_title(f"{plural(len(updates), 'mise à jour disponible', 'mises à jour disponibles')} : "
                              + ", ".join(a.name for a in updates[:4]) + ("…" if len(updates) > 4 else ""))
        self.banner.set_revealed(bool(updates))
        self._build_chips()
        self.stack.set_visible_child_name("list")

    def _build_chips(self):
        while child := self.chips.get_first_child():
            self.chips.remove(child)
        group = None
        for key, label in FILTERS:
            count = len(self.apps) if key == "all" else sum(self._matches(a, key) for a in self.apps)
            if key not in ("all", "updates") and not count:
                continue
            chip = Gtk.ToggleButton(label=f"{label}  {count}", css_classes=["chip"], active=key == self.filter)
            if group:
                chip.set_group(group)
            group = group or chip
            chip.connect("toggled", lambda b, k=key: b.get_active() and self._set_filter(k))
            self.chips.append(chip)

    # --- Filtre et tri ----------------------------------------------------

    @staticmethod
    def _matches(app, key):
        return key == "all" or (key == "updates" and bool(app.update)) or app.source == key

    def _set_filter(self, key):
        if self.filter != key:
            self.filter = key
            self._build_chips()
            self.list.invalidate_filter()

    def _on_search(self, entry):
        self.query = entry.get_text().casefold().strip()
        self.list.invalidate_filter()

    def _filter_row(self, row):
        app = row.app
        if not self._matches(app, self.filter):
            return False
        return not self.query or self.query in f"{app.name} {app.ident}".casefold()

    def _sort_rows(self, a, b):
        if self.sort.get_selected() == 1:
            return (b.app.size or 0) - (a.app.size or 0)
        return (a.app.name.casefold() > b.app.name.casefold()) - (a.app.name.casefold() < b.app.name.casefold())

    # --- Actions ----------------------------------------------------------

    def launch(self, app):
        try:
            app.info.launch([], Gdk.Display.get_default().get_app_launch_context())
            self.window.toast(f"{app.name} se lance…")
        except GLib.Error as error:
            self.window.toast(f"Impossible de lancer {app.name} : {error.message}")

    def update(self, app):
        command = scanner.update_command(app)
        self.window.run(command.argv, f"Mise à jour de {app.name}", command.display, on_done=lambda ok: self.scan())

    def update_all(self):
        apps = [a for a in self.apps if scanner.update_command(a)]
        command = scanner.update_all_command(apps)
        if not command:
            return
        body = "\n".join(f"• {a.name} → {a.update}" for a in apps)
        body += "\n\nTon mot de passe ne sera demandé qu'une fois."
        self.window.confirm(f"Mettre à jour {plural(len(apps), 'application', 'applications')} ?", body,
                            "Tout mettre à jour",
                            lambda: self.window.run(command.argv, "Mise à jour de toutes les applications",
                                                    command.display, on_done=lambda ok: self.scan()),
                            destructive=False)

    def remove(self, app):
        if app.source == APPIMAGE:
            self.window.confirm(f"Supprimer {app.name} ?",
                                f"Le fichier {app.note} sera placé dans la corbeille.",
                                "Mettre à la corbeille", lambda: self._trash(app))
        elif app.source in (APT, DEB):
            threading.Thread(target=lambda: GLib.idle_add(self._confirm_apt, app, scanner.removal_preview(app)),
                             daemon=True).start()
        else:
            self._confirm_remove(app, f"{SOURCES[app.source]} « {app.ident} » sera désinstallé. "
                                      "Tes fichiers personnels sont conservés.")

    def _confirm_apt(self, app, removed):
        body = f"Le paquet « {app.ident} » sera désinstallé avec apt. Tes réglages et fichiers personnels sont conservés."
        others = [p for p in removed if p != app.ident]
        if others:
            body += (f"\n\n⚠ apt supprimerait aussi {plural(len(others), 'autre paquet', 'autres paquets')} : "
                     + ", ".join(others[:12]) + ("…" if len(others) > 12 else ""))
        self._confirm_remove(app, body)

    def _confirm_remove(self, app, body):
        command = scanner.remove_command(app)
        self.window.confirm(f"Désinstaller {app.name} ?", body, "Désinstaller",
                            lambda: self.window.run(command.argv, f"Désinstallation de {app.name}", command.display,
                                                    on_done=lambda ok: self.scan()))

    def _trash(self, app):
        try:
            Gio.File.new_for_path(app.ident).trash(None)
        except GLib.Error as error:
            self.window.toast(f"Impossible de supprimer : {error.message}")
            return
        self.window.toast(f"{app.name} est dans la corbeille.")
        self.scan()


class AppRow(Adw.ActionRow):
    def __init__(self, app: scanner.App, page: AppsPage):
        super().__init__(title=GLib.markup_escape_text(app.name), subtitle_lines=2)
        self.app = app

        icon = Gtk.Image(pixel_size=40, css_classes=["icon-dropshadow"])
        if app.icon:
            icon.set_from_gicon(app.icon)
        else:
            icon.set_from_icon_name("application-x-executable")
        self.add_prefix(icon)

        details = [d for d in (app.version or "version inconnue", app.note) if d]
        subtitle = GLib.markup_escape_text(" · ".join(details))
        if app.update:
            subtitle += f"\n<b>→ {GLib.markup_escape_text(app.update)} disponible</b>"
        self.set_subtitle(subtitle)

        self.add_suffix(Gtk.Label(label=SOURCES[app.source], valign=Gtk.Align.CENTER,
                                  css_classes=["pill-tag", f"src-{app.source}"]))
        self.add_suffix(Gtk.Label(label=GLib.format_size(app.size) if app.size else "—", width_chars=9, xalign=1,
                                  css_classes=["dim-label", "numeric"]))

        if scanner.update_command(app):
            button = Gtk.Button(label="Mettre à jour", valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
            button.connect("clicked", lambda *_: page.update(app))
            self.add_suffix(button)
        if app.info:
            button = Gtk.Button(icon_name="media-playback-start-symbolic", tooltip_text="Lancer",
                                valign=Gtk.Align.CENTER, css_classes=["flat", "circular"])
            button.connect("clicked", lambda *_: page.launch(app))
            self.add_suffix(button)
        if app.source in REMOVABLE:
            button = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Désinstaller",
                                valign=Gtk.Align.CENTER, css_classes=["flat", "circular", "remove-button"])
            button.connect("clicked", lambda *_: page.remove(app))
            self.add_suffix(button)
