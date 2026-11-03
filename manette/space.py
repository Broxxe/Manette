"""Estimate peak package space and account for separate mount points."""

from dataclasses import dataclass, field
import json
from pathlib import Path
import shutil
import subprocess
import sys

from .i18n import _

RESERVE = 512 * 1024**2


@dataclass
class Request:
    kind: str = 'unknown'
    target: str | list[str] = ''
    partial: bool = False


@dataclass
class Filesystem:
    path: Path
    free: int | None
    required: int = 0
    paths: list = field(default_factory=list)

    @property
    def insufficient(self):
        return self.free is not None and self.required > self.free


@dataclass
class Estimate:
    download: int | None
    unpacked: int | None
    net: int | None
    filesystems: list
    partial: bool
    note: str = ''

    @property
    def blocked(self):
        return any(fs.insufficient for fs in self.filesystems)


def inspect(request, paths):
    amounts, note = {}, ''
    if request.kind != 'unknown':
        try:
            result = subprocess.run([sys.executable, '-m', 'manette.space_probe', json.dumps(
                {'kind': request.kind, 'target': request.target})],
                capture_output=True, text=True, timeout=30, cwd=Path(__file__).resolve().parent.parent)
            amounts = json.loads(result.stdout)
            if result.returncode or 'error' in amounts:
                raise ValueError(amounts.get('error', result.stderr))
            for key in ('download', 'unpacked', 'net'):
                if not isinstance(amounts.get(key), int) or amounts[key] < 0:
                    raise ValueError('Invalid size returned by APT')
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            amounts = {}
            note = _('Estimation APT indisponible : {value0}', value0=str(error)[:600])
    partial = request.partial or request.kind == 'unknown' or not amounts
    demands = [(Path('/'), amounts.get('unpacked', 0)),
               (Path('/var/cache/apt/archives'), amounts.get('download', 0))] if amounts else []
    demands += [(Path(value).expanduser(), 0) for value in paths]
    grouped = {}
    for path, required in demands:
        existing = path
        while not existing.exists() and existing != existing.parent:
            existing = existing.parent
        try:
            device = existing.stat().st_dev
            free = shutil.disk_usage(existing).free
        except OSError:
            device, free = str(path), None
        if device not in grouped:
            grouped[device] = Filesystem(existing, free, RESERVE if amounts else 0)
        fs = grouped[device]
        fs.required += required
        if path not in fs.paths:
            fs.paths.append(path)
    return Estimate(amounts.get('download'), amounts.get('unpacked'), amounts.get('net'),
                    list(grouped.values()), partial or any(fs.free is None for fs in grouped.values()), note)
