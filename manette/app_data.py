"""Associations entre applications et dossiers, indépendantes de la machine."""

from .i18n import _ as tr

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import time

from gi.repository import GLib

from .scanner import APPIMAGE, FLATPAK, SNAP


@dataclass
class Folder:
    path: Path
    automatic: bool = False


@dataclass
class Usage:
    folder: Folder
    size: int | None
    complete: bool
    included_in: Path | None = None


def config_path() -> Path:
    return Path(GLib.get_user_config_dir()) / 'manette' / 'dossiers.json'


def app_key(app) -> str:
    desktop_id = app.info.get_id() if app.info else None
    ident = desktop_id if app.source == APPIMAGE and desktop_id else app.ident
    if app.source == APPIMAGE and Path(ident).is_absolute() and Path(ident).is_relative_to(Path.home()):
        ident = '~/' + str(Path(ident).relative_to(Path.home()))
    return f'{app.source}:{ident}'


def _load() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict) or any(not isinstance(v, list) or
                                       any(not isinstance(p, str) for p in v) for v in raw.values()):
        raise ValueError(tr('Le fichier des associations de dossiers est invalide.'))
    return raw


def associated(app) -> list[Path]:
    return [Path(p).expanduser() for p in _load().get(app_key(app), [])]


def associate(app, path: Path, remove=False):
    raw = _load()  # Ne jamais écraser un fichier illisible ou endommagé.
    target = path.expanduser().absolute()
    items = [Path(p).expanduser() for p in raw.get(app_key(app), [])]
    items = [p for p in items if p.absolute() != target]
    if not remove:
        items.append(target)
    home = Path.home()
    raw[app_key(app)] = ['~/' + str(p.relative_to(home)) if p.is_relative_to(home) else str(p) for p in items]
    destination = config_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix('.tmp')
    tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2))
    tmp.replace(destination)


def discover(app) -> list[Folder]:
    """Utilise les identifiants exacts, jamais une recherche floue dans le disque."""
    home = Path.home()
    config = Path(GLib.get_user_config_dir())
    cache = Path(GLib.get_user_cache_dir())
    data = Path(GLib.get_user_data_dir())
    candidates = []
    safe_id = app.ident and app.ident not in ('.', '..') and '/' not in app.ident and '\\' not in app.ident
    if app.source == FLATPAK and safe_id:
        candidates.append(home / '.var' / 'app' / app.ident)
    elif app.source == SNAP and safe_id:
        candidates.append(home / 'snap' / app.ident)
    else:
        names = {app.name, app.ident}
        if app.info:
            names.add((app.info.get_id() or '').removesuffix('.desktop'))
        # Un identifiant ne peut pas devenir un chemin ou désigner tout ~/.config.
        names = {n for n in names if n and n not in ('.', '..') and '/' not in n and '\\' not in n}
        for name in sorted(names):
            candidates.extend(base / name for base in (config, cache, data))
        normalized = re.sub(r'[^a-z0-9]', '', app.name.casefold())
        if normalized == 'lmstudio':
            candidates.extend([home / '.lmstudio', config / 'LM Studio', cache / 'lm-studio'])
        elif normalized == 'bionic':
            candidates.append(home / '.lmstudio' / 'apps' / 'bionic')
    manual = associated(app)
    folders = {str(p.absolute()): Folder(p, True) for p in candidates if p.is_dir()}
    for path in manual:
        folders[str(path.absolute())] = Folder(path, False)
    return list(folders.values())


def measure(folders: list[Folder], timeout=20) -> tuple[list[Usage], int, bool]:
    """Mesure les blocs alloués, sans lire les fichiers ni suivre les liens internes."""
    result, seen, roots = [], set(), []
    total, complete = 0, True
    deadline = time.monotonic() + timeout
    # Les parents passent avant leurs sous-dossiers pour ne pas les compter deux fois.
    for folder in sorted(folders, key=lambda f: len(f.path.parts)):
        try:
            path = folder.path.resolve(strict=True)
        except OSError:
            result.append(Usage(folder, None, False))
            complete = False
            continue
        parent = next((root for root in roots if path == root or path.is_relative_to(root)), None)
        if parent is not None:
            result.append(Usage(folder, None, True, parent))
            continue
        roots.append(path)
        size, ok, stack = 0, True, [path]
        while stack:
            if time.monotonic() >= deadline:
                ok = False
                break
            current = stack.pop()
            try:
                info = current.lstat()
                inode = (info.st_dev, info.st_ino)
                if inode in seen:
                    continue
                seen.add(inode)
                size += info.st_blocks * 512
                if stat.S_ISDIR(info.st_mode):
                    with os.scandir(current) as entries:
                        for entry in entries:
                            if time.monotonic() >= deadline:
                                ok = False
                                break
                            stack.append(Path(entry.path))
            except OSError:
                ok = False
        total += size
        complete = complete and ok
        result.append(Usage(folder, size, ok))
    return result, total, complete


def trash_candidate(path, app, other_apps):
    """Validate an individual data folder; never delete a broad/shared directory."""
    path = Path(path).expanduser().absolute()
    home = Path.home().resolve()
    if path.is_symlink() or not path.is_dir():
        raise ValueError(tr('Ce dossier est absent ou correspond à un lien symbolique.'))
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(home) or resolved == home or path != resolved:
        raise ValueError(tr('Seuls les dossiers réels situés dans le dossier personnel peuvent être mis à la corbeille.'))
    protected = {home, home / '.local', home / '.var', home / '.var/app', home / 'snap',
                 Path(GLib.get_user_config_dir()).resolve(), Path(GLib.get_user_cache_dir()).resolve(),
                 Path(GLib.get_user_data_dir()).resolve(), Path(GLib.get_user_state_dir()).resolve()}
    protected.update(home / name for name in ('.ssh', '.gnupg', '.local/share/Trash', '.local/share/applications',
                                             '.local/bin', '.local/opt', 'Applications', 'AppImages', 'opt', 'Games'))
    protected.update(Path(value).resolve() for directory in (
        GLib.UserDirectory.DIRECTORY_DESKTOP, GLib.UserDirectory.DIRECTORY_DOCUMENTS,
        GLib.UserDirectory.DIRECTORY_DOWNLOAD, GLib.UserDirectory.DIRECTORY_MUSIC,
        GLib.UserDirectory.DIRECTORY_PICTURES, GLib.UserDirectory.DIRECTORY_PUBLIC_SHARE,
        GLib.UserDirectory.DIRECTORY_TEMPLATES, GLib.UserDirectory.DIRECTORY_VIDEOS)
        if (value := GLib.get_user_special_dir(directory)))
    if any(resolved.is_relative_to(home / name) for name in ('.ssh', '.gnupg', '.local/share/Trash')):
        raise ValueError(tr('Ce dossier est un emplacement personnel ou partagé protégé.'))
    if os.path.ismount(resolved) or any(root == resolved or root.is_relative_to(resolved) for root in protected):
        raise ValueError(tr('Ce dossier est un emplacement personnel ou partagé protégé.'))
    if resolved.stat().st_uid != os.getuid():
        raise ValueError(tr('Ce dossier n’appartient pas au compte utilisateur.'))
    for other in other_apps:
        if app_key(other) == app_key(app):
            continue
        from .local_removal import _program_paths
        programs = _program_paths(other.info) if other.info else []
        if other.source == APPIMAGE:
            programs.append(Path(other.ident).resolve())
        if any(program.is_relative_to(resolved) for program in programs):
            raise ValueError(tr('Ce dossier peut aussi être utilisé par {value0}.', value0=other.name))
        for folder in discover(other):
            other_path = folder.path.resolve()
            if resolved == other_path or resolved.is_relative_to(other_path) or other_path.is_relative_to(resolved):
                raise ValueError(tr('Ce dossier peut aussi être utilisé par {value0}.', value0=other.name))
    return resolved
