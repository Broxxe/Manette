"""Search applications, commands, associated folders, actions and settings."""

import threading
from pathlib import Path
from gi.repository import Adw, Gio, GLib, Gtk

from . import app_data, search
from .i18n import _


class SearchDialog(Adw.Dialog):
    def __init__(self, window):
        super().__init__(title=_('Recherche globale'), content_width=760, content_height=640)
        self.window, self.closed = window, False
        self.connect('closed', lambda *_: setattr(self, 'closed', True))
        self.apps = list(window.apps_page.apps)
        self.items = [search.Item(app.name, app.ident, 'app', app, window.apps_page.is_favorite(app)) for app in self.apps]
        self.items += [search.Item(item.name, item.description + ' ' + item.command, 'command', item,
                                  window.custom_page.is_favorite(item)) for item in window.custom_page.items]
        self.items += [search.Item(item.title, item.subtitle, 'system', item) for item in window.system_page.actions]
        self.items += [search.Item(_('Préférences'), _('Langue, apparence, opacité et mises à jour de Manette'), 'navigation', 'settings'),
                       search.Item(_('Historique des opérations'), _('Rapports, erreurs et opérations récentes'), 'navigation', 'history'),
                       search.Item(_('Diagnostic des mises à jour'), _('Comprendre les erreurs de téléchargement et de paquets'), 'navigation', 'diagnostics'),
                       search.Item(_('Ouvrir un fichier…'), _('Installer une application téléchargée ou lancer une AppImage'), 'navigation', 'file')]
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                          margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        self.entry = Gtk.SearchEntry(placeholder_text=_('Applications, commandes, dossiers, réglages…'), hexpand=True)
        self.entry.connect('search-changed', lambda *_: self._render())
        content.append(self.entry)
        self.status = Gtk.Label(xalign=0, wrap=True, css_classes=['caption', 'dim-label'])
        content.append(self.status)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=['boxed-list'])
        self.list.set_placeholder(Gtk.Label(label=_('Aucun résultat.'), margin_top=24, margin_bottom=24))
        content.append(Gtk.ScrolledWindow(child=self.list, vexpand=True,
                                          hscrollbar_policy=Gtk.PolicyType.NEVER))
        toolbar = Adw.ToolbarView(content=content)
        toolbar.add_top_bar(Adw.HeaderBar())
        self.set_child(toolbar)
        self.folder_note = _('Indexation des dossiers associés…')
        self._render()
        self.entry.grab_focus()
        threading.Thread(target=self._folders, daemon=True).start()

    def _folders(self):
        items, seen = [], set()
        errors = False
        for app in self.apps:
            if self.closed:
                return
            try:
                for folder in app_data.discover(app):
                    key = (str(folder.path), app_data.app_key(app))
                    if key not in seen:
                        items.append(search.Item(str(folder.path), app.name, 'folder', folder.path))
                        seen.add(key)
            except (OSError, ValueError):
                errors = True
        GLib.idle_add(self._add_folders, items, errors)

    def _add_folders(self, items, errors):
        if self.closed:
            return
        self.items.extend(items)
        self.folder_note = _('Certains dossiers associés n’ont pas pu être indexés.') if errors else ''
        self._render()

    def _render(self):
        self.list.remove_all()
        query = self.entry.get_text()
        items, count = search.find(self.items, query)
        note = _('Favoris et raccourcis. Saisissez un terme pour rechercher partout.') if not query.strip() else _('Résultats : {value0}', value0=count)
        if count > len(items):
            note += ' · ' + _('Affinez la recherche pour afficher les autres résultats.')
        self.status.set_text(note + ('\n' + self.folder_note if self.folder_note else ''))
        labels = {'app': _('Application'), 'command': _('Commande'), 'system': _('Action système'),
                  'folder': _('Dossier associé'), 'navigation': _('Navigation')}
        icons = {'app': 'application-x-executable-symbolic', 'command': 'utilities-terminal-symbolic',
                 'system': 'computer-symbolic', 'folder': 'folder-symbolic', 'navigation': 'go-next-symbolic'}
        for item in items:
            row = Adw.ActionRow(title=GLib.markup_escape_text(('★ ' if item.favorite else '') + item.title),
                subtitle=GLib.markup_escape_text(labels[item.kind] + ' · ' + item.detail),
                title_lines=1, subtitle_lines=2, activatable=True)
            row.add_prefix(Gtk.Image(icon_name=icons[item.kind]))
            if item.kind == 'app':
                launch = Gtk.Button(icon_name='media-playback-start-symbolic', tooltip_text=_('Lancer'),
                                    valign=Gtk.Align.CENTER, css_classes=['suggested-action', 'circular'],
                                    sensitive=bool(item.target.info or item.target.source == 'appimage'))
                launch.connect('clicked', lambda *_, app=item.target: self._launch(app))
                row.add_suffix(launch)
            row.add_suffix(Gtk.Image(icon_name='go-next-symbolic'))
            row.connect('activated', lambda *_, selected=item: self._activate(selected))
            self.list.append(row)

    def _launch(self, app):
        self.close()
        self.window.apps_page.launch(app)

    def _activate(self, item):
        self.close()
        if item.kind == 'app':
            self.window.stack.set_visible_child_name('apps')
            self.window.apps_page.show_data(item.target)
        elif item.kind == 'command':
            # Preserve normal confirmation and root restrictions.
            self.window.custom_page.run(item.target)
        elif item.kind == 'system':
            self.window.system_page._run(item.target)
        elif item.kind == 'folder':
            try:
                Gio.AppInfo.launch_default_for_uri(Path(item.target).absolute().as_uri(), None)
            except GLib.Error as error:
                self.window.toast(_('Impossible d’ouvrir le dossier : {value0}', value0=error.message))
        elif item.target == 'file':
            self.window.apps_page.open_file()
        else:
            self.window.activate_action('win.' + item.target, None)
