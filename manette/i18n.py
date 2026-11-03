"""Traductions explicites des messages et modèles de l'interface."""

import json
import os
from pathlib import Path

from . import preferences


def language():
    requested = os.environ.get('MANETTE_LANG')
    if not requested:
        try:
            requested = preferences.load().get('language', 'system')
        except (OSError, ValueError):
            requested = 'system'
    if requested == 'system':
        requested = (os.environ.get('LANGUAGE') or os.environ.get('LC_ALL') or
                     os.environ.get('LC_MESSAGES') or os.environ.get('LANG') or 'en')
    return 'fr' if str(requested).lower().startswith('fr') else 'en'


ENGLISH = json.loads((Path(__file__).parent / 'locales' / 'en.json').read_text())


def _(message, context=None, **values):
    key = context + '\x04' + message if context else message
    translated = ENGLISH.get(key, message) if language() == 'en' else message
    return translated.format(**values) if values else translated


def number(text):
    return text.replace('.', ',').replace('%', ' %') if language() == 'fr' else text
