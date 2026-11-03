"""Résumé de l'espace du dossier personnel, sans modification des fichiers."""

from .i18n import _ as tr

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess


@dataclass
class Entry:
    path: Path
    size: int
    direct_files: bool = False


@dataclass
class Summary:
    home: Path
    total: int
    entries: list[Entry]
    warning: str = ''


def parse_usage(home: Path, output: bytes, warning='') -> Summary:
    home = home.absolute()
    total, folders = None, {}
    for record in output.split(b'\0'):
        if not record:
            continue
        size, separator, raw_path = record.partition(b'\t')
        if not separator or not size.isdigit():
            continue
        path = Path(os.fsdecode(raw_path))
        if path == home:
            total = int(size)
        elif path.parent == home:
            folders[path] = Entry(path, int(size))
    if total is None and not folders:
        raise ValueError(warning or tr('Impossible de mesurer le dossier personnel.'))
    measured = sum(entry.size for entry in folders.values())
    if total is None:
        total = measured
        warning = warning or tr('Analyse incomplète : seuls les dossiers mesurés sont affichés.')
    entries = list(folders.values())
    # du inclut aussi les fichiers directement dans HOME et les blocs du dossier.
    if total > measured:
        entries.append(Entry(home, total - measured, direct_files=True))
    entries.sort(key=lambda entry: (-entry.size, str(entry.path)))
    return Summary(home, total, entries, warning)


def analyze(home: Path | None = None) -> Summary:
    home = (home or Path.home()).absolute()
    argv = ['du', '-x', '-B1', '--max-depth=1', '--null', '--', str(home)]
    try:
        result = subprocess.run(argv, capture_output=True, timeout=60,
                                env={**os.environ, 'LC_ALL': 'C.UTF-8'})
        warning = ''
        if result.returncode:
            warning = tr("Analyse partielle : certains dossiers n'ont pas pu être lus.")
        return parse_usage(home, result.stdout, warning)
    except subprocess.TimeoutExpired as error:
        return parse_usage(home, error.stdout or b'',
                           tr('Analyse arrêtée après une minute : les tailles affichées sont partielles. Réessayez si nécessaire.'))
    except OSError as error:
        raise ValueError(tr("Impossible de lancer l'analyse : {value0}", value0=error)) from error


DESCRIPTIONS = {
    '.local': tr('Applications et données utilisateur'),
    '.cache': tr('Caches des applications'),
    '.config': tr('Réglages et données des applications'),
    '.var': tr('Données utilisateur, notamment Flatpak'),
    '.lmstudio': tr('Modèles et données LM Studio'),
    '.unsloth': tr('Environnement et données Unsloth'),
    '.codex': tr('Données Codex'),
    'snap': tr('Données des applications Snap'),
}


def entry_title(entry: Entry) -> str:
    if entry.direct_files:
        return tr('Fichiers directement dans le dossier personnel')
    return DESCRIPTIONS.get(entry.path.name, entry.path.name)
