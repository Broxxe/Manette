"""Asynchronous preflight, before a package command or privilege prompt."""

import threading
from gi.repository import Adw, GLib, Gtk

from . import space
from .i18n import _
from .widgets import usage_bar


class SpaceDialog(Adw.Dialog):
    def __init__(self, window, request, paths, proceed):
        super().__init__(title=_('Espace avant installation'), content_width=640, content_height=540)
        self.window, self.request, self.paths, self.proceed = window, request, paths, proceed
        self.closed = False
        self.connect('closed', self._closed)
        header = Adw.HeaderBar()
        self.start_button = Gtk.Button(label=_('Continuer'), sensitive=False, css_classes=['suggested-action'])
        self.start_button.connect('clicked', self._proceed)
        header.pack_end(self.start_button)
        self.page = Adw.PreferencesPage()
        self.summary = Adw.PreferencesGroup(title=_('Calcul de l’espace nécessaire…'),
            description=_('Lecture des métadonnées disponibles, sans installation ni modification des paquets.'))
        self.page.add(self.summary)
        self.disk_group = Adw.PreferencesGroup(title=_('Espace disponible par disque'))
        self.page.add(self.disk_group)
        self.disk_rows = []
        actions = Gtk.Box(spacing=8, margin_top=12)
        cleanup = Gtk.Button(label=_('Examiner les dossiers'), hexpand=True)
        cleanup.connect('clicked', self._storage)
        self.refresh_button = Gtk.Button(label=_('Recalculer'))
        self.refresh_button.connect('clicked', lambda *_: self._calculate())
        actions.append(cleanup)
        actions.append(self.refresh_button)
        action_group = Adw.PreferencesGroup()
        action_group.add(actions)
        self.page.add(action_group)
        view = Adw.ToolbarView(content=self.page)
        view.add_top_bar(header)
        self.set_child(view)
        self.generation = 0
        self._calculate()

    def _closed(self, *unused):
        self.closed = True
        self.window._space_check_pending = False

    def _calculate(self):
        self.generation += 1
        self.start_button.set_sensitive(False)
        self.refresh_button.set_sensitive(False)
        self.summary.set_title(_('Calcul de l’espace nécessaire…'))
        threading.Thread(target=self._work, args=(self.generation,), daemon=True).start()

    def _work(self, generation):
        try:
            estimate = space.inspect(self.request, self.paths)
        except Exception as error:
            GLib.idle_add(self._failed, generation, str(error))
            return
        GLib.idle_add(self._populate, generation, estimate)

    def _failed(self, generation, error):
        if self.closed or generation != self.generation:
            return
        self.summary.set_title(_('Mesure impossible'))
        self.summary.set_description(error)
        self.refresh_button.set_sensitive(True)

    def _populate(self, generation, estimate):
        if self.closed or generation != self.generation:
            return
        self.estimate = estimate
        self.refresh_button.set_sensitive(True)
        details = []
        if estimate.download is not None:
            details.append(_('Téléchargement APT : {value0}', value0=GLib.format_size(estimate.download)))
            details.append(_('Paquets à décompresser : {value0}', value0=GLib.format_size(estimate.unpacked)))
            details.append(_('Augmentation nette estimée : {value0}', value0=GLib.format_size(estimate.net)))
            details.append(_('Le contrôle prévoit les nouveaux paquets décompressés, les téléchargements et une marge de 512 Mio par disque.'))
            details.append(_('Estimation fondée sur les listes APT locales. Les scripts d’installation peuvent utiliser de l’espace supplémentaire.'))
        if estimate.partial:
            details.append(_('Estimation partielle : la taille des paquets Snap, Flatpak ou des sources non résolues est inconnue. Prévoyez de la place supplémentaire.'))
        if estimate.note:
            details.append(estimate.note)
        self.summary.set_title(_('Espace insuffisant') if estimate.blocked else _('Vérification terminée'))
        self.summary.set_description('\n\n'.join(details))
        for row in self.disk_rows:
            self.disk_group.remove(row)
        self.disk_rows.clear()
        for fs in estimate.filesystems:
            free = GLib.format_size(fs.free) if fs.free is not None else _('Inconnu')
            detail = _('Libre : {value0} · besoin calculé : {value1}',
                       value0=free, value1=GLib.format_size(fs.required)) if estimate.download is not None else _('Libre : {value0} · besoin inconnu', value0=free)
            row = Adw.ActionRow(title=GLib.markup_escape_text(' · '.join(map(str, fs.paths))),
                                subtitle=GLib.markup_escape_text(detail), title_lines=2)
            if fs.insufficient or fs.free is None or (estimate.partial and fs.free < 5 * 1024**3):
                row.add_css_class('warning')
            if fs.free is not None and fs.required:
                row.add_suffix(usage_bar(min(1, fs.required / max(1, fs.free))))
            self.disk_group.add(row)
            self.disk_rows.append(row)
        self.start_button.set_label(_('Continuer avec une estimation partielle') if estimate.partial else _('Installer'))
        self.start_button.set_sensitive(not estimate.blocked)

    def _storage(self, *unused):
        from .storage_dialog import StorageDialog
        StorageDialog(self.window).present(self.window)

    def _proceed(self, *unused):
        # Recheck disks at click time, after a possibly lengthy review/cleanup.
        if self.estimate.blocked:
            return
        for fs in self.estimate.filesystems:
            if fs.required:
                try:
                    import shutil
                    if shutil.disk_usage(fs.path).free < fs.required:
                        self._calculate()
                        return
                except OSError:
                    self._calculate()
                    return
        # Adw.Dialog's closed signal may arrive after its closing animation.
        # Release the gate now so the confirmed operation can start immediately.
        self.window._space_check_pending = False
        self.close()
        self.proceed()
