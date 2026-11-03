"""Mises à jour isolées : pas de git pull, pas de droits administrateur."""

from .i18n import _ as tr

import ast
from datetime import datetime, timezone
import hashlib
import fcntl
from functools import wraps
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile

from gi.repository import GLib

from . import preferences

REPOSITORY = 'Broxxe/Manette'
LIMIT = 20 * 1024 * 1024


def root():
    return Path(GLib.get_user_data_dir()) / 'manette'


def exclusive(function):
    @wraps(function)
    def run(*args, **kwargs):
        root().mkdir(parents=True, exist_ok=True)
        with (root() / 'update.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError(tr('Une mise à jour de Manette est déjà en cours.')) from error
            return function(*args, **kwargs)
    return run


def request(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Manette-Updater', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=20) as response:
        content = response.read(LIMIT + 1)
    if len(content) > LIMIT:
        raise ValueError(tr('Le téléchargement dépasse la limite autorisée.'))
    return content


def _validate(folder):
    for name in ('manette/__init__.py', 'manette/__main__.py', 'manette/app.py', 'bin/manette',
                 'data/local.Manette.svg', 'data/local.Manette.desktop.in'):
        if not (folder / name).is_file():
            raise ValueError(tr('La nouvelle version est incomplète.'))
    for file in (folder / 'manette').rglob('*.py'):
        ast.parse(file.read_text(), filename=str(file))


def _activate(folder):
    current = root() / 'current'
    previous = root() / 'previous'
    if current.is_symlink():
        if current.resolve() == folder.resolve():
            return
        temporary = root() / 'previous.new'
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(current.resolve())
        temporary.replace(previous)
    elif current.exists():
        raise ValueError(tr("Le chemin de l'installation est occupé par un dossier non géré."))
    temporary = root() / 'current.new'
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(folder)
    temporary.replace(current)


def _register(folder):
    executable = Path.home() / '.local/bin/manette'
    executable.parent.mkdir(parents=True, exist_ok=True)
    if executable.exists() and not executable.is_symlink():
        raise ValueError(tr('Un autre programme utilise déjà le nom manette dans le dossier des exécutables.'))
    temporary = executable.with_name('manette.new')
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(root() / 'current/bin/manette')
    temporary.replace(executable)
    icon = Path(GLib.get_user_data_dir()) / 'icons/hicolor/scalable/apps/local.Manette.svg'
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(folder / 'data/local.Manette.svg', icon)
    desktop = Path(GLib.get_user_data_dir()) / 'applications/local.Manette.desktop'
    desktop.parent.mkdir(parents=True, exist_ok=True)
    escaped = str(executable).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
    desktop.write_text((folder / 'data/local.Manette.desktop.in').read_text().replace('@EXEC@', f'"{escaped}"'))


def _revision(source):
    try:
        result = subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=5)
        value = result.stdout.strip()
        return value if re.fullmatch('[0-9a-f]{40}', value) else None
    except (OSError, subprocess.TimeoutExpired):
        return None


@exclusive
def install_local(source=None):
    source = (source or Path(__file__).resolve().parent.parent).resolve()
    releases = root() / 'versions'
    releases.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.prepare-', dir=releases) as temporary:
        stage = Path(temporary) / 'app'
        stage.mkdir()
        for name in ('manette', 'bin', 'data'):
            shutil.copytree(source / name, stage / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        _validate(stage)
        (stage / 'bin/manette').chmod(0o755)
        digest = hashlib.sha256()
        for file in sorted(stage.rglob('*')):
            if file.is_file():
                digest.update(str(file.relative_to(stage)).encode())
                digest.update(file.read_bytes())
        destination = releases / ('local-' + digest.hexdigest()[:16])
        metadata = {'revision': _revision(source), 'repository': REPOSITORY}
        (stage / 'installation.json').write_text(json.dumps(metadata))
        if not destination.exists():
            stage.rename(destination)
        current = root() / 'current'
        if current.exists() and not current.is_symlink():
            raise ValueError(tr("Le chemin de l'installation est occupé par un dossier non géré."))
        _register(destination)
        _activate(destination)
    preferences.save(automatic_updates=True)
    return destination


def managed():
    here = Path(__file__).resolve().parent.parent
    current = root() / 'current'
    return current.is_symlink() and (here / 'installation.json').is_file() and here.parent == root() / 'versions'


def stage_archive(content, revision):
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError(tr('Identifiant de version invalide.'))
    releases = root() / 'versions'
    releases.mkdir(parents=True, exist_ok=True)
    destination = releases / revision
    with tempfile.TemporaryDirectory(prefix='.download-', dir=releases) as temporary:
        stage = Path(temporary) / 'app'
        stage.mkdir()
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if sum(info.file_size for info in archive.infolist()) > LIMIT:
                raise ValueError(tr("L'archive dépasse la limite autorisée."))
            for info in archive.infolist():
                parts = PurePosixPath(info.filename).parts
                mode = info.external_attr >> 16
                if '..' in parts or info.filename.startswith('/') or stat.S_ISLNK(mode):
                    raise ValueError(tr("L'archive contient un chemin non autorisé."))
                if len(parts) < 2 or parts[1] not in ('manette', 'bin', 'data'):
                    continue
                target = stage.joinpath(*parts[1:])
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(info))
        _validate(stage)
        (stage / 'bin/manette').chmod(0o755)
        (stage / 'installation.json').write_text(json.dumps({'revision': revision, 'repository': REPOSITORY}))
        if not destination.exists():
            stage.rename(destination)
        else:
            _validate(destination)
        _activate(destination)
    return destination


@exclusive
def check(force=False):
    if not managed():
        return 'unmanaged'
    settings = preferences.load()
    now = datetime.now(timezone.utc)
    if not force and settings.get('last_update_check'):
        last = datetime.fromisoformat(settings['last_update_check'])
        if (now - last).total_seconds() < 86400:
            return 'skipped'
    preferences.save(last_update_check=now.isoformat())
    repository = json.loads(request(f'https://api.github.com/repos/{REPOSITORY}'))
    branch = urllib.parse.quote(repository['default_branch'], safe='')
    commit = json.loads(request(f'https://api.github.com/repos/{REPOSITORY}/commits/{branch}'))['sha']
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError(tr('Identifiant de version invalide.'))
    active = (root() / 'current').resolve()
    installed = json.loads((active / 'installation.json').read_text()).get('revision')
    if installed == commit:
        return 'current'
    if installed:
        comparison = json.loads(request(f'https://api.github.com/repos/{REPOSITORY}/compare/{installed}...{commit}'))
        if comparison.get('status') != 'ahead':
            raise ValueError(tr('La version distante ne prolonge pas la version installée. Aucune modification effectuée.'))
    stage_archive(request(f'https://api.github.com/repos/{REPOSITORY}/zipball/{commit}'), commit)
    return 'updated'


if __name__ == '__main__':
    install_local()
    print(tr('Manette : installation utilisateur prête, mises à jour automatiques activées.'))
