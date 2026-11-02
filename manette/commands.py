"""Tes commandes perso, rangées dans ~/.config/manette/commandes.json."""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from gi.repository import GLib

PATH = Path(GLib.get_user_config_dir()) / "manette" / "commandes.json"

ICONS = [
    "utilities-terminal-symbolic", "system-run-symbolic", "folder-symbolic", "network-wired-symbolic",
    "network-wireless-symbolic", "audio-speakers-symbolic", "drive-harddisk-symbolic", "software-update-available-symbolic",
    "applications-games-symbolic", "camera-photo-symbolic", "media-playback-start-symbolic", "emblem-system-symbolic",
    "utilities-system-monitor-symbolic", "edit-find-symbolic", "user-trash-symbolic", "weather-clear-night-symbolic",
]


@dataclass
class Custom:
    name: str
    command: str
    description: str = ""
    icon: str = "utilities-terminal-symbolic"
    root: bool = False
    confirm: bool = False
    terminal: bool = False  # pour les commandes interactives (htop, ssh…)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


def _defaults() -> list[Custom]:
    return [
        Custom("Redémarrer le son", "systemctl --user restart pipewire pipewire-pulse wireplumber && echo 'Son relancé.'",
               "Quand le son ne marche plus", "audio-speakers-symbolic"),
        Custom("Espace disque", "df -h -x tmpfs -x squashfs -x efivarfs -x devtmpfs",
               "Résumé de tous les disques montés", "drive-harddisk-symbolic"),
        Custom("Mon adresse IP", "ip -br address", "Adresses de toutes les interfaces", "network-wired-symbolic"),
        Custom("Moniteur htop", "htop", "Processus en temps réel, dans un vrai terminal",
               "utilities-system-monitor-symbolic", terminal=True),
    ]


def load() -> list[Custom]:
    if not PATH.exists():
        items = _defaults()
        save(items)
        return items
    try:
        raw = json.loads(PATH.read_text())
    except (OSError, ValueError):
        # Fichier abîmé : on le met de côté plutôt que de l'écraser.
        PATH.replace(PATH.with_suffix(".json.abime"))
        return []
    known = {f.name for f in fields(Custom)}
    return [Custom(**{k: v for k, v in item.items() if k in known})
            for item in raw if isinstance(item, dict) and "name" in item and "command" in item]


def save(items: list[Custom]) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(i) for i in items], ensure_ascii=False, indent=2))
    tmp.replace(PATH)


def argv(item: Custom) -> list[str]:
    return ["pkexec", "bash", "-c", item.command] if item.root else ["bash", "-c", item.command]


def terminal_argv(item: Custom) -> list[str] | None:
    inner = ["sudo", "bash", "-c", item.command] if item.root else ["bash", "-c", item.command]
    hold = 'echo; read -rsn1 -p "Terminé. Appuie sur une touche pour fermer…"'
    wrapped = ["bash", "-c", f'"$@"; {hold}', "manette", *inner]
    if shutil.which("ptyxis"):
        return ["ptyxis", "--new-window", "--", *wrapped]
    if shutil.which("gnome-terminal"):
        return ["gnome-terminal", "--", *wrapped]
    if shutil.which("kgx"):
        return ["kgx", "--", *wrapped]
    if shutil.which("x-terminal-emulator"):
        return ["x-terminal-emulator", "-e", *wrapped]
    return None
