"""Petits composants partagés entre les pages."""

from gi.repository import Adw, Gtk, Pango


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n < 2 else many}"


def page_scroller(child: Gtk.Widget) -> Gtk.ScrolledWindow:
    clamp = Adw.Clamp(maximum_size=1040, tightening_threshold=800, child=child)
    return Gtk.ScrolledWindow(child=clamp, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)


def page_box() -> Gtk.Box:
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24,
                   margin_top=24, margin_bottom=36, margin_start=16, margin_end=16)


def icon_tile(icon_name: str, size: int = 16) -> Gtk.Widget:
    box = Gtk.Box(valign=Gtk.Align.CENTER, halign=Gtk.Align.START, css_classes=["icon-tile"])
    box.append(Gtk.Image(icon_name=icon_name, pixel_size=size))
    return box


class StatCard(Gtk.Box):
    def __init__(self, caption: str, icon_name: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True,
                         css_classes=["card", "stat-card"])
        top = Gtk.Box(spacing=8)
        top.append(Gtk.Image(icon_name=icon_name, css_classes=["stat-icon"]))
        top.append(Gtk.Label(label=caption, xalign=0, css_classes=["caption-heading", "dim-label"]))
        self.value = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=14, css_classes=["stat-value"])
        self.detail = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=18, css_classes=["caption", "dim-label"])
        self.bar = None
        self.append(top)
        self.append(self.value)
        self.append(self.detail)

    def set(self, value: str, detail: str = "", fraction: float | None = None):
        self.value.set_label(value)
        self.detail.set_label(detail)
        if fraction is not None:
            if self.bar is None:
                self.bar = usage_bar()
                self.append(self.bar)
            self.bar.set_value(fraction)


def usage_bar(fraction: float = 0) -> Gtk.LevelBar:
    bar = Gtk.LevelBar(min_value=0, max_value=1, value=fraction, css_classes=["usage"], valign=Gtk.Align.CENTER)
    for name in ("low", "high", "full"):
        bar.remove_offset_value(name)
    bar.add_offset_value("ok", 0.8)
    bar.add_offset_value("warn", 0.92)
    bar.add_offset_value("crit", 1.0)
    return bar


def stat_grid(*cards: Gtk.Widget) -> Gtk.FlowBox:
    grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, column_spacing=12,
                       row_spacing=12, min_children_per_line=2, max_children_per_line=len(cards))
    for card in cards:
        grid.append(card)
        grid.get_last_child().set_focusable(False)
    return grid
