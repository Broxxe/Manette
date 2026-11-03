"""Page Moniteur : processeur, mémoire, carte graphique et applications en direct."""

from .i18n import _ as tr, number

import subprocess
import threading
from collections import deque

from gi.repository import Adw, GLib, Gsk, Gtk

from . import monitor
from .widgets import StatCard, page_box, page_scroller, plural, stat_grid, usage_bar

TICK_MS = 1500
APPS_EVERY = 3  # la mémoire par app est plus coûteuse à lire : un tour sur trois


class Sparkline(Gtk.Widget):
    """Petite courbe de l'historique, dessinée avec GSK (pas besoin de cairo)."""

    def __init__(self, length=60):
        super().__init__(height_request=44, hexpand=True, margin_top=4)
        self.values = deque([0.0] * length, maxlen=length)

    def push(self, value):
        self.values.append(max(0.0, min(1.0, value)))
        self.queue_draw()

    def do_snapshot(self, snapshot):
        width, height = self.get_width(), self.get_height()
        if width < 2:
            return
        accent = Adw.StyleManager.get_default().get_accent_color_rgba()
        step = width / (len(self.values) - 1)
        points = [(i * step, height - 1 - v * (height - 3)) for i, v in enumerate(self.values)]

        area = Gsk.PathBuilder.new()
        area.move_to(0, height)
        for x, y in points:
            area.line_to(x, y)
        area.line_to(width, height)
        area.close()
        fill = accent.copy()
        fill.alpha = 0.16
        snapshot.append_fill(area.to_path(), Gsk.FillRule.WINDING, fill)

        line = Gsk.PathBuilder.new()
        line.move_to(*points[0])
        for x, y in points[1:]:
            line.line_to(x, y)
        stroke = Gsk.Stroke.new(2)
        stroke.set_line_join(Gsk.LineJoin.ROUND)
        snapshot.append_stroke(line.to_path(), stroke, accent)


class LiveCard(StatCard):
    def __init__(self, caption, icon_name):
        super().__init__(caption, icon_name)
        self.spark = Sparkline()
        self.append(self.spark)


class MonitorPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.cpu = monitor.CpuSampler()
        self.apps = monitor.AppSampler()
        self.timer = None
        self.working = False
        self.tick = 0
        self.app_rows: dict[str, AppUsageRow] = {}

        content = page_box()
        self.card_cpu = LiveCard(tr('Processeur'), "computer-chip-symbolic")
        self.card_mem = LiveCard(tr('Mémoire'), "media-flash-symbolic")
        self.card_gpu = LiveCard(tr('Carte graphique'), "video-display-symbolic")
        self.card_vram = LiveCard(tr('Mémoire vidéo'), "drive-harddisk-solidstate-symbolic")
        self.cards = stat_grid(self.card_cpu, self.card_mem, self.card_gpu, self.card_vram)
        content.append(self.cards)

        self.cpu_group = Adw.PreferencesGroup(title=tr('Processeur'), description=monitor.cpu_model())
        self.cores = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, min_children_per_line=1,
                                 max_children_per_line=64, column_spacing=8, row_spacing=12)
        self.core_bars = {}
        self.core_layout = None
        cores_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["card"], margin_top=0)
        cores_card.append(self.cores)
        self.cores.set_margin_top(16)
        self.cores.set_margin_bottom(14)
        self.cores.set_margin_start(14)
        self.cores.set_margin_end(14)
        self.cores.set_hexpand(True)
        self.cpu_legend = Gtk.Label(xalign=0, wrap=True, margin_start=16, margin_end=16, margin_bottom=14,
            label=tr('Chaque barre représente un processeur logique.'), css_classes=['caption', 'dim-label'])
        cores_card.append(self.cpu_legend)
        self.cpu_group.add(cores_card)
        content.append(self.cpu_group)

        self.gpu_group = Adw.PreferencesGroup(title=tr('Carte graphique'))
        self.gpu_rows = {}
        for key, title, icon in (("temp", tr('Température'), "weather-clear-symbolic"),
                                 ("power", tr('Consommation'), "battery-full-charging-symbolic"),
                                 ("fan", tr('Ventilateur'), "weather-windy-symbolic"),
                                 ("clock", tr('Fréquence'), "speedometer-symbolic")):
            row = Adw.ActionRow(title=title)
            row.add_prefix(Gtk.Image(icon_name=icon, css_classes=["dim-label"]))
            label = Gtk.Label(css_classes=["numeric"])
            row.add_suffix(label)
            self.gpu_group.add(row)
            self.gpu_rows[key] = label
        content.append(self.gpu_group)

        apps_group = Adw.PreferencesGroup(title=tr('Applications'),
                                          description=tr('Mémoire et processeur utilisés par chaque application'))
        self.app_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        self.app_list.set_sort_func(lambda a, b: b.usage.memory - a.usage.memory)
        self.app_list.set_placeholder(Gtk.Label(label=tr('Mesure en cours…'), margin_top=18, margin_bottom=18,
                                                css_classes=["dim-label"]))
        apps_group.add(self.app_list)
        content.append(apps_group)

        self.append(page_scroller(content))

    # --- Rafraîchissement, seulement quand l'onglet est affiché -----------

    def start(self):
        if self.timer is None:
            self.tick = 0
            self._tick()
            self.timer = GLib.timeout_add(TICK_MS, self._tick)

    def stop(self):
        if self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None

    def _tick(self):
        if not self.working:
            self.working = True
            with_apps = self.tick % APPS_EVERY == 0
            self.tick += 1
            threading.Thread(target=self._sample, args=(with_apps,), daemon=True).start()
        return True

    def _sample(self, with_apps):
        data = {"cpu": self.cpu.sample(), "freq": monitor.cpu_frequency(), "temp": monitor.cpu_temperature(),
                "mem": monitor.memory(), "gpus": monitor.gpus()}
        data['cpu_ids'], data['cpu_topology'] = self.cpu.cpu_ids, self.cpu.topology
        if with_apps:
            data["apps"] = self.apps.sample()
        GLib.idle_add(self._update, data)

    def _update(self, data):
        self.working = False
        total, cores = data["cpu"]
        details = [f"{data['temp']:.0f} °C" if data["temp"] is not None else "",
                   number(f"{data['freq']:.2f} GHz") if data["freq"] else ""]
        self.card_cpu.set(number(f"{total:.0%}"), " · ".join(d for d in details if d))
        self.card_cpu.spark.push(total)
        ids = data.get('cpu_ids', tuple(range(len(cores))))
        self._update_cores(cores, ids, data.get('cpu_topology', monitor.CpuTopology(tuple((ident,) for ident in ids), False)))

        mem = data["mem"]
        self.card_mem.set(GLib.format_size(mem.used), tr('sur {value0} · {value1} disponibles', value0=GLib.format_size(mem.total), value1=GLib.format_size(mem.available)))
        self.card_mem.spark.push(mem.used / mem.total if mem.total else 0)

        gpu = data["gpus"][0] if data["gpus"] else None
        for widget in (self.card_gpu.get_parent(), self.card_vram.get_parent(), self.gpu_group):
            widget.set_visible(gpu is not None)
        if gpu:
            self._update_gpu(gpu)
        if "apps" in data:
            self._update_apps(data["apps"])

    def _update_cores(self, cores, ids, topology):
        layout = (ids, topology)
        if layout != self.core_layout:
            self.core_layout = layout
            self.cores.remove_all()
            self.core_bars = {}
            for index, members in enumerate(topology.groups, 1):
                group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                                css_classes=['cpu-physical-core'] if topology.known else [])
                columns = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
                for ident in members:
                    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, halign=Gtk.Align.CENTER)
                    bar = usage_bar()
                    bar.set_orientation(Gtk.Orientation.VERTICAL)
                    bar.set_inverted(True)
                    bar.set_size_request(10, 56)
                    bar.set_halign(Gtk.Align.CENTER)
                    box.append(bar)
                    box.append(Gtk.Label(label=str(ident + 1), css_classes=['caption', 'dim-label', 'numeric']))
                    columns.append(box)
                    self.core_bars[ident] = (bar, index)
                group.append(columns)
                if topology.known:
                    group.append(Gtk.Label(label=tr('Cœur {value0}', value0=index),
                                           css_classes=['caption', 'dim-label']))
                self.cores.append(group)
                self.cores.get_last_child().set_focusable(False)
            logical_label = tr('processeur logique') if len(ids) == 1 else tr('processeurs logiques')
            summary = f'{len(ids)} {logical_label}'
            if topology.known:
                physical_label = tr('cœur physique') if topology.physical_count == 1 else tr('cœurs physiques')
                summary = f'{topology.physical_count} {physical_label} · {summary}'
            else:
                summary += ' · ' + tr('topologie physique indisponible')
            # The counts describe the topology exposed by Linux, including in VMs.
            self.cpu_group.set_description(monitor.cpu_model() + '\n' + summary)
            self.cpu_legend.set_label(tr('Chaque barre représente un processeur logique. Les barres d’un même cœur physique sont regroupées.')
                                     if topology.known else tr('Chaque barre représente un processeur logique.'))
        for ident, value in zip(ids, cores):
            bar, core = self.core_bars[ident]
            bar.set_value(value)
            label = tr('Cœur physique {value0} · processeur logique {value1} : {value2}',
                       value0=core, value1=ident + 1, value2=number(f'{value:.0%}')) if topology.known else \
                    tr('Processeur logique {value0} : {value1}', value0=ident + 1, value1=number(f'{value:.0%}'))
            bar.set_tooltip_text(label)
            bar.update_property([Gtk.AccessibleProperty.LABEL], [label])

    def _update_gpu(self, gpu: monitor.Gpu):
        self.gpu_group.set_description(gpu.name)
        usage = gpu.usage or 0
        temp = f"{gpu.temperature:.0f} °C" if gpu.temperature is not None else ""
        power = f"{gpu.power:.0f} W" if gpu.power is not None else ""
        self.card_gpu.set(number(f"{usage:.0%}"), " · ".join(d for d in (temp, power) if d))
        self.card_gpu.spark.push(usage)
        if gpu.mem_used is not None and gpu.mem_total:
            self.card_vram.set(GLib.format_size(gpu.mem_used), tr('sur {value0}', value0=GLib.format_size(gpu.mem_total)))
            self.card_vram.spark.push(gpu.mem_used / gpu.mem_total)

        self.gpu_rows["temp"].set_label(temp or "—")
        if gpu.power is not None and gpu.power_limit:
            self.gpu_rows["power"].set_label(tr('{value0:.0f} W sur {value1:.0f} W max', value0=gpu.power, value1=gpu.power_limit))
        else:
            self.gpu_rows["power"].set_label(power or "—")
        if gpu.fan is not None:
            self.gpu_rows["fan"].set_label(tr("à l'arrêt") if gpu.fan == 0 else number(f"{gpu.fan:.0%}"))
        else:
            self.gpu_rows["fan"].set_label("—")
        self.gpu_rows["clock"].set_label(f"{gpu.clock} MHz" if gpu.clock else "—")

    def _update_apps(self, apps):
        seen = set()
        for usage in apps:
            if usage.memory < 5 * 2**20 and usage.cpu < 0.005:
                continue  # les miettes encombrent plus qu'elles n'informent
            seen.add(usage.key)
            if row := self.app_rows.get(usage.key):
                row.update(usage)
            else:
                row = self.app_rows[usage.key] = AppUsageRow(usage, self)
                self.app_list.append(row)
        for key in list(self.app_rows):
            if key not in seen:
                self.app_list.remove(self.app_rows.pop(key))
        self.app_list.invalidate_sort()

    def close_app(self, usage: monitor.AppUsage):
        if not usage.units:
            return
        def go():
            threading.Thread(target=self._close_app, args=(usage,), daemon=True).start()
        self.window.confirm(tr('Fermer {value0} ?', value0=usage.name),
                            tr("Ses {value0} processus seront arrêtés. Ce qui n'est pas enregistré sera perdu.", value0=usage.processes),
                            tr('Fermer'), go)

    def _close_app(self, usage):
        try:
            result = subprocess.run(["systemctl", "--user", "stop", *usage.units],
                                    capture_output=True, text=True, timeout=30)
            if result.returncode:
                detail = result.stderr.strip() or tr('code {value0}', value0=result.returncode)
                message = tr('Impossible de fermer {value0} : {value1}', value0=usage.name, value1=detail)
            else:
                message = tr('{value0} est fermée', value0=usage.name)
        except subprocess.TimeoutExpired:
            message = tr('Fermeture de {value0} non confirmée : délai dépassé.', value0=usage.name)
        except OSError as error:
            message = tr('Impossible de fermer {value0} : {value1}', value0=usage.name, value1=error)
        GLib.idle_add(self.window.toast, message)


class AppUsageRow(Adw.ActionRow):
    def __init__(self, usage: monitor.AppUsage, page: MonitorPage):
        super().__init__()
        icon = Gtk.Image(pixel_size=32, css_classes=["icon-dropshadow"])
        if usage.icon:
            icon.set_from_gicon(usage.icon)
        self.add_prefix(icon)
        self.cpu = Gtk.Label(width_chars=6, xalign=1, css_classes=["numeric", "dim-label"], tooltip_text=tr('Processeur'))
        self.mem = Gtk.Label(width_chars=9, xalign=1, css_classes=["numeric", "heading"], tooltip_text=tr('Mémoire'))
        self.add_suffix(self.cpu)
        self.add_suffix(self.mem)
        close = Gtk.Button(icon_name="window-close-symbolic", tooltip_text=tr("Fermer l'application"),
                           valign=Gtk.Align.CENTER, css_classes=["flat", "circular", "remove-button"],
                           sensitive=bool(usage.units), opacity=1 if usage.units else 0)
        close.connect("clicked", lambda *_: page.close_app(self.usage))
        self.add_suffix(close)
        self.update(usage)

    def update(self, usage: monitor.AppUsage):
        self.usage = usage
        self.set_title(GLib.markup_escape_text(usage.name))
        self.set_subtitle(plural(usage.processes, tr('processus', context='singular'), tr('processus')))
        self.cpu.set_label(number(f"{usage.cpu:.0%}") if usage.cpu >= 0.005 else "—")
        self.mem.set_label(GLib.format_size(usage.memory))
