"""Vue graphique des plus gros dossiers personnels."""

from .i18n import _ as tr, number

import threading

from gi.repository import Adw, Gio, GLib, Gtk, Pango

from . import storage
from .widgets import StatCard, icon_tile, page_box, page_scroller, stat_grid


class StorageDialog(Adw.Dialog):
    def __init__(self, window):
        super().__init__(title=tr('Occupation du dossier personnel'), content_width=840, content_height=740)
        self.window = window
        self.generation = 0
        self.busy = False
        self.connect('closed', lambda *_: self._closed())
        header = Adw.HeaderBar()
        self.refresh_button = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text=tr('Recalculer les tailles'))
        self.refresh_button.connect('clicked', lambda *_: self.refresh())
        header.pack_start(self.refresh_button)
        self.stack = Gtk.Stack(vexpand=True)
        self.stack.add_named(Adw.StatusPage(title=tr('Analyse du dossier personnel…'),
            description=tr('Les dossiers cachés sont inclus. Cela peut prendre un moment.'),
            child=Adw.Spinner(width_request=40, height_request=40)), 'loading')
        self.error_page = Adw.StatusPage(title=tr('Analyse impossible'), icon_name='dialog-warning-symbolic',
                                         description=tr('Réessayez avec le bouton Actualiser.'))
        self.stack.add_named(self.error_page, 'error')

        content = page_box()
        self.total_card = StatCard(tr('Espace mesuré'), 'drive-harddisk-symbolic')
        self.count_card = StatCard(tr('Dossiers'), 'folder-symbolic')
        self.largest_card = StatCard(tr('Le plus gros dossier'), 'view-sort-descending-symbolic')
        content.append(stat_grid(self.total_card, self.count_card, self.largest_card))
        self.warning = Gtk.Label(xalign=0, wrap=True, selectable=True, visible=False, css_classes=['warning'])
        content.append(self.warning)
        group = Adw.PreferencesGroup(title=tr('Du plus gros au plus petit'),
            description=tr('Chaque barre indique la part du dossier dans le total mesuré. Les autres disques montés et les cibles des liens symboliques ne sont pas parcourus.'))
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=['boxed-list'])
        group.add(self.list)
        content.append(group)
        self.message = Gtk.Label(xalign=0, wrap=True, selectable=True, css_classes=['dim-label'])
        content.append(self.message)
        self.stack.add_named(page_scroller(content), 'results')
        toolbar = Adw.ToolbarView(content=self.stack)
        toolbar.add_top_bar(header)
        self.set_child(toolbar)
        self.refresh()

    def _closed(self):
        self.generation += 1

    def refresh(self):
        if self.busy:
            return
        self.busy = True
        self.generation += 1
        self.refresh_button.set_sensitive(False)
        self.stack.set_visible_child_name('loading')
        threading.Thread(target=self._analyze, args=(self.generation,), daemon=True).start()

    def _analyze(self, generation):
        try:
            summary, error = storage.analyze(), None
        except ValueError as exc:
            summary, error = None, str(exc)
        GLib.idle_add(self._populate, generation, summary, error)

    def _populate(self, generation, summary, error):
        if generation != self.generation:
            return
        self.busy = False
        self.refresh_button.set_sensitive(True)
        if error:
            self.error_page.set_description(error)
            self.stack.set_visible_child_name('error')
            return
        folders = [entry for entry in summary.entries if not entry.direct_files]
        self.total_card.set(GLib.format_size(summary.total), str(summary.home))
        self.count_card.set(str(len(folders)), tr('dossiers cachés inclus'))
        largest = max(folders, key=lambda entry: entry.size, default=None)
        self.largest_card.set(GLib.format_size(largest.size) if largest else '—',
                              largest.path.name if largest else tr('Aucun dossier'))
        self.warning.set_text(summary.warning)
        self.warning.set_visible(bool(summary.warning))
        self.message.set_text('')
        self.list.remove_all()
        for entry in summary.entries:
            self.list.append(self._row(entry, summary.total))
        if not summary.entries:
            self.message.set_text(tr('Aucun dossier ou fichier à afficher.'))
        self.stack.set_visible_child_name('results')

    def _row(self, entry, total):
        fraction = min(entry.size / total, 1) if total else 0
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                       margin_top=14, margin_bottom=14, margin_start=16, margin_end=16)
        head = Gtk.Box(spacing=12)
        head.append(icon_tile('text-x-generic-symbolic' if entry.direct_files else 'folder-symbolic'))
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
        labels.append(Gtk.Label(label=storage.entry_title(entry), xalign=0, wrap=True, css_classes=['heading']))
        path = Gtk.Label(label=str(entry.path), xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE,
                         max_width_chars=40, css_classes=['caption', 'dim-label'])
        path.set_tooltip_text(str(entry.path))
        labels.append(path)
        head.append(labels)
        head.append(Gtk.Label(label=GLib.format_size(entry.size), valign=Gtk.Align.CENTER,
                              css_classes=['heading', 'numeric']))
        button = Gtk.Button(child=Adw.ButtonContent(icon_name='folder-open-symbolic', label=tr('Ouvrir')),
                            tooltip_text=tr('Ouvrir {value0}', value0=entry.path), valign=Gtk.Align.CENTER)
        button.connect('clicked', lambda *_: self._open(entry.path))
        head.append(button)
        body.append(head)
        bar = Gtk.ProgressBar(fraction=fraction, show_text=True,
                              text=number(tr('{value0:.1%} du total', value0=fraction)))
        body.append(bar)
        return Gtk.ListBoxRow(child=body, activatable=False)

    def _open(self, path):
        try:
            Gio.AppInfo.launch_default_for_uri(path.absolute().as_uri(), None)
        except GLib.Error as error:
            self.message.set_text(tr('Impossible d’ouvrir le dossier : {value0}', value0=error.message))
