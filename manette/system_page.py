"""Page Système : état de la machine, disques et actions toutes prêtes."""

from .i18n import _ as tr

import threading
from dataclasses import replace
from pathlib import Path

from gi.repository import Adw, Gio, GLib, Gtk

from . import scanner, system
from .storage_dialog import StorageDialog
from .widgets import StatCard, icon_tile, page_box, page_scroller, stat_grid, usage_bar


class SystemPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.measured_rows = []

        content = page_box()
        self.card_os = StatCard(tr('Système'), "computer-symbolic")
        self.card_uptime = StatCard(tr('Allumé depuis'), "preferences-system-time-symbolic")
        self.card_mem = StatCard(tr('Mémoire'), "media-flash-symbolic")
        self.card_disk = StatCard(tr('Espace libre'), "drive-harddisk-symbolic")
        content.append(stat_grid(self.card_os, self.card_uptime, self.card_mem, self.card_disk))

        self.disk_group = Adw.PreferencesGroup(title=tr('Disques'), description=tr("Cliquez sur un disque pour l'ouvrir"))
        self.disk_rows = []
        content.append(self.disk_group)

        for title, description, actions in system.action_groups():
            group = Adw.PreferencesGroup(title=title, description=description)
            for action in actions:
                group.add(self._action_row(action))
            content.append(group)

        self.append(page_scroller(content))

    def _action_row(self, action: system.Action) -> Adw.ActionRow:
        row = Adw.ActionRow(title=action.title, subtitle=action.subtitle)
        row.add_prefix(icon_tile(action.icon))
        if action.root:
            row.add_suffix(Gtk.Image(icon_name="changes-prevent-symbolic", tooltip_text=tr('Autorisation administrateur requise'),
                                     css_classes=["dim-label"]))
        button = Gtk.Button(icon_name="folder-open-symbolic" if action.view else "media-playback-start-symbolic",
                            tooltip_text=tr('Afficher le résumé') if action.view else tr('Lancer'),
                            valign=Gtk.Align.CENTER, css_classes=["flat", "circular"])
        button.connect("clicked", lambda *_: self._run(action))
        row.add_suffix(button)
        row.set_activatable_widget(button)
        if action.measure:
            self.measured_rows.append((row, action))
        return row

    def _run(self, action: system.Action):
        if action.view == "storage":
            StorageDialog(self.window).present(self.window)
            return
        if action.preview_autoremove:
            threading.Thread(target=self._preview_autoremove, args=(action,), daemon=True).start()
            return
        def go():
            self.window.run(["bash", "-c", action.command], action.title, action.display or action.command.strip(),
                            on_done=lambda ok: self._after(action),
                            space_paths=["/", "/var/cache/apt/archives", "/var/lib/flatpak", Path.home()]
                            if action.check_space else None)
        if action.confirm:
            self.window.confirm(f"{action.title} ?", action.confirmation or action.subtitle + ".",
                                tr('Supprimer') if action.destructive else tr('Lancer'), go,
                                destructive=action.destructive)
        else:
            go()

    def _preview_autoremove(self, action):
        try:
            packages, error = scanner.apt_removal_preview("autoremove"), None
        except scanner.RemovalPreviewError as exc:
            packages, error = None, str(exc)
        GLib.idle_add(self._confirm_autoremove, action, packages, error)

    def _confirm_autoremove(self, action, packages, error):
        if error or packages is None:
            self.window.confirm(tr('Nettoyage APT bloqué'), (error or tr('Simulation indisponible')) +
                                tr("\n\nAucune suppression n'a été lancée."), tr('Compris'), lambda: None,
                                destructive=False)
            return
        if not packages:
            self.window.toast(tr("APT n'a trouvé aucun paquet à supprimer."))
            return
        body = tr('APT propose de supprimer ces paquets :\n\n') + "\n".join(f"• {pkg}" for pkg in packages)
        body += tr('\n\nVérifiez cette liste avant de confirmer.')
        self._run(replace(action, preview_autoremove=False, confirmation=body))

    def _after(self, action):
        self.refresh()
        if action.rescan:
            self.window.apps_page.scan()

    # --- Rafraîchissement -------------------------------------------------

    def refresh(self):
        info = system.overview()
        self.card_os.set(info["os"], tr('Noyau {value0}', value0=info['kernel']))
        self.card_uptime.set(info["uptime"], info["host"])
        self.card_mem.set(f"{GLib.format_size(info['mem_used'])}",
                          tr('utilisés sur {value0}', value0=GLib.format_size(info['mem_total'])), info["mem_fraction"])

        disks = system.disks()
        for row in self.disk_rows:
            self.disk_group.remove(row)
        self.disk_rows = [self._disk_row(d) for d in disks]
        for row in self.disk_rows:
            self.disk_group.add(row)
        if root := next((d for d in disks if d.mount == "/"), disks[0] if disks else None):
            self.card_disk.set(GLib.format_size(root.free), tr('sur {value0} ({value1})', value0=GLib.format_size(root.total), value1=root.label),
                               root.used / root.total)

        threading.Thread(target=self._measure, daemon=True).start()

    def _disk_row(self, disk: system.Disk) -> Adw.ActionRow:
        row = Adw.ActionRow(title=disk.label, subtitle=f"{disk.mount} · {disk.device}", activatable=True)
        row.add_prefix(icon_tile("drive-harddisk-symbolic"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.CENTER, width_request=240)
        box.append(Gtk.Label(label=tr('{value0} libres sur {value1}', value0=GLib.format_size(disk.free), value1=GLib.format_size(disk.total)),
                             xalign=1, css_classes=["caption", "numeric"]))
        box.append(usage_bar(disk.used / disk.total))
        row.add_suffix(box)
        row.connect("activated", lambda *_: Gio.AppInfo.launch_default_for_uri(
            GLib.filename_to_uri(disk.mount, None), None))
        return row

    def _measure(self):
        for row, action in self.measured_rows:
            try:
                size = action.measure()
            except OSError:
                size = None
            if size is not None:
                text = tr('{value0} · <b>{value1}</b> à récupérer', value0=action.subtitle, value1=GLib.format_size(size)) if size else \
                    tr('{value0} · rien à récupérer', value0=action.subtitle)
                GLib.idle_add(row.set_subtitle, text)
