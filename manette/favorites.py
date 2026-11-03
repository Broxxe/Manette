"""Stable favorite identifiers shared by application views and global search."""

from . import app_data, preferences


def application_key(app):
    return 'app:' + app_data.app_key(app)


def command_key(item):
    return 'command:' + item.id


def load():
    raw = preferences.load().get('favorites', [])
    return {key for key in raw if isinstance(key, str)} if isinstance(raw, list) else set()


def toggle(key):
    items = load()
    if key in items:
        items.remove(key)
    else:
        items.add(key)
    preferences.save(favorites=sorted(items))
    return items
