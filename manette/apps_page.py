"""Page Applications : ce qui est installé, comment, et les boutons qui vont avec."""

import threading
import traceback
import subprocess
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import local_apps, local_removal, scanner
from .scanner import APPIMAGE, APT, DEB, SOURCES
from .data_dialog import DataDialog
from .widgets import StatCard, page_box, page_scroller, plural, stat_grid

FILTERS = [("all", "Toutes"), ("updates", "Mises à jour"), *SOURCES.items()]
REMOVABLE = {APT, DEB, scanner.FLATPAK, scanner.SNAP, APPIMAGE, scanner.LOCAL}


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

        file_bar = Gtk.Box(spacing=12, margin_top=12, margin_start=16, margin_end=16)
        file_bar.append(Gtk.Label(label="Une application téléchargée ?", xalign=0, hexpand=True, wrap=True))
        self.open_button = Gtk.Button(child=Adw.ButtonContent(icon_name="document-open-symbolic",
                                                             label="Ouvrir un fichier…"))
        self.open_button.connect("clicked", lambda *_: self.open_file())
        file_bar.append(self.open_button)
        self.append(file_bar)

        self.stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(Adw.StatusPage(title="Analyse en cours…",
                                            description="Je repère tes applications et la façon dont elles sont installées.",
                                            child=Adw.Spinner(width_request=40, height_request=40)), "loading")
        self.stack.add_named(Adw.StatusPage(title="Analyse impossible",
                                            description="Réessaie avec le bouton Actualiser.",
                                            icon_name="dialog-warning-symbolic"), "error")
        self.append(self.stack)

        content = page_box()
        self.card_count = StatCard("Applications", "view-app-grid-symbolic")
        self.card_updates = StatCard("Mises à jour", "software-update-available-symbolic")
        self.card_size = StatCard("Espace occupé", "drive-harddisk-symbolic")
        content.append(stat_grid(self.card_count, self.card_updates, self.card_size))
        self.scan_warning = Gtk.Label(xalign=0, wrap=True, selectable=True, visible=False,
                                       css_classes=["warning"])
        content.append(self.scan_warning)

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
            result = scanner.scan()
        except Exception:
            traceback.print_exc()
            result = None
        GLib.idle_add(self._populate, result)

    def _populate(self, result):
        self.scanning = False
        self.window.set_scanning(False)
        if result is None:
            self.card_updates.set("Inconnu", "La dernière analyse a échoué")
            self.banner.set_revealed(False)
            self.scan_warning.set_text("Analyse échouée : les résultats précédents peuvent être périmés.")
            self.scan_warning.set_visible(True)
            self.stack.set_visible_child_name("list" if self.apps else "error")
            self.window.toast("L'analyse des applications a échoué (détails dans le terminal).")
            return
        apps = result.apps
        self.scan_warning.set_text("Vérification incomplète :\n" + "\n".join(result.warnings))
        self.scan_warning.set_visible(bool(result.warnings))
        self.apps = apps
        self.list.remove_all()
        for app in apps:
            self.list.append(AppRow(app, self))

        updates = [a for a in apps if a.update]
        total = sum(a.size or 0 for a in apps)
        self.card_count.set(str(len(apps)), " · ".join(
            f"{sum(a.source == s for a in apps)} {label}" for s, label in SOURCES.items()
            if any(a.source == s for a in apps))[:80])
        self.card_updates.set(str(len(updates)) if updates else ("Inconnu" if result.warnings else "Aucune"),
                              "Vérification incomplète" if result.warnings else
                              ("prêtes à installer" if updates else "Aucune mise à jour détectée"))
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

    def show_data(self, app):
        DataDialog(app, self.window).present(self.window)

    def open_file(self):
        filters = Gio.ListStore.new(Gtk.FileFilter)
        supported = Gtk.FileFilter(name="Applications (.deb, .AppImage, Flatpak)")
        for suffix in ("deb", "AppImage", "appimage", "flatpakref", "flatpak"):
            supported.add_suffix(suffix)
        filters.append(supported)
        dialog = Gtk.FileDialog(title="Ouvrir une application téléchargée", filters=filters)
        folder = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD) or str(Path.home())
        dialog.set_initial_folder(Gio.File.new_for_path(folder))
        dialog.open(self.window, None, self._file_selected)

    def _file_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
        except GLib.Error as error:
            if not error.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                self.window.toast(f"Impossible d'ouvrir le fichier : {error.message}")
            return
        path = file.get_path()
        if path is None:
            self.window.toast("Choisis un fichier enregistré sur cet ordinateur.")
            return
        self._inspect_download(path)

    def _inspect_download(self, path):
        self.open_button.set_sensitive(False)
        threading.Thread(target=self._inspect_thread, args=(path,), daemon=True).start()

    def _inspect_thread(self, path):
        try:
            download, error = local_apps.inspect_file(path), None
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            download, error = None, str(exc)
        GLib.idle_add(self._confirm_download, download, error)

    def _confirm_download(self, download, error):
        self.open_button.set_sensitive(True)
        if error:
            self.window.toast(f"Impossible d'ouvrir cette application : {error}")
            return
        launch = download.kind == "appimage"
        label = "Lancer" if launch else "Installer"
        body = f"{download.path}\n\n{download.description}\n\nN'ouvre que des applications dont tu connais la provenance."
        self.window.confirm(f"{label} {download.path.name} ?", body, label,
                            lambda: self._open_download(download), destructive=False)

    def _open_download(self, download):
        if download.kind == "appimage":
            threading.Thread(target=self._launch_download, args=(download,), daemon=True).start()
            return
        command = download.command
        paths = [Path.home()] if download.kind == "flatpak" else ["/", "/var/cache/apt/archives"]
        self.window.run(command.argv, f"Installation de {download.path.name}", command.display,
                        on_done=lambda ok: self._after_install(), space_paths=paths)

    def _launch_download(self, download):
        try:
            local_apps.launch_appimage(download)
            message = f"{download.path.stem} se lance…"
        except (OSError, ValueError) as error:
            message = f"Impossible de lancer : {error}"
        GLib.idle_add(self.window.toast, message)

    def _after_install(self):
        self.scan()
        self.window.system_page.refresh()

    def launch(self, app):
        if app.source == APPIMAGE:
            self._inspect_download(app.ident)
            return
        try:
            app.info.launch([], Gdk.Display.get_default().get_app_launch_context())
            self.window.toast(f"{app.name} se lance…")
        except GLib.Error as error:
            self.window.toast(f"Impossible de lancer {app.name} : {error.message}")

    def update(self, app):
        command = scanner.update_command(app)
        if command is None:
            return
        body = f"{app.name} : {app.version} → {app.update}"
        if app.source == DEB:
            body += ("\n\nLe paquet téléchargé peut exécuter des scripts avec les droits administrateur. "
                     "La source de téléchargement est :\n" + app.update_url)
        self.window.confirm(f"Mettre à jour {app.name} ?", body, "Mettre à jour",
                            lambda: self.window.run(command.argv, f"Mise à jour de {app.name}", command.display,
                                                    on_done=lambda ok: self.scan(),
                                                    space_paths=["/", "/var/cache/apt/archives", "/var/lib/flatpak", Path.home()]),
                            destructive=False)

    def update_all(self):
        apps = [a for a in self.apps if scanner.update_command(a)]
        command = scanner.update_all_command(apps)
        if not command:
            return
        body = "\n".join(f"• {a.name} → {a.update}" for a in apps)
        if any(a.source == DEB for a in apps):
            body += "\n\nLes .deb téléchargés peuvent exécuter des scripts avec les droits administrateur."
        body += "\n\nUne autorisation administrateur peut être demandée."
        self.window.confirm(f"Mettre à jour {plural(len(apps), 'application', 'applications')} ?", body,
                            "Tout mettre à jour",
                            lambda: self.window.run(command.argv, "Mise à jour de toutes les applications",
                                                    command.display, on_done=lambda ok: self.scan(),
                                                    space_paths=["/", "/var/cache/apt/archives", "/var/lib/flatpak", Path.home()]),
                            destructive=False)

    def remove(self, app):
        if app.source == scanner.LOCAL:
            self._remove_local(app)
        elif app.source == APPIMAGE:
            body = f"Le fichier {app.note} sera placé dans la corbeille."
            if app.local_launchers:
                body += "\n\nCes raccourcis personnels seront aussi mis à la corbeille :\n" + "\n".join(app.local_launchers)
            self.window.confirm(f"Supprimer {app.name} ?",
                                body,
                                "Mettre à la corbeille", lambda: self._trash(app))
        elif app.source in (APT, DEB):
            threading.Thread(target=self._preview_removal, args=(app,), daemon=True).start()
        else:
            self._confirm_remove(app, f"{SOURCES[app.source]} « {app.ident} » sera désinstallé. "
                                      "Tes fichiers personnels sont conservés.")

    def _preview_removal(self, app):
        try:
            removed, error = scanner.removal_preview(app), None
        except scanner.RemovalPreviewError as exc:
            removed, error = None, str(exc)
        GLib.idle_add(self._confirm_apt, app, removed, error)

    def _confirm_apt(self, app, removed, error=None):
        if error or removed is None:
            self.window.confirm("Désinstallation bloquée", (error or "Simulation indisponible") +
                                "\n\nAucune suppression n'a été lancée. Réessaie après avoir corrigé le problème APT.",
                                "Compris", lambda: None, destructive=False)
            return
        body = f"Le paquet « {app.ident} » sera désinstallé avec apt. Tes réglages et fichiers personnels sont conservés."
        others = [p for p in removed if p != app.ident]
        if others:
            body += (f"\n\n⚠ apt supprimerait aussi {plural(len(others), 'autre paquet', 'autres paquets')} : "
                     + "\n" + "\n".join(f"• {pkg}" for pkg in others))
        self._confirm_remove(app, body)

    def _confirm_remove(self, app, body):
        command = scanner.remove_command(app)
        if app.local_launchers:
            body += "\n\nAprès réussite, ces raccourcis personnels seront mis à la corbeille :\n" + "\n".join(app.local_launchers)
        self.window.confirm(f"Désinstaller {app.name} ?", body, "Désinstaller",
                            lambda: self.window.run(command.argv, f"Désinstallation de {app.name}", command.display,
                                                    on_done=lambda ok: self._after_remove(app, ok)))

    def _after_remove(self, app, ok):
        if ok:
            for filename in app.local_launchers:
                path = Path(filename)
                if (path.parent != Path(GLib.get_user_data_dir()) / 'applications' or path.is_symlink()
                        or path.suffix != '.desktop' or not path.is_file()):
                    continue
                try:
                    Gio.File.new_for_path(str(path)).trash(None)
                except GLib.Error as error:
                    self.window.toast(f"Application désinstallée, mais raccourci conservé : {error.message}")
        self.scan()

    def _remove_local(self, app):
        try:
            plan = local_removal.preview(app)
        except (OSError, ValueError) as error:
            self.window.toast(str(error))
            return
        if plan.bundle is None:
            dialog = Adw.AlertDialog(heading=f"Retirer {app.name}",
                body="Manette ne connaît pas le dossier d'installation de cette application locale. "
                     "Tu peux le choisir pour préparer son retrait, ou retirer seulement son raccourci.",
                default_response="cancel", close_response="cancel")
            dialog.add_response("cancel", "Annuler")
            dialog.add_response("folder", "Choisir le dossier d'installation…")
            dialog.add_response("shortcut", "Retirer seulement le raccourci")
            dialog.connect("response", lambda _d, response: self._choose_local_folder(app) if response == "folder" else
                           self._confirm_local_plan(app, plan) if response == "shortcut" else None)
            dialog.present(self.window)
            return
        self._confirm_local_plan(app, plan)

    def _choose_local_folder(self, app):
        dialog = Gtk.FileDialog(title=f"Dossier d'installation de {app.name}")
        dialog.set_initial_folder(Gio.File.new_for_path(str(Path.home())))
        dialog.select_folder(self.window, None, lambda d, result: self._local_folder_selected(app, d, result))

    def _local_folder_selected(self, app, dialog, result):
        try:
            filename = dialog.select_folder_finish(result).get_path()
            if filename is None:
                raise ValueError("Choisis un dossier sur cet ordinateur.")
            plan = local_removal.preview(app, filename)
        except GLib.Error as error:
            if not error.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                self.window.toast(error.message)
            return
        except (OSError, ValueError) as error:
            self.window.confirm("Retrait du dossier bloqué", str(error), "Compris", lambda: None, destructive=False)
            return
        self._confirm_local_plan(app, plan)

    def _confirm_local_plan(self, app, plan):
        if plan.bundle:
            heading, label = f"Retirer {app.name} ?", "Mettre à la corbeille"
            body = (f"Dossier de l'application :\n{plan.bundle}\n\nRaccourci :\n{plan.launcher}\n\n"
                    "Tout le contenu de ce dossier sera mis à la corbeille. Les données situées ailleurs "
                    "sont conservées. Ferme l'application avant de continuer. "
                    "L'espace sera libéré lorsque tu videras la corbeille.")
        else:
            heading, label = f"Retirer le raccourci de {app.name} ?", "Retirer le raccourci"
            body = (f"{plan.launcher}\n\nLe dossier de l'application n'a pas été identifié avec assez de certitude. "
                    "Seul ce raccourci sera mis à la corbeille. Le programme et ses données resteront en place.")
        self.window.confirm(heading, body, label, lambda: self._trash_local(app, plan))

    def _trash_local(self, app, plan):
        try:
            local_removal.execute(app, plan, lambda p: Gio.File.new_for_path(str(p)).trash(None))
            self.window.toast(f"{app.name} : éléments mis à la corbeille.")
        except (OSError, ValueError, GLib.Error) as error:
            self.window.toast(f"Retrait incomplet ou annulé : {error}. Vérifie aussi la corbeille.")
        self.scan()

    def _trash(self, app):
        try:
            Gio.File.new_for_path(app.ident).trash(None)
        except GLib.Error as error:
            self.window.toast(f"Impossible de supprimer : {error.message}")
            return
        self.window.toast(f"{app.name} est dans la corbeille.")
        self._after_remove(app, True)


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

        data_button = Gtk.Button(icon_name="folder-open-symbolic", tooltip_text="Données et dossiers associés",
                                 valign=Gtk.Align.CENTER, css_classes=["flat", "circular"])
        data_button.connect("clicked", lambda *_: page.show_data(app))
        self.add_suffix(data_button)

        if scanner.update_command(app):
            button = Gtk.Button(label="Mettre à jour", valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
            button.connect("clicked", lambda *_: page.update(app))
            self.add_suffix(button)
        if app.info or app.source == APPIMAGE:
            button = Gtk.Button(icon_name="media-playback-start-symbolic", tooltip_text="Lancer",
                                valign=Gtk.Align.CENTER, css_classes=["flat", "circular"])
            button.connect("clicked", lambda *_: page.launch(app))
            self.add_suffix(button)
        if app.source in REMOVABLE:
            button = Gtk.Button(icon_name="user-trash-symbolic",
                                tooltip_text="Retirer l'application ou son raccourci" if app.source == scanner.LOCAL else "Désinstaller",
                                valign=Gtk.Align.CENTER, css_classes=["flat", "circular", "remove-button"])
            button.connect("clicked", lambda *_: page.remove(app))
            self.add_suffix(button)
