"""Page Moniteur : processeur, mémoire, carte graphique et applications en direct."""

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
        self.card_cpu = LiveCard("Processeur", "computer-chip-symbolic")
        self.card_mem = LiveCard("Mémoire", "media-flash-symbolic")
        self.card_gpu = LiveCard("Carte graphique", "video-display-symbolic")
        self.card_vram = LiveCard("Mémoire vidéo", "drive-harddisk-solidstate-symbolic")
        self.cards = stat_grid(self.card_cpu, self.card_mem, self.card_gpu, self.card_vram)
        content.append(self.cards)

        self.cpu_group = Adw.PreferencesGroup(title="Processeur", description=monitor.cpu_model())
        self.cores = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, min_children_per_line=8,
                                 max_children_per_line=16, column_spacing=6, row_spacing=12)
        self.core_bars = []
        cores_card = Gtk.Box(css_classes=["card"], margin_top=0)
        cores_card.append(self.cores)
        self.cores.set_margin_top(16)
        self.cores.set_margin_bottom(14)
        self.cores.set_margin_start(14)
        self.cores.set_margin_end(14)
        self.cores.set_hexpand(True)
        self.cpu_group.add(cores_card)
        content.append(self.cpu_group)

        self.gpu_group = Adw.PreferencesGroup(title="Carte graphique")
        self.gpu_rows = {}
        for key, title, icon in (("temp", "Température", "weather-clear-symbolic"),
                                 ("power", "Consommation", "battery-full-charging-symbolic"),
                                 ("fan", "Ventilateur", "weather-windy-symbolic"),
                                 ("clock", "Fréquence", "speedometer-symbolic")):
            row = Adw.ActionRow(title=title)
            row.add_prefix(Gtk.Image(icon_name=icon, css_classes=["dim-label"]))
            label = Gtk.Label(css_classes=["numeric"])
            row.add_suffix(label)
            self.gpu_group.add(row)
            self.gpu_rows[key] = label
        content.append(self.gpu_group)

        apps_group = Adw.PreferencesGroup(title="Applications",
                                          description="Mémoire et processeur utilisés par chaque application")
        self.app_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        self.app_list.set_sort_func(lambda a, b: b.usage.memory - a.usage.memory)
        self.app_list.set_placeholder(Gtk.Label(label="Mesure en cours…", margin_top=18, margin_bottom=18,
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
        if with_apps:
            data["apps"] = self.apps.sample()
        GLib.idle_add(self._update, data)

    def _update(self, data):
        self.working = False
        total, cores = data["cpu"]
        details = [f"{data['temp']:.0f} °C" if data["temp"] is not None else "",
                   f"{data['freq']:.2f} GHz".replace(".", ",") if data["freq"] else ""]
        self.card_cpu.set(f"{total:.0%}".replace("%", " %"), " · ".join(d for d in details if d))
        self.card_cpu.spark.push(total)
        self._update_cores(cores)

        mem = data["mem"]
        self.card_mem.set(GLib.format_size(mem.used), f"sur {GLib.format_size(mem.total)} · "
                          f"{GLib.format_size(mem.available)} disponibles")
        self.card_mem.spark.push(mem.used / mem.total if mem.total else 0)

        gpu = data["gpus"][0] if data["gpus"] else None
        for widget in (self.card_gpu.get_parent(), self.card_vram.get_parent(), self.gpu_group):
            widget.set_visible(gpu is not None)
        if gpu:
            self._update_gpu(gpu)
        if "apps" in data:
            self._update_apps(data["apps"])

    def _update_cores(self, cores):
        if len(self.core_bars) != len(cores):
            self.cores.remove_all()
            self.core_bars = []
            for i in range(len(cores)):
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, halign=Gtk.Align.CENTER)
                bar = usage_bar()
                bar.set_orientation(Gtk.Orientation.VERTICAL)
                bar.set_inverted(True)
                bar.set_size_request(10, 56)
                bar.set_halign(Gtk.Align.CENTER)
                box.append(bar)
                box.append(Gtk.Label(label=str(i + 1), css_classes=["caption", "dim-label", "numeric"]))
                self.cores.append(box)
                self.cores.get_last_child().set_focusable(False)
                self.core_bars.append(bar)
        for bar, value in zip(self.core_bars, cores):
            bar.set_value(value)
            bar.set_tooltip_text(f"{value:.0%}".replace("%", " %"))

    def _update_gpu(self, gpu: monitor.Gpu):
        self.gpu_group.set_description(gpu.name)
        usage = gpu.usage or 0
        temp = f"{gpu.temperature:.0f} °C" if gpu.temperature is not None else ""
        power = f"{gpu.power:.0f} W" if gpu.power is not None else ""
        self.card_gpu.set(f"{usage:.0%}".replace("%", " %"), " · ".join(d for d in (temp, power) if d))
        self.card_gpu.spark.push(usage)
        if gpu.mem_used is not None and gpu.mem_total:
            self.card_vram.set(GLib.format_size(gpu.mem_used), f"sur {GLib.format_size(gpu.mem_total)}")
            self.card_vram.spark.push(gpu.mem_used / gpu.mem_total)

        self.gpu_rows["temp"].set_label(temp or "—")
        if gpu.power is not None and gpu.power_limit:
            self.gpu_rows["power"].set_label(f"{gpu.power:.0f} W sur {gpu.power_limit:.0f} W max")
        else:
            self.gpu_rows["power"].set_label(power or "—")
        if gpu.fan is not None:
            self.gpu_rows["fan"].set_label("à l'arrêt" if gpu.fan == 0 else f"{gpu.fan:.0%}".replace("%", " %"))
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
        self.window.confirm(f"Fermer {usage.name} ?",
                            f"Ses {usage.processes} processus seront arrêtés. Ce qui n'est pas enregistré sera perdu.",
                            "Fermer", go)

    def _close_app(self, usage):
        try:
            result = subprocess.run(["systemctl", "--user", "stop", *usage.units],
                                    capture_output=True, text=True, timeout=30)
            if result.returncode:
                detail = result.stderr.strip() or f"code {result.returncode}"
                message = f"Impossible de fermer {usage.name} : {detail}"
            else:
                message = f"{usage.name} est fermée"
        except subprocess.TimeoutExpired:
            message = f"Fermeture de {usage.name} non confirmée : délai dépassé."
        except OSError as error:
            message = f"Impossible de fermer {usage.name} : {error}"
        GLib.idle_add(self.window.toast, message)


class AppUsageRow(Adw.ActionRow):
    def __init__(self, usage: monitor.AppUsage, page: MonitorPage):
        super().__init__()
        icon = Gtk.Image(pixel_size=32, css_classes=["icon-dropshadow"])
        if usage.icon:
            icon.set_from_gicon(usage.icon)
        self.add_prefix(icon)
        self.cpu = Gtk.Label(width_chars=6, xalign=1, css_classes=["numeric", "dim-label"], tooltip_text="Processeur")
        self.mem = Gtk.Label(width_chars=9, xalign=1, css_classes=["numeric", "heading"], tooltip_text="Mémoire")
        self.add_suffix(self.cpu)
        self.add_suffix(self.mem)
        close = Gtk.Button(icon_name="window-close-symbolic", tooltip_text="Fermer l'application",
                           valign=Gtk.Align.CENTER, css_classes=["flat", "circular", "remove-button"],
                           sensitive=bool(usage.units), opacity=1 if usage.units else 0)
        close.connect("clicked", lambda *_: page.close_app(self.usage))
        self.add_suffix(close)
        self.update(usage)

    def update(self, usage: monitor.AppUsage):
        self.usage = usage
        self.set_title(GLib.markup_escape_text(usage.name))
        self.set_subtitle(plural(usage.processes, "processus", "processus"))
        self.cpu.set_label(f"{usage.cpu:.0%}".replace("%", " %") if usage.cpu >= 0.005 else "—")
        self.mem.set_label(GLib.format_size(usage.memory))
