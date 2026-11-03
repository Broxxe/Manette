"""Dossiers associés à une application : consulter et lier, sans suppression."""

from .i18n import _ as tr

from pathlib import Path
import threading

from gi.repository import Adw, Gio, GLib, Gtk

from . import app_data


class DataDialog(Adw.Dialog):
    def __init__(self, app, window):
        super().__init__(title=tr('Données de {value0}', value0=app.name), content_width=680, content_height=600)
        self.app, self.window = app, window
        self.generation = 0
        self.connect('closed', lambda *_: self._closed())
        header = Adw.HeaderBar()
        self.add_button = Gtk.Button(label=tr('Associer un dossier…'), css_classes=['suggested-action'])
        self.add_button.connect('clicked', lambda *_: self._select_folder())
        header.pack_end(self.add_button)
        page = Adw.PreferencesPage()
        self.summary = Adw.PreferencesGroup(title=tr('Espace associé'), description=tr('Mesure en cours…'))
        page.add(self.summary)
        app_size = GLib.format_size(app.size) if app.size is not None else tr('inconnue')
        self.summary.add(Adw.ActionRow(title=tr("Taille de l'application"), subtitle=app_size))
        self.folders = Adw.PreferencesGroup(title=tr('Dossiers associés'),
            description=tr('Détection des emplacements standards et dossiers ajoutés manuellement. Certains dossiers peuvent être partagés entre applications. Retirer une association conserve tous les fichiers.'))
        page.add(self.folders)
        self.rows = []
        self.message = Gtk.Label(xalign=0, wrap=True, selectable=True)
        messages = Adw.PreferencesGroup()
        messages.add(self.message)
        page.add(messages)
        view = Adw.ToolbarView(content=page)
        view.add_top_bar(header)
        self.set_child(view)
        self.refresh()

    def _closed(self):
        self.generation += 1

    def refresh(self):
        self.generation += 1
        self.summary.set_description(tr('Mesure en cours…'))
        self.add_button.set_sensitive(False)
        threading.Thread(target=self._measure, args=(self.generation,), daemon=True).start()

    def _measure(self, generation):
        try:
            usages, total, complete = app_data.measure(app_data.discover(self.app))
            error = None
        except (OSError, ValueError) as exc:
            usages, total, complete, error = [], 0, False, str(exc)
        GLib.idle_add(self._populate, generation, usages, total, complete, error)

    def _populate(self, generation, usages, total, complete, error):
        if generation != self.generation:
            return
        self.add_button.set_sensitive(True)
        for row in self.rows:
            self.folders.remove(row)
        self.rows.clear()
        self.summary.set_description(tr('Données associées sur disque : {value0}', value0=GLib.format_size(total)) +
                                    (' · mesure partielle' if not complete else '') if not error else tr('Mesure impossible'))
        self.message.set_text(error or ('' if usages else
            tr('Aucun dossier identifié automatiquement. Vous pouvez en associer un avec le bouton en haut.')))
        for usage in usages:
            folder = usage.folder
            size = GLib.format_size(usage.size) if usage.size is not None else tr('indisponible')
            detail = f'{size} · ' + (tr('détecté automatiquement') if folder.automatic else tr('association personnelle'))
            if usage.included_in is not None:
                detail = tr('Déjà inclus dans {value0}', value0=usage.included_in)
            if not usage.complete:
                detail += ' · dossier absent, illisible ou mesure incomplète'
            row = Adw.ActionRow(title=GLib.markup_escape_text(str(folder.path)),
                                subtitle=GLib.markup_escape_text(detail), title_lines=2)
            open_button = Gtk.Button(icon_name='folder-open-symbolic', tooltip_text=tr('Ouvrir le dossier'),
                                     valign=Gtk.Align.CENTER, sensitive=folder.path.is_dir())
            open_button.connect('clicked', lambda *_, p=folder.path: self._open(p))
            row.add_suffix(open_button)
            if not folder.automatic:
                remove = Gtk.Button(icon_name='list-remove-symbolic', tooltip_text=tr("Retirer l'association (garde les fichiers)"),
                                    valign=Gtk.Align.CENTER)
                remove.connect('clicked', lambda *_, p=folder.path: self._unlink(p))
                row.add_suffix(remove)
            self.folders.add(row)
            self.rows.append(row)

    def _open(self, path):
        try:
            Gio.AppInfo.launch_default_for_uri(path.absolute().as_uri(), None)
        except GLib.Error as error:
            self.message.set_text(tr('Impossible d’ouvrir le dossier : {value0}', value0=error.message))

    def _select_folder(self):
        dialog = Gtk.FileDialog(title=tr('Associer un dossier à {value0}', value0=self.app.name))
        dialog.set_initial_folder(Gio.File.new_for_path(str(Path.home())))
        dialog.select_folder(self.window, None, self._selected)

    def _selected(self, dialog, result):
        try:
            file = dialog.select_folder_finish(result)
        except GLib.Error as error:
            if not error.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                self.message.set_text(error.message)
            return
        path = file.get_path()
        if path is None:
            self.message.set_text(tr('Choisissez un dossier sur cet ordinateur.'))
            return
        try:
            app_data.associate(self.app, Path(path))
        except (OSError, ValueError) as error:
            self.message.set_text(tr('Association impossible : {value0}', value0=error))
            return
        self.refresh()

    def _unlink(self, path):
        try:
            app_data.associate(self.app, path, remove=True)
        except (OSError, ValueError) as error:
            self.message.set_text(tr('Impossible de retirer cette association : {value0}', value0=error))
            return
        self.refresh()
