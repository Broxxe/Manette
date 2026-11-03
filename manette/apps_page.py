"""Page Applications : ce qui est installé, comment, et les boutons qui vont avec."""

from .i18n import _ as tr

import threading
import traceback
import subprocess
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from . import categories, favorites, local_apps, local_removal, preferences, scanner, space
from .category_dialog import CategoryDialog
from .search import normalize
from .scanner import APPIMAGE, APT, DEB, SOURCES
from .data_dialog import DataDialog
from .widgets import StatCard, page_box, page_scroller, plural, stat_grid

FILTERS = [("all", tr('Toutes')), ("favorites", tr('Favoris')), ("updates", tr('Mises à jour')), *SOURCES.items()]
REMOVABLE = {APT, DEB, scanner.FLATPAK, scanner.SNAP, APPIMAGE, scanner.LOCAL}


class AppsPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.apps: list[scanner.App] = []
        self.filter = "all"
        self.category = "all"
        self.category_overrides = {}
        self.collapsed_categories = set()
        self._category_rebuilding = False
        self.query = ""
        self.scanning = False
        try:
            self.favorites = favorites.load()
        except (OSError, ValueError):
            self.favorites = set()
        try:
            settings = preferences.load()
            mode = settings.get('applications_view', 'grid')
            self.category_overrides = categories.overrides_from(settings)
            self.collapsed_categories = categories.collapsed_from(settings)
        except (OSError, ValueError):
            mode = 'grid'
        self.view_mode = mode if mode in ('grid', 'list') else 'grid'

        self.banner = Adw.Banner(button_label=tr('Tout mettre à jour'), button_style=Adw.BannerButtonStyle.SUGGESTED)
        self.banner.connect("button-clicked", lambda *_: self.update_all())
        self.append(self.banner)

        file_bar = Gtk.Box(spacing=12, margin_top=12, margin_start=16, margin_end=16)
        file_bar.append(Gtk.Label(label=tr('Une application téléchargée ?'), xalign=0, hexpand=True, wrap=True))
        self.open_button = Gtk.Button(child=Adw.ButtonContent(icon_name="document-open-symbolic",
                                                             label=tr('Ouvrir un fichier…')))
        self.open_button.connect("clicked", lambda *_: self.open_file())
        file_bar.append(self.open_button)
        self.append(file_bar)

        self.stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(Adw.StatusPage(title=tr('Analyse en cours…'),
                                            description=tr('Identification des applications et de leur mode d’installation.'),
                                            child=Adw.Spinner(width_request=40, height_request=40)), "loading")
        self.stack.add_named(Adw.StatusPage(title=tr('Analyse impossible'),
                                            description=tr('Réessayez avec le bouton Actualiser.'),
                                            icon_name="dialog-warning-symbolic"), "error")
        self.append(self.stack)

        content = page_box()
        self.card_count = StatCard(tr('Applications'), "view-app-grid-symbolic")
        self.card_updates = StatCard(tr('Mises à jour'), "software-update-available-symbolic")
        self.card_size = StatCard(tr('Espace occupé'), "drive-harddisk-symbolic")
        content.append(stat_grid(self.card_count, self.card_updates, self.card_size))
        self.scan_warning = Gtk.Label(xalign=0, wrap=True, selectable=True, visible=False,
                                       css_classes=["warning"])
        content.append(self.scan_warning)

        tools = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        search_row = Gtk.Box(spacing=8)
        self.search = Gtk.SearchEntry(placeholder_text=tr('Rechercher une application…'), hexpand=True)
        self.search.connect("search-changed", self._on_search)
        self.sort = Gtk.DropDown.new_from_strings([tr('Trier par nom'), tr('Trier par taille')])
        self.sort.connect("notify::selected", lambda *_: self._invalidate_sort())
        search_row.append(self.search)
        search_row.append(self.sort)
        tools.append(search_row)
        view_row = Gtk.Box(spacing=6)
        view_row.append(Gtk.Label(label=tr('Affichage'), xalign=0, hexpand=True, css_classes=['dim-label']))
        self.view_buttons = {}
        for key, label, icon in [('grid', tr('Mosaïque'), 'view-grid-symbolic'),
                                  ('list', tr('Liste'), 'view-list-symbolic')]:
            button = Gtk.ToggleButton(child=Adw.ButtonContent(icon_name=icon, label=label),
                                      active=self.view_mode == key)
            if self.view_buttons:
                button.set_group(self.view_buttons['grid'])
            self.view_buttons[key] = button
            view_row.append(button)
        tools.append(view_row)
        self.chips = Adw.WrapBox(child_spacing=6, line_spacing=6)
        tools.append(self.chips)
        category_row = Gtk.Box(spacing=12)
        category_row.append(Gtk.Label(label=tr('Catégorie'), xalign=0, hexpand=True, css_classes=['dim-label']))
        self.category_keys = ['all']
        self.category_choice = Gtk.DropDown.new_from_strings([tr('Toutes les catégories')])
        self.category_choice.set_tooltip_text(tr('Classement d’après les catégories déclarées par les applications. Plusieurs catégories sont possibles.'))
        self.category_choice.connect('notify::selected', self._on_category)
        category_row.append(self.category_choice)
        tools.append(category_row)
        content.append(tools)

        self.sections = {'grid': [], 'list': []}
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.grid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        grid_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        grid_box.append(self.grid)
        self.grid_empty = Gtk.Label(label=tr('Aucune application ne correspond.'), margin_top=24,
                                     margin_bottom=24, visible=False, css_classes=['dim-label'])
        grid_box.append(self.grid_empty)
        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        list_box.append(self.list)
        self.list_empty = Gtk.Label(label=tr('Aucune application ne correspond.'), margin_top=24,
                                     margin_bottom=24, visible=False, css_classes=['dim-label'])
        list_box.append(self.list_empty)
        self.view_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.view_stack.add_named(grid_box, 'grid')
        self.view_stack.add_named(list_box, 'list')
        self.view_stack.set_visible_child_name(self.view_mode)
        content.append(self.view_stack)
        for key, button in self.view_buttons.items():
            button.connect('toggled', lambda b, k=key: b.get_active() and self.set_view(k))
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
            self.card_updates.set(tr('Inconnu'), tr('La dernière analyse a échoué'))
            self.banner.set_revealed(False)
            self.scan_warning.set_text(tr('Analyse échouée : les résultats précédents peuvent être périmés.'))
            self.scan_warning.set_visible(True)
            self.stack.set_visible_child_name("list" if self.apps else "error")
            self.window.toast(tr("L'analyse des applications a échoué (détails dans le terminal)."))
            return
        apps = result.apps
        self.scan_warning.set_text(tr('Vérification incomplète :\n') + "\n".join(result.warnings))
        self.scan_warning.set_visible(bool(result.warnings))
        self.apps = apps
        self._render_apps()

        updates = [a for a in apps if a.update]
        total = sum(a.size or 0 for a in apps)
        self.card_count.set(str(len(apps)), " · ".join(
            f"{sum(a.source == s for a in apps)} {label}" for s, label in SOURCES.items()
            if any(a.source == s for a in apps))[:80])
        self.card_updates.set(str(len(updates)) if updates else (tr('Inconnu') if result.warnings else tr('Aucune')),
                              tr('Vérification incomplète') if result.warnings else
                              (tr('prêtes à installer') if updates else tr('Aucune mise à jour détectée')))
        self.card_size.set(GLib.format_size(total), tr('par les applications listées'))
        self.banner.set_title(f"{plural(len(updates), tr('mise à jour disponible'), tr('mises à jour disponibles'))} : "
                              + ", ".join(a.name for a in updates[:4]) + ("…" if len(updates) > 4 else ""))
        self.banner.set_revealed(bool(updates))
        self._build_chips()
        self._refresh_category_choices()
        self._invalidate_filter()
        self.stack.set_visible_child_name("list")

    def _build_chips(self):
        while child := self.chips.get_first_child():
            self.chips.remove(child)
        group = None
        for key, label in FILTERS:
            count = len(self.apps) if key == "all" else sum(self._matches(a, key) for a in self.apps)
            if key not in ("all", "updates", "favorites") and not count:
                continue
            chip = Gtk.ToggleButton(label=f"{label}  {count}", css_classes=["chip"], active=key == self.filter)
            if group:
                chip.set_group(group)
            group = group or chip
            chip.connect("toggled", lambda b, k=key: b.get_active() and self._set_filter(k))
            self.chips.append(chip)

    # --- Filtre et tri ----------------------------------------------------

    def _matches(self, app, key):
        return (key == 'all' or (key == 'favorites' and self.is_favorite(app))
                or (key == 'updates' and bool(app.update)) or app.source == key)

    def is_favorite(self, app):
        return favorites.application_key(app) in self.favorites

    def toggle_favorite(self, app):
        try:
            self.favorites = favorites.toggle(favorites.application_key(app))
        except (OSError, ValueError) as error:
            self.window.toast(tr('Favoris non enregistrés : {value0}', value0=error))
            return
        self._render_apps()
        self._build_chips()
        self._refresh_category_choices()
        self._invalidate_filter()

    def _render_apps(self):
        groups = categories.grouped(self.apps, self.categories_for, self.category)
        for mode, container in (('grid', self.grid), ('list', self.list)):
            while child := container.get_first_child():
                container.remove(child)
            self.sections[mode] = []
            for key, members in groups:
                section = AppSection(key, members, mode, self)
                container.append(section)
                self.sections[mode].append(section)

    def categories_for(self, app):
        return categories.for_app(app, self.category_overrides)

    def set_category_collapsed(self, key, collapsed):
        if key not in categories.CATEGORIES or (key in self.collapsed_categories) == collapsed:
            return
        updated = set(self.collapsed_categories)
        if collapsed:
            updated.add(key)
        else:
            updated.discard(key)
        self.collapsed_categories = updated
        for sections in self.sections.values():
            for section in sections:
                if section.key == key:
                    section.set_expanded(not collapsed)
        try:
            preferences.save(collapsed_categories=sorted(updated))
        except (OSError, ValueError) as error:
            self.window.toast(tr('Le repli des catégories n’a pas pu être enregistré : {value0}', value0=error))

    def category_labels(self, app):
        return categories.labels(self.categories_for(app))

    def edit_category(self, app):
        CategoryDialog(app, self).present(self.window)

    def set_category(self, app, choice):
        try:
            self.category_overrides = categories.save_choice(app, choice)
        except (OSError, ValueError) as error:
            self.window.toast(tr('Catégorie non enregistrée : {value0}', value0=error))
            return False
        self._render_apps()
        self._refresh_category_choices()
        self._invalidate_filter()
        return True

    def _refresh_category_choices(self):
        counts = {key: 0 for key in categories.CATEGORIES}
        for app in self.apps:
            for key in self.categories_for(app):
                counts[key] += 1
        self._category_rebuilding = True
        self.category_keys = ['all', *categories.CATEGORIES]
        labels = [f"{tr('Toutes les catégories')} ({len(self.apps)})"]
        labels.extend(f'{label} ({counts[key]})' for key, label in categories.CATEGORIES.items())
        self.category_choice.set_model(Gtk.StringList.new(labels))
        self.category_choice.set_selected(self.category_keys.index(self.category))
        self._category_rebuilding = False

    def _on_category(self, dropdown, *unused):
        if self._category_rebuilding:
            return
        index = dropdown.get_selected()
        if index < len(self.category_keys):
            self.category = self.category_keys[index]
            self._render_apps()
            self._invalidate_filter()

    def _set_filter(self, key):
        if self.filter != key:
            self.filter = key
            self._build_chips()
            self._invalidate_filter()

    def _on_search(self, entry):
        self.query = entry.get_text().casefold().strip()
        self._invalidate_filter()

    def set_view(self, mode):
        if mode not in ('grid', 'list') or mode == self.view_mode:
            return
        self.view_mode = mode
        self.view_stack.set_visible_child_name(mode)
        self.view_buttons[mode].set_active(True)
        try:
            preferences.save(applications_view=mode)
        except (OSError, ValueError):
            self.window.toast(tr("Le choix d'affichage n'a pas pu être enregistré."))

    def _invalidate_sort(self):
        for sections in self.sections.values():
            for section in sections:
                section.body.invalidate_sort()

    def _invalidate_filter(self):
        for sections in self.sections.values():
            for section in sections:
                section.body.invalidate_filter()
                count = sum(self._visible_app(app) for app in section.apps)
                section.count.set_label(str(count))
                section.set_visible(bool(count))
        empty = not any(self._visible_app(app) for app in self.apps)
        self.grid_empty.set_visible(empty)
        self.list_empty.set_visible(empty)

    def _visible_app(self, app):
        if not self._matches(app, self.filter):
            return False
        if self.category != 'all' and self.category not in self.categories_for(app):
            return False
        text = f'{app.name} {app.ident} {self.category_labels(app)}'
        return not self.query or normalize(self.query) in normalize(text)

    def _filter_row(self, row):
        return self._visible_app(row.app)

    def _sort_rows(self, a, b):
        left_favorite, right_favorite = self.is_favorite(a.app), self.is_favorite(b.app)
        if left_favorite != right_favorite:
            return -1 if left_favorite else 1
        if self.sort.get_selected() == 1:
            left, right = a.app.size or 0, b.app.size or 0
            if left != right:
                return (right > left) - (right < left)
        return (a.app.name.casefold() > b.app.name.casefold()) - (a.app.name.casefold() < b.app.name.casefold())

    # --- Actions ----------------------------------------------------------

    def show_data(self, app):
        DataDialog(app, self.window).present(self.window)

    def open_file(self):
        filters = Gio.ListStore.new(Gtk.FileFilter)
        supported = Gtk.FileFilter(name=tr('Applications (.deb, .AppImage, Flatpak)'))
        for suffix in ("deb", "AppImage", "appimage", "flatpakref", "flatpak"):
            supported.add_suffix(suffix)
        filters.append(supported)
        dialog = Gtk.FileDialog(title=tr('Ouvrir une application téléchargée'), filters=filters)
        folder = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD) or str(Path.home())
        dialog.set_initial_folder(Gio.File.new_for_path(folder))
        dialog.open(self.window, None, self._file_selected)

    def _file_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
        except GLib.Error as error:
            if not error.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                self.window.toast(tr("Impossible d'ouvrir le fichier : {value0}", value0=error.message))
            return
        path = file.get_path()
        if path is None:
            self.window.toast(tr('Choisissez un fichier enregistré sur cet ordinateur.'))
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
            self.window.toast(tr("Impossible d'ouvrir cette application : {value0}", value0=error))
            return
        launch = download.kind == "appimage"
        label = tr('Lancer') if launch else tr('Installer')
        body = tr('{value0}\n\n{value1}\n\nOuvrez uniquement des applications de provenance connue.', value0=download.path, value1=download.description)
        self.window.confirm(f"{label} {download.path.name} ?", body, label,
                            lambda: self._open_download(download), destructive=False)

    def _open_download(self, download):
        if download.kind == "appimage":
            threading.Thread(target=self._launch_download, args=(download,), daemon=True).start()
            return
        command = download.command
        paths = [Path.home()] if download.kind == "flatpak" else ["/", "/var/cache/apt/archives"]
        self.window.run(command.argv, tr('Installation de {value0}', value0=download.path.name), command.display,
                        on_done=lambda ok: self._after_install(), space_paths=paths,
                        space_request=space.Request('deb', str(download.path)) if download.kind == 'deb'
                        else space.Request())

    def _launch_download(self, download):
        try:
            local_apps.launch_appimage(download)
            message = tr('{value0} se lance…', value0=download.path.stem)
            ok = True
        except (OSError, ValueError) as error:
            message = tr('Impossible de lancer : {value0}', value0=error)
            ok = False
        GLib.idle_add(self.window.record_operation, tr('Lancement de {value0}', value0=download.path.stem),
                      ok, message, str(download.path))
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
            self.window.toast(tr('{value0} se lance…', value0=app.name))
        except GLib.Error as error:
            self.window.toast(tr('Impossible de lancer {value0} : {value1}', value0=app.name, value1=error.message))

    @staticmethod
    def _space_request(apps):
        apt_apps = [app for app in apps if app.source == APT]
        return space.Request('apt-install', [app.ident for app in apt_apps],
                             partial=len(apt_apps) != len(apps)) if apt_apps else space.Request()

    def update(self, app):
        command = scanner.update_command(app)
        if command is None:
            return
        body = f"{app.name} : {app.version} → {app.update}"
        if app.source == DEB:
            body += (tr('\n\nLe paquet téléchargé peut exécuter des scripts avec les droits administrateur. La source de téléchargement est :\n') + app.update_url)
        self.window.confirm(tr('Mettre à jour {value0} ?', value0=app.name), body, tr('Mettre à jour'),
                            lambda: self.window.run(command.argv, tr('Mise à jour de {value0}', value0=app.name), command.display,
                                                    on_done=lambda ok: self.scan(),
                                                    space_paths=["/", "/var/cache/apt/archives", "/var/lib/flatpak", Path.home()],
                                                    space_request=self._space_request([app])),
                            destructive=False)

    def update_all(self):
        apps = [a for a in self.apps if scanner.update_command(a)]
        command = scanner.update_all_command(apps)
        if not command:
            return
        body = "\n".join(f"• {a.name} → {a.update}" for a in apps)
        if any(a.source == DEB for a in apps):
            body += tr('\n\nLes .deb téléchargés peuvent exécuter des scripts avec les droits administrateur.')
        body += tr('\n\nUne autorisation administrateur peut être demandée.')
        self.window.confirm(tr('Mettre à jour {value0} ?', value0=plural(len(apps), tr('application'), tr('applications'))), body,
                            tr('Tout mettre à jour'),
                            lambda: self.window.run(command.argv, tr('Mise à jour de toutes les applications'),
                                                    command.display, on_done=lambda ok: self.scan(),
                                                    space_paths=["/", "/var/cache/apt/archives", "/var/lib/flatpak", Path.home()],
                                                    space_request=self._space_request(apps)),
                            destructive=False)

    def remove(self, app):
        if app.source == scanner.LOCAL:
            self._remove_local(app)
        elif app.source == APPIMAGE:
            body = tr('Le fichier {value0} sera placé dans la corbeille.', value0=app.note)
            if app.local_launchers:
                body += tr('\n\nCes raccourcis personnels seront aussi mis à la corbeille :\n') + "\n".join(app.local_launchers)
            self.window.confirm(tr('Supprimer {value0} ?', value0=app.name),
                                body,
                                tr('Mettre à la corbeille'), lambda: self._trash(app))
        elif app.source in (APT, DEB):
            threading.Thread(target=self._preview_removal, args=(app,), daemon=True).start()
        else:
            self._confirm_remove(app, tr('{value0} « {value1} » sera désinstallé. Vos fichiers personnels sont conservés.', value0=SOURCES[app.source], value1=app.ident))

    def _preview_removal(self, app):
        try:
            removed, error = scanner.removal_preview(app), None
        except scanner.RemovalPreviewError as exc:
            removed, error = None, str(exc)
        GLib.idle_add(self._confirm_apt, app, removed, error)

    def _confirm_apt(self, app, removed, error=None):
        if error or removed is None:
            self.window.confirm(tr('Désinstallation bloquée'), (error or tr('Simulation indisponible')) +
                                tr("\n\nAucune suppression n'a été lancée. Réessayez après avoir corrigé le problème APT."),
                                tr('Compris'), lambda: None, destructive=False)
            return
        body = tr('Le paquet « {value0} » sera désinstallé avec apt. Vos réglages et fichiers personnels sont conservés.', value0=app.ident)
        others = [p for p in removed if p != app.ident]
        if others:
            body += (tr('\n\n⚠ apt supprimerait aussi {value0} : ', value0=plural(len(others), tr('autre paquet'), tr('autres paquets')))
                     + "\n" + "\n".join(f"• {pkg}" for pkg in others))
        self._confirm_remove(app, body)

    def _confirm_remove(self, app, body):
        command = scanner.remove_command(app)
        if app.local_launchers:
            body += tr('\n\nAprès réussite, ces raccourcis personnels seront mis à la corbeille :\n') + "\n".join(app.local_launchers)
        self.window.confirm(tr('Désinstaller {value0} ?', value0=app.name), body, tr('Désinstaller'),
                            lambda: self.window.run(command.argv, tr('Désinstallation de {value0}', value0=app.name), command.display,
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
                    self.window.toast(tr('Application désinstallée, mais raccourci conservé : {value0}', value0=error.message))
            DataDialog(app, self.window, after_removal=True).present(self.window)
        self.scan()
        self.window.system_page.refresh()

    def _remove_local(self, app):
        try:
            plan = local_removal.preview(app)
        except (OSError, ValueError) as error:
            self.window.toast(str(error))
            return
        if plan.bundle is None:
            dialog = Adw.AlertDialog(heading=tr('Retirer {value0}', value0=app.name),
                body=tr("Manette ne connaît pas le dossier d'installation de cette application locale. Vous pouvez le choisir pour préparer son retrait, ou retirer seulement son raccourci."),
                default_response="cancel", close_response="cancel")
            dialog.add_response("cancel", tr('Annuler'))
            dialog.add_response("folder", tr("Choisir le dossier d'installation…"))
            dialog.add_response("shortcut", tr('Retirer seulement le raccourci'))
            dialog.connect("response", lambda _d, response: self._choose_local_folder(app) if response == "folder" else
                           self._confirm_local_plan(app, plan) if response == "shortcut" else None)
            dialog.present(self.window)
            return
        self._confirm_local_plan(app, plan)

    def _choose_local_folder(self, app):
        dialog = Gtk.FileDialog(title=tr("Dossier d'installation de {value0}", value0=app.name))
        dialog.set_initial_folder(Gio.File.new_for_path(str(Path.home())))
        dialog.select_folder(self.window, None, lambda d, result: self._local_folder_selected(app, d, result))

    def _local_folder_selected(self, app, dialog, result):
        try:
            filename = dialog.select_folder_finish(result).get_path()
            if filename is None:
                raise ValueError(tr('Choisissez un dossier sur cet ordinateur.'))
            plan = local_removal.preview(app, filename)
        except GLib.Error as error:
            if not error.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                self.window.toast(error.message)
            return
        except (OSError, ValueError) as error:
            self.window.confirm(tr('Retrait du dossier bloqué'), str(error), tr('Compris'), lambda: None, destructive=False)
            return
        self._confirm_local_plan(app, plan)

    def _confirm_local_plan(self, app, plan):
        if plan.bundle:
            heading, label = tr('Retirer {value0} ?', value0=app.name), tr('Mettre à la corbeille')
            body = (tr("Dossier de l'application :\n{value0}\n\nRaccourci :\n{value1}\n\nTout le contenu de ce dossier sera mis à la corbeille. Les données situées ailleurs sont conservées. Fermez l'application avant de continuer. L'espace sera libéré lorsque vous viderez la corbeille.", value0=plan.bundle, value1=plan.launcher))
        else:
            heading, label = tr('Retirer le raccourci de {value0} ?', value0=app.name), tr('Retirer le raccourci')
            body = (tr("{value0}\n\nLe dossier de l'application n'a pas été identifié avec assez de certitude. Seul ce raccourci sera mis à la corbeille. Le programme et ses données resteront en place.", value0=plan.launcher))
        self.window.confirm(heading, body, label, lambda: self._trash_local(app, plan))

    def _trash_local(self, app, plan):
        try:
            local_removal.execute(app, plan, lambda p: Gio.File.new_for_path(str(p)).trash(None))
            self.window.toast(tr('{value0} : éléments mis à la corbeille.', value0=app.name))
            self.window.record_operation(tr('Retrait de {value0}', value0=app.name),
                                         output='\n'.join(map(str, [plan.launcher, plan.bundle] if plan.bundle else [plan.launcher])))
            DataDialog(app, self.window, after_removal=True, shortcut_only=plan.bundle is None).present(self.window)
        except (OSError, ValueError, GLib.Error) as error:
            self.window.toast(tr('Retrait incomplet ou annulé : {value0}. Vérifiez aussi la corbeille.', value0=error))
            self.window.record_operation(tr('Retrait de {value0}', value0=app.name), False, str(error))
        self.scan()

    def _trash(self, app):
        try:
            Gio.File.new_for_path(app.ident).trash(None)
        except GLib.Error as error:
            self.window.toast(tr('Impossible de supprimer : {value0}', value0=error.message))
            return
        self.window.toast(tr('{value0} est dans la corbeille.', value0=app.name))
        self.window.record_operation(tr('Retrait de {value0}', value0=app.name), output=app.ident)
        self._after_remove(app, True)


def app_icon(app, size):
    icon = Gtk.Image(pixel_size=size, css_classes=['icon-dropshadow'])
    if app.icon:
        icon.set_from_gicon(app.icon)
    else:
        icon.set_from_icon_name('application-x-executable')
    return icon


def app_play(app, page):
    button = Gtk.Button(child=Gtk.Image(icon_name='media-playback-start-symbolic', pixel_size=26),
                        tooltip_text=tr('Lancer'), valign=Gtk.Align.CENTER,
                        css_classes=['suggested-action', 'circular', 'app-play'])
    button.set_sensitive(bool(app.info or app.source == APPIMAGE))
    button.connect('clicked', lambda *_: page.launch(app))
    return button


def app_options(app, page):
    button = Gtk.MenuButton(icon_name='view-more-horizontal-symbolic', tooltip_text=tr('Options de l’application'),
                            valign=Gtk.Align.END, css_classes=['flat', 'circular', 'app-options'])
    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3,
                   margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
    popover = Gtk.Popover(child=body)
    actions = [(tr('Données et dossiers associés'), lambda: page.show_data(app), False),
               (tr('Retirer des favoris') if page.is_favorite(app) else tr('Ajouter aux favoris'),
                lambda: page.toggle_favorite(app), False),
               (tr('Modifier la catégorie…'), lambda: page.edit_category(app), False)]
    if scanner.update_command(app):
        actions.append((tr('Mettre à jour'), lambda: page.update(app), False))
    if app.source in REMOVABLE:
        actions.append((tr("Retirer l'application ou son raccourci") if app.source == scanner.LOCAL else
                        tr('Désinstaller'), lambda: page.remove(app), True))
    for title, callback, destructive in actions:
        if destructive:
            body.append(Gtk.Separator())
        item = Gtk.Button(label=title, css_classes=['flat', 'destructive-action'] if destructive else ['flat'])
        item.get_child().set_xalign(0)
        item.connect('clicked', lambda _b, cb=callback: (popover.popdown(), cb()))
        body.append(item)
    button.set_popover(popover)
    return button


class AppSection(Gtk.Box):
    def __init__(self, key, apps, mode, page):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.key, self.apps = key, apps
        header = Gtk.Box(spacing=10, css_classes=['category-heading'])
        header.append(Gtk.Image(icon_name=categories.ICONS[key], css_classes=['accent']))
        header.append(Gtk.Label(label=categories.CATEGORIES[key], xalign=0, css_classes=['title-3']))
        self.count = Gtk.Label(label=str(len(apps)), css_classes=['category-count', 'numeric'])
        header.append(self.count)
        header.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True, valign=Gtk.Align.CENTER))
        header.set_tooltip_text(tr('Les applications sont regroupées par catégorie. Chacune apparaît une seule fois ; le filtre inclut aussi ses catégories secondaires.'))
        self.chevron = Gtk.Image(icon_name='pan-down-symbolic')
        header.append(self.chevron)
        self.toggle = Gtk.ToggleButton(child=header, css_classes=['flat', 'category-toggle'])
        self.append(self.toggle)
        if mode == 'grid':
            self.body = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                min_children_per_line=1, max_children_per_line=64, column_spacing=12, row_spacing=12,
                halign=Gtk.Align.START, valign=Gtk.Align.START, css_classes=['app-grid'])
            self.body.set_filter_func(lambda child: page._filter_row(child.get_child()))
            self.body.set_sort_func(lambda a, b: page._sort_rows(a.get_child(), b.get_child()))
            for app in apps:
                self.body.append(AppCard(app, page))
                self.body.get_last_child().set_focusable(False)
        else:
            self.body = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=['boxed-list'])
            self.body.set_filter_func(page._filter_row)
            self.body.set_sort_func(page._sort_rows)
            for app in apps:
                self.body.append(AppRow(app, page))
        self.revealer = Gtk.Revealer(child=self.body, transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
                                     transition_duration=150)
        self.append(self.revealer)
        self.set_expanded(key not in page.collapsed_categories)
        self.toggle.connect('toggled', lambda button: page.set_category_collapsed(key, not button.get_active()))

    def set_expanded(self, expanded):
        self.toggle.set_active(expanded)
        self.toggle.set_tooltip_text(tr('Replier {value0}', value0=categories.CATEGORIES[self.key]) if expanded else
                                     tr('Déplier {value0}', value0=categories.CATEGORIES[self.key]))
        self.toggle.update_state([Gtk.AccessibleState.EXPANDED], [int(expanded)])
        self.revealer.set_reveal_child(expanded)
        self.chevron.set_from_icon_name('pan-down-symbolic' if expanded else 'pan-end-symbolic')


class AppCard(Gtk.Box):
    def __init__(self, app, page):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True,
                         width_request=160, css_classes=['card', 'app-card'])
        self.app = app
        top = Gtk.Box(spacing=8)
        top.append(app_icon(app, 64))
        top.append(Gtk.Box(hexpand=True))
        top.append(Gtk.Label(label=SOURCES[app.source], ellipsize=Pango.EllipsizeMode.END, max_width_chars=10,
                             valign=Gtk.Align.START, css_classes=['pill-tag', f'src-{app.source}']))
        self.append(top)
        self.append(Gtk.Label(label=('★ ' if page.is_favorite(app) else '') + app.name, xalign=0, wrap=True, lines=2, max_width_chars=20,
                               ellipsize=Pango.EllipsizeMode.END, css_classes=['heading', 'app-card-title']))
        category = page.category_labels(app)
        self.append(Gtk.Label(label=category, xalign=0, ellipsize=Pango.EllipsizeMode.END,
                               max_width_chars=20, tooltip_text=category, css_classes=['caption', 'dim-label']))
        detail = ' · '.join([app.version or tr('version inconnue'), GLib.format_size(app.size) if app.size else '—'])
        self.append(Gtk.Label(label=detail, xalign=0, ellipsize=Pango.EllipsizeMode.END,
                               max_width_chars=20, tooltip_text=detail, css_classes=['caption', 'dim-label']))
        note = tr('Mise à jour disponible : {value0}', value0=app.update) if app.update else app.note
        self.append(Gtk.Label(label=note, visible=bool(note), xalign=0, wrap=True, lines=1, max_width_chars=20,
                               ellipsize=Pango.EllipsizeMode.END, tooltip_text=note,
                               css_classes=['caption', 'accent'] if app.update else ['caption', 'dim-label']))
        bottom = Gtk.Box(spacing=8, vexpand=True, valign=Gtk.Align.END)
        bottom.append(app_play(app, page))
        bottom.append(Gtk.Box(hexpand=True))
        bottom.append(app_options(app, page))
        self.append(bottom)


class AppRow(Adw.ActionRow):
    def __init__(self, app: scanner.App, page: AppsPage):
        super().__init__(title=GLib.markup_escape_text(('★ ' if page.is_favorite(app) else '') + app.name), subtitle_lines=2)
        self.app = app
        self.add_css_class('app-row')

        self.add_prefix(app_icon(app, 44))

        details = [d for d in (page.category_labels(app), app.version or tr('version inconnue'), app.note) if d]
        subtitle = GLib.markup_escape_text(" · ".join(details))
        if app.update:
            subtitle += tr('\n<b>→ {value0} disponible</b>', value0=GLib.markup_escape_text(app.update))
        self.set_subtitle(subtitle)

        self.add_suffix(Gtk.Label(label=SOURCES[app.source], valign=Gtk.Align.CENTER,
                                  css_classes=["pill-tag", f"src-{app.source}"]))
        self.add_suffix(Gtk.Label(label=GLib.format_size(app.size) if app.size else "—", width_chars=9, xalign=1,
                                  css_classes=["dim-label", "numeric"]))

        self.add_suffix(app_play(app, page))
        self.add_suffix(app_options(app, page))
