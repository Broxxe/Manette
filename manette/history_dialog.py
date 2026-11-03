"""Operation history, reports and failure explanations."""

from datetime import datetime
import sqlite3
from gi.repository import Adw, GLib, Gtk

from . import diagnostics, history, system
from .i18n import _


def status_label(status):
    return {'running': _('En cours'), 'success': _('Réussie'), 'failed': _('Échec'),
            'stopped': _('Arrêtée'), 'unknown': _('Résultat inconnu'),
            'external': _('Ouverte dans un terminal')}.get(status, _('Résultat inconnu'))


def report(entry):
    return '\n'.join([entry['title'], entry['started'], status_label(entry['status']),
                      entry.get('command', ''), '', entry.get('output', '')])


class ReportDialog(Adw.Dialog):
    def __init__(self, window, entry):
        super().__init__(title=entry['title'], content_width=760, content_height=640)
        header = Adw.HeaderBar()
        copy = Gtk.Button(label=_('Copier le rapport'))
        text = report(entry)
        copy.connect('clicked', lambda *_: self.get_clipboard().set(text))
        header.pack_end(copy)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=16,
                       margin_bottom=16, margin_start=16, margin_end=16)
        if entry['status'] in ('failed', 'stopped', 'unknown'):
            button = Gtk.Button(label=_('Diagnostiquer le problème'), css_classes=['suggested-action'])
            button.connect('clicked', lambda *_: DiagnosticDialog(window, entry.get('output', '')).present(window))
            page.append(button)
        page.append(Gtk.Label(label=_('Les rapports conservent uniquement les 128 derniers Kio de sortie.'),
                              wrap=True, xalign=0, css_classes=['caption', 'dim-label']))
        view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                            wrap_mode=Gtk.WrapMode.WORD_CHAR, vexpand=True)
        view.get_buffer().set_text(text)
        page.append(Gtk.ScrolledWindow(child=view, vexpand=True))
        toolbar = Adw.ToolbarView(content=page)
        toolbar.add_top_bar(header)
        self.set_child(toolbar)


class HistoryDialog(Adw.Dialog):
    def __init__(self, window):
        super().__init__(title=_('Historique des opérations'), content_width=760, content_height=660)
        self.window = window
        header = Adw.HeaderBar()
        refresh = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text=_('Actualiser'))
        refresh.connect('clicked', lambda *_: self.refresh())
        header.pack_start(refresh)
        clear = Gtk.Button(label=_('Effacer l’historique'))
        clear.connect('clicked', lambda *_: window.confirm(_('Effacer l’historique ?'),
            _('Les rapports enregistrés seront supprimés. Les opérations en cours sont conservées.'),
            _('Effacer'), self._clear))
        header.pack_end(clear)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                          margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        content.append(Gtk.Label(label=_('Les 500 dernières opérations sont conservées localement.'),
                                 xalign=0, wrap=True, css_classes=['dim-label']))
        tools = Gtk.Box(spacing=8)
        self.search = Gtk.SearchEntry(placeholder_text=_('Rechercher dans l’historique…'), hexpand=True)
        self.search.connect('search-changed', lambda *_: self._render())
        self.failures = Gtk.ToggleButton(label=_('Échecs uniquement'))
        self.failures.connect('toggled', lambda *_: self._render())
        tools.append(self.search)
        tools.append(self.failures)
        content.append(tools)
        self.message = Gtk.Label(xalign=0, wrap=True, visible=False)
        content.append(self.message)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=['boxed-list'])
        self.list.set_placeholder(Gtk.Label(label=_('Aucune opération à afficher.'), margin_top=24, margin_bottom=24))
        content.append(Gtk.ScrolledWindow(child=self.list, vexpand=True,
                                          hscrollbar_policy=Gtk.PolicyType.NEVER))
        toolbar = Adw.ToolbarView(content=content)
        toolbar.add_top_bar(header)
        self.set_child(toolbar)
        self.items = []
        self.refresh()

    def refresh(self):
        try:
            self.items = history.entries()
            self.message.set_visible(False)
        except (OSError, sqlite3.Error) as error:
            self.message.set_label(_('Historique indisponible : {value0}', value0=error))
            self.message.set_visible(True)
        self._render()

    def _render(self):
        self.list.remove_all()
        query = self.search.get_text().strip().casefold()
        for item in self.items:
            if self.failures.get_active() and item['status'] not in ('failed', 'stopped', 'unknown'):
                continue
            if query and query not in (item['title'] + ' ' + item['command'] + ' ' + item['output']).casefold():
                continue
            date = datetime.fromisoformat(item['started']).astimezone().strftime('%x %X')
            row = Adw.ActionRow(title=GLib.markup_escape_text(item['title']),
                subtitle=GLib.markup_escape_text(f"{date} · {status_label(item['status'])}"), activatable=True)
            row.add_prefix(Gtk.Image(icon_name='emblem-ok-symbolic' if item['status'] == 'success' else
                                     'dialog-warning-symbolic' if item['status'] == 'failed' else 'document-open-recent-symbolic'))
            row.add_suffix(Gtk.Image(icon_name='go-next-symbolic'))
            row.connect('activated', lambda *_, entry=item: ReportDialog(self.window, entry).present(self.window))
            self.list.append(row)

    def _clear(self):
        try:
            history.clear()
        except (OSError, sqlite3.Error) as error:
            self.window.toast(_('Historique indisponible : {value0}', value0=error))
        self.refresh()


class DiagnosticDialog(Adw.Dialog):
    def __init__(self, window, output=None):
        super().__init__(title=_('Diagnostic des mises à jour'), content_width=680, content_height=580)
        if output is None:
            try:
                entry = next((item for item in history.entries() if item['status'] == 'failed'), None)
                output = entry['output'] if entry else ''
            except (OSError, sqlite3.Error):
                output = ''
        header = Adw.HeaderBar()
        copy = Gtk.Button(label=_('Copier le rapport'))
        copy.connect('clicked', lambda *_: self.get_clipboard().set(output))
        header.pack_end(copy)
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title=_('Analyse du journal'),
            description=_('Les causes proposées sont des pistes fondées sur les messages du journal. Aucune réparation n’est lancée automatiquement.'))
        page.add(group)
        for finding in diagnostics.analyze(output):
            row = Adw.ActionRow(title=finding.title, subtitle=finding.explanation, subtitle_lines=0)
            group.add(row)
            if finding.action:
                button = Gtk.Button(label=_('Examiner les dossiers') if finding.action == 'storage'
                                    else _('Vérifier les mises à jour'), margin_top=8, margin_bottom=8)
                button.connect('clicked', lambda *_, action=finding.action: self._action(window, action))
                group.add(button)
        if not output:
            group.set_description(_('Aucun journal d’échec disponible. Lancez une vérification ou ouvrez le rapport d’une opération dans l’historique.'))
        toolbar = Adw.ToolbarView(content=page)
        toolbar.add_top_bar(header)
        self.set_child(toolbar)

    def _action(self, window, action):
        if action == 'storage':
            from .storage_dialog import StorageDialog
            StorageDialog(window).present(window)
        else:
            window.confirm(_('Vérifier les mises à jour ?'),
                _('Les listes de paquets seront actualisées. Une autorisation administrateur peut être demandée. Aucune mise à jour ne sera installée.'),
                _('Vérifier'), lambda: window.run(['bash', '-c', system.CHECK_UPDATES],
                    _('Vérifier les mises à jour'), on_done=lambda ok: window.refresh()), destructive=False)
