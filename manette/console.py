"""Panneau qui exécute une commande et affiche sa sortie en direct."""

from .i18n import _ as tr

import os
import re
import signal

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][A-Z0-9]")


def _clean(raw: str) -> str:
    # Les barres de progression réécrivent la ligne avec \r : on garde le dernier état.
    parts = ANSI.sub("", raw).split("\r")
    return next((p for p in reversed(parts) if p.strip()), "")


class Console(Gtk.Box):
    def __init__(self, on_finished):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.toolbar = Adw.ToolbarView(vexpand=True)
        self.append(self.toolbar)
        self.on_finished = on_finished
        self.proc = None
        self.title = ""
        self.on_done = None

        self.status = Adw.WindowTitle(title=tr('Console'), subtitle=tr('Prête'))
        header = Adw.HeaderBar(title_widget=self.status)
        self.spinner = Adw.Spinner(visible=False)
        self.stop_button = Gtk.Button(icon_name="media-playback-stop-symbolic", tooltip_text=tr('Arrêter'),
                                      sensitive=False, css_classes=["flat"])
        self.stop_button.connect("clicked", lambda *_: self.stop())
        copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text=tr('Copier la sortie'))
        copy.connect("clicked", lambda *_: self._copy())
        clear = Gtk.Button(icon_name="edit-clear-all-symbolic", tooltip_text=tr('Effacer'))
        clear.connect("clicked", lambda *_: self.clear())
        header.pack_start(self.stop_button)
        header.pack_start(self.spinner)
        header.pack_end(clear)
        header.pack_end(copy)
        self.toolbar.add_top_bar(header)

        self.view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                 wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=14, bottom_margin=14,
                                 left_margin=16, right_margin=16, css_classes=["console-view"])
        self.buffer = self.view.get_buffer()
        self.buffer.create_tag("title", weight=Pango.Weight.BOLD, scale=1.12, pixels_above_lines=4)
        self.buffer.create_tag("cmd", foreground="#3584e4", pixels_below_lines=6)
        self.buffer.create_tag("ok", foreground="#26a269", weight=Pango.Weight.BOLD, pixels_above_lines=6)
        self.buffer.create_tag("error", foreground="#e01b24", weight=Pango.Weight.BOLD, pixels_above_lines=6)
        self.end_mark = self.buffer.create_mark("end", self.buffer.get_end_iter(), False)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(Adw.StatusPage(icon_name="utilities-terminal-symbolic", title=tr("Rien pour l'instant"),
                                            description=tr("Cliquez sur un bouton : le résultat s'affiche ici en direct."),
                                            css_classes=["compact"]), "empty")
        self.stack.add_named(Gtk.ScrolledWindow(child=self.view, hscrollbar_policy=Gtk.PolicyType.NEVER), "log")
        self.toolbar.set_content(self.stack)

    @property
    def busy(self) -> bool:
        return self.proc is not None

    def run(self, argv, title, display=None, on_done=None):
        self.stack.set_visible_child_name("log")
        if self.buffer.get_char_count():
            self._write("\n")
        self._write(f"{title}\n", "title")
        for line in (display or " ".join(argv)).splitlines():
            self._write(f"$ {line}\n", "cmd")

        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
        launcher.setenv("TERM", "dumb", True)
        launcher.setenv("PYTHONUNBUFFERED", "1", True)
        try:
            # setsid : la commande a son propre groupe de processus, qu'on peut arrêter d'un coup.
            proc = launcher.spawnv(["setsid", *argv])
        except GLib.Error as error:
            self._write(tr('✘ Impossible de lancer la commande : {value0}\n', value0=error.message), "error")
            return

        self.proc, self.title, self.on_done = proc, title, on_done
        self.pending = b""
        self._set_running(True)
        self._read(proc.get_stdout_pipe())

    def stop(self):
        if not self.proc:
            return
        try:
            os.killpg(int(self.proc.get_identifier()), signal.SIGTERM)
        except (OSError, TypeError, ValueError):
            self.proc.force_exit()

    def clear(self):
        self.buffer.set_text("")
        if not self.busy:
            self.stack.set_visible_child_name("empty")

    def _copy(self):
        text = self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), False)
        provider = Gdk.ContentProvider.new_for_bytes("text/plain;charset=utf-8", GLib.Bytes.new(text.encode()))
        self.get_clipboard().set_content(provider)

    def _read(self, stream):
        stream.read_bytes_async(16384, GLib.PRIORITY_DEFAULT, None, self._on_chunk)

    def _on_chunk(self, stream, result):
        try:
            chunk = stream.read_bytes_finish(result).get_data() or b""
        except GLib.Error:
            chunk = b""
        if not chunk:  # fin de la sortie
            if self.pending:
                self._write(_clean(self.pending.decode("utf-8", "replace")) + "\n")
            self.proc.wait_async(None, self._on_exit)
            return
        *lines, self.pending = (self.pending + chunk).split(b"\n")
        if lines:
            self._write("".join(_clean(line.decode("utf-8", "replace")) + "\n" for line in lines))
        self._read(stream)

    def _on_exit(self, proc, result):
        try:
            proc.wait_finish(result)
        except GLib.Error:
            pass
        code = proc.get_exit_status() if proc.get_if_exited() else -1
        ok = code == 0
        if ok:
            self._write(tr('✔ Terminé\n'), "ok")
        elif code == -1:
            self._write(tr('✘ Arrêté\n'), "error")
        elif code in (126, 127):
            self._write(tr('✘ Échec (code {value0}) : mot de passe refusé ou annulé ?\n', value0=code), "error")
        else:
            self._write(tr('✘ Échec (code {value0})\n', value0=code), "error")

        title, on_done = self.title, self.on_done
        self.proc, self.on_done = None, None
        self._set_running(False, tr('Terminé') if ok else tr('Échec'))
        if on_done:
            on_done(ok)
        self.on_finished(title, ok)

    def _set_running(self, running, outcome=""):
        self.spinner.set_visible(running)
        self.stop_button.set_sensitive(running)
        self.status.set_subtitle(self.title if running else f"{outcome} : {self.title}")

    def _write(self, text, tag=None):
        end = self.buffer.get_end_iter()
        if tag:
            self.buffer.insert_with_tags_by_name(end, text, tag)
        else:
            self.buffer.insert(end, text)
        self.view.scroll_to_mark(self.end_mark, 0, False, 0, 1)
