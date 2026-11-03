"""Page Mes commandes : tes propres boutons."""

import subprocess
from dataclasses import replace

from gi.repository import Adw, Gtk, Pango

from . import commands
from .commands import Custom
from .widgets import page_box, page_scroller


class CustomPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.items = commands.load()

        content = page_box()
        head = Gtk.Box(spacing=12)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        titles.append(Gtk.Label(label="Mes commandes", xalign=0, css_classes=["title-2"]))
        titles.append(Gtk.Label(label="Tes boutons perso : un clic pour lancer, ⋯ pour modifier.", xalign=0,
                                wrap=True, css_classes=["dim-label"]))
        add = Gtk.Button(valign=Gtk.Align.CENTER, css_classes=["suggested-action", "pill"],
                         child=Adw.ButtonContent(icon_name="list-add-symbolic", label="Nouvelle commande"))
        add.connect("clicked", lambda *_: self.edit(None))
        head.append(titles)
        head.append(add)
        content.append(head)

        self.stack = Gtk.Stack()
        self.grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, column_spacing=12,
                                row_spacing=12, min_children_per_line=1, max_children_per_line=4,
                                valign=Gtk.Align.START)
        self.stack.add_named(self.grid, "grid")
        empty = Adw.StatusPage(icon_name="utilities-terminal-symbolic", title="Aucune commande",
                               description="Crée ton premier bouton avec « Nouvelle commande ».",
                               css_classes=["compact"])
        self.stack.add_named(empty, "empty")
        content.append(self.stack)
        self.append(page_scroller(content))
        self._render()

    def _render(self):
        self.grid.remove_all()
        for item in self.items:
            self.grid.append(self._tile(item))
            self.grid.get_last_child().set_focusable(False)
        self.stack.set_visible_child_name("grid" if self.items else "empty")

    def _tile(self, item: Custom) -> Gtk.Widget:
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        top = Gtk.Box(spacing=8)
        icon = Gtk.Box(css_classes=["icon-tile", "large"], halign=Gtk.Align.START)
        icon.append(Gtk.Image(icon_name=item.icon, pixel_size=24))
        top.append(icon)
        if item.root:
            top.append(Gtk.Image(icon_name="changes-prevent-symbolic", tooltip_text="Autorisation administrateur requise",
                                 valign=Gtk.Align.END, css_classes=["dim-label"]))
        if item.terminal:
            top.append(Gtk.Image(icon_name="utilities-terminal-symbolic", tooltip_text="S'ouvre dans un terminal",
                                 valign=Gtk.Align.END, css_classes=["dim-label"]))
        body.append(top)
        body.append(Gtk.Label(label=item.name, xalign=0, wrap=True, max_width_chars=24, css_classes=["heading"]))
        if item.description:
            body.append(Gtk.Label(label=item.description, xalign=0, wrap=True, lines=2, max_width_chars=24,
                                  ellipsize=Pango.EllipsizeMode.END, css_classes=["caption", "dim-label"]))
        body.append(Gtk.Label(label=item.command.splitlines()[0], xalign=0, ellipsize=Pango.EllipsizeMode.END,
                              max_width_chars=24, vexpand=True, valign=Gtk.Align.END,
                              css_classes=["caption", "monospace", "command-preview"]))

        button = Gtk.Button(child=body, css_classes=["card", "tile"], tooltip_text=item.command)
        button.connect("clicked", lambda *_: self.run(item))

        menu = Gtk.MenuButton(icon_name="view-more-horizontal-symbolic", halign=Gtk.Align.END,
                              valign=Gtk.Align.START, margin_top=8, margin_end=8,
                              css_classes=["flat", "circular"], tooltip_text="Options")
        popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        popover = Gtk.Popover(child=popover_box)
        for label, callback in (("Modifier", lambda: self.edit(item)), ("Dupliquer", lambda: self._duplicate(item)),
                                ("Supprimer", lambda: self._delete(item))):
            entry = Gtk.Button(label=label, css_classes=["flat"])
            entry.get_child().set_xalign(0)
            entry.connect("clicked", lambda _b, cb=callback: (popover.popdown(), cb()))
            popover_box.append(entry)
        menu.set_popover(popover)

        overlay = Gtk.Overlay(child=button)
        overlay.add_overlay(menu)
        return overlay

    # --- Actions ----------------------------------------------------------

    def run(self, item: Custom):
        def go():
            if item.terminal:
                argv = commands.terminal_argv(item)
                if not argv:
                    self.window.toast("Aucun terminal trouvé.")
                    return
                subprocess.Popen(argv, start_new_session=True)
                self.window.toast(f"« {item.name} » s'ouvre dans le terminal")
            else:
                self.window.run(commands.argv(item), item.name, item.command)
        if item.root or item.confirm:
            body = item.command
            if item.root:
                body = "Cette commande aura les droits administrateur et pourra modifier tout le système.\n\n" + body
            self.window.confirm(f"Lancer « {item.name} » ?", body, "Lancer", go, destructive=item.root)
        else:
            go()

    def edit(self, item: Custom | None):
        CommandDialog(item, self._save).present(self.window)

    def _save(self, original: Custom | None, edited: Custom):
        if original is None:
            self.items.append(edited)
        else:
            self.items[self.items.index(original)] = edited
        commands.save(self.items)
        self._render()

    def _duplicate(self, item: Custom):
        copy = replace(item, name=f"{item.name} (copie)", id=Custom("", "").id)
        self.items.insert(self.items.index(item) + 1, copy)
        commands.save(self.items)
        self._render()

    def _delete(self, item: Custom):
        def go():
            self.items.remove(item)
            commands.save(self.items)
            self._render()
            self.window.toast(f"« {item.name} » supprimée")
        self.window.confirm(f"Supprimer « {item.name} » ?", "Le bouton disparaîtra de Mes commandes.", "Supprimer", go)


class CommandDialog(Adw.Dialog):
    def __init__(self, item: Custom | None, on_save):
        super().__init__(title="Modifier la commande" if item else "Nouvelle commande", content_width=560,
                         content_height=720)
        self.item, self.on_save = item, on_save
        self.icon = item.icon if item else commands.ICONS[0]

        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Annuler")
        cancel.connect("clicked", lambda *_: self.close())
        self.save_button = Gtk.Button(label="Enregistrer", css_classes=["suggested-action"])
        self.save_button.connect("clicked", lambda *_: self._save())
        header.pack_start(cancel)
        header.pack_end(self.save_button)

        page = Adw.PreferencesPage()
        main = Adw.PreferencesGroup()
        self.name = Adw.EntryRow(title="Nom du bouton", text=item.name if item else "")
        self.description = Adw.EntryRow(title="Description (facultatif)", text=item.description if item else "")
        main.add(self.name)
        main.add(self.description)
        page.add(main)

        command_group = Adw.PreferencesGroup(title="Commande",
                                             description="Du bash : plusieurs lignes, &amp;&amp;, pipes… tout marche.")
        self.command = Gtk.TextView(monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=12,
                                    bottom_margin=12, left_margin=12, right_margin=12, css_classes=["command-editor"])
        self.command.get_buffer().set_text(item.command if item else "")
        frame = Gtk.Frame(child=Gtk.ScrolledWindow(child=self.command, min_content_height=120,
                                                   hscrollbar_policy=Gtk.PolicyType.NEVER),
                          css_classes=["card"])
        command_group.add(frame)
        page.add(command_group)

        options = Adw.PreferencesGroup(title="Options")
        self.root = Adw.SwitchRow(title="Droits administrateur", subtitle="Demande une autorisation au système",
                                  active=item.root if item else False)
        self.confirm = Adw.SwitchRow(title="Demander confirmation",
                                     subtitle="Affiche la commande avant de la lancer, même sans droits administrateur",
                                     active=item.confirm if item else True)
        self.terminal = Adw.SwitchRow(title="Ouvrir dans un vrai terminal",
                                      subtitle="Pour les commandes interactives (htop, ssh, questions…)",
                                      active=item.terminal if item else False)
        for row in (self.root, self.confirm, self.terminal):
            options.add(row)
        self.root.connect("notify::active", lambda *_: self._sync_confirmation())
        self._sync_confirmation()
        page.add(options)

        icons_group = Adw.PreferencesGroup(title="Icône")
        icons = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=8, min_children_per_line=4,
                            column_spacing=6, row_spacing=6, homogeneous=True)
        group = None
        for name in commands.ICONS:
            button = Gtk.ToggleButton(child=Gtk.Image(icon_name=name, pixel_size=20), active=name == self.icon,
                                      css_classes=["flat", "icon-choice"], tooltip_text=name.removesuffix("-symbolic"))
            if group:
                button.set_group(group)
            group = group or button
            button.connect("toggled", lambda b, n=name: b.get_active() and setattr(self, "icon", n))
            icons.append(button)
        icons_group.add(icons)
        page.add(icons_group)

        view = Adw.ToolbarView(content=page)
        view.add_top_bar(header)
        self.set_child(view)

        self.name.connect("changed", lambda *_: self._validate())
        self.command.get_buffer().connect("changed", lambda *_: self._validate())
        self._validate()

    def _command_text(self) -> str:
        buffer = self.command.get_buffer()
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False).strip()

    def _sync_confirmation(self):
        root = self.root.get_active()
        if root:
            self.confirm.set_active(True)
        self.confirm.set_sensitive(not root)
        self.confirm.set_subtitle("Obligatoire pour les commandes avec droits administrateur" if root else
                                  "Une commande peut aussi modifier tes fichiers sans droits administrateur")

    def _validate(self):
        self.save_button.set_sensitive(bool(self.name.get_text().strip() and self._command_text()))

    def _save(self):
        values = dict(name=self.name.get_text().strip(), command=self._command_text(),
                      description=self.description.get_text().strip(), icon=self.icon, root=self.root.get_active(),
                      confirm=self.root.get_active() or self.confirm.get_active(), terminal=self.terminal.get_active())
        edited = replace(self.item, **values) if self.item else Custom(**values)
        self.on_save(self.item, edited)
        self.close()
