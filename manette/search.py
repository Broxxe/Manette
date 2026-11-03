"""Small in-memory search index. Searching never executes a command."""

from dataclasses import dataclass
import unicodedata


def normalize(text):
    return ''.join(character for character in unicodedata.normalize('NFKD', text.casefold())
                   if not unicodedata.combining(character))


@dataclass
class Item:
    title: str
    detail: str
    kind: str
    target: object = None
    favorite: bool = False


def find(items, query, limit=80):
    words = normalize(query).split()
    matches = [item for item in items if all(word in normalize(item.title + ' ' + item.detail) for word in words)
               and (words or item.favorite or item.kind == 'navigation')]
    matches.sort(key=lambda item: (not item.favorite,
                 not normalize(item.title).startswith(normalize(query).strip()), normalize(item.title)))
    return matches[:limit], len(matches)
