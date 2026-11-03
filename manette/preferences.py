"""Préférences de Manette, dans le dossier de configuration utilisateur."""

import json
import fcntl
from pathlib import Path
import tempfile

from gi.repository import GLib


def path():
    return Path(GLib.get_user_config_dir()) / 'manette' / 'preferences.json'


def load():
    file = path()
    if not file.exists():
        return {}
    data = json.loads(file.read_text())
    if not isinstance(data, dict):
        raise ValueError('Le fichier des préférences est invalide.')
    return data


def save(**changes):
    file = path()
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = load()
        data.update(changes)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=file.parent, delete=False) as stream:
            stream.write(json.dumps(data, ensure_ascii=False, indent=2))
            temporary = Path(stream.name)
        try:
            temporary.replace(file)
        finally:
            temporary.unlink(missing_ok=True)


def background_opacity(settings):
    """Return a valid background percentage even for hand-edited preferences."""
    try:
        return max(0, min(100, int(settings.get('background_opacity', 78))))
    except (TypeError, ValueError, OverflowError):
        return 78
