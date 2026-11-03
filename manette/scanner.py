"""Repère les applications installées et la façon dont elles l'ont été."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from gi.repository import Gio, GLib

APT, DEB, FLATPAK, SNAP, APPIMAGE, LOCAL = "apt", "deb", "flatpak", "snap", "appimage", "local"

SOURCES = {
    APT: "Dépôt APT",
    DEB: ".deb manuel",
    FLATPAK: "Flatpak",
    SNAP: "Snap",
    APPIMAGE: "AppImage",
    LOCAL: "Local",
}

# .deb installés à la main dont le champ Homepage ne mène pas au dépôt GitHub.
KNOWN_GITHUB = {
    "heroic": "Heroic-Games-Launcher/HeroicGamesLauncher",
    "obsidian": "obsidianmd/obsidian-releases",
    "vesktop": "Vencord/Vesktop",
}

APPIMAGE_DIRS = ("~/Applications", "~/AppImages", "~/.local/bin", "~/Téléchargements", "~/Downloads", "~/opt", "/opt")

CACHE_DIR = Path(GLib.get_user_cache_dir()) / "manette"


@dataclass
class App:
    name: str
    source: str
    ident: str
    version: str = ""
    size: int | None = None
    info: Gio.DesktopAppInfo | None = None
    update: str | None = None
    update_url: str | None = None
    note: str = ""
    installation: str = ""  # Flatpak : system ou user
    local_launchers: list[str] = field(default_factory=list)

    @property
    def icon(self) -> Gio.Icon | None:
        return self.info.get_icon() if self.info else None


@dataclass
class Command:
    argv: list[str]
    display: str


@dataclass
class ScanResult:
    apps: list[App]
    warnings: list[str] = field(default_factory=list)


def _run(*argv: str, timeout: int = 30, warnings: list[str] | None = None) -> str:
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                             env={**os.environ, "LC_ALL": "C.UTF-8"})
    except (OSError, subprocess.TimeoutExpired) as error:
        if warnings is not None:
            warnings.append(f"{argv[0]} : vérification impossible ({error})")
        return ""
    if out.returncode and warnings is not None:
        detail = out.stderr.strip() or f"code {out.returncode}"
        warnings.append(f"{argv[0]} : {detail}")
        return ""
    return out.stdout


def scan() -> ScanResult:
    warnings = []
    flatpaks, snaps, appimages, debs = {}, {}, {}, {}
    for info in Gio.AppInfo.get_all():
        if not info.should_show() or not isinstance(info, Gio.DesktopAppInfo):
            continue
        filename = info.get_filename() or ""
        if fid := info.get_string("X-Flatpak"):
            flatpaks.setdefault(fid, info)
        elif snap := info.get_string("X-SnapInstanceName") or _snap_from_path(filename):
            snaps.setdefault(snap, info)
        elif path := _appimage_path(info):
            appimages.setdefault(os.path.realpath(path), info)
        else:
            debs[filename] = info

    apps = [*_scan_debs(debs, warnings), *_scan_flatpaks(flatpaks, warnings),
            *_scan_snaps(snaps, warnings), *_scan_appimages(appimages)]
    apps.sort(key=lambda a: a.name.casefold())
    return ScanResult(apps, warnings)


def _snap_from_path(filename: str) -> str | None:
    if filename.startswith("/var/lib/snapd/desktop/"):
        return Path(filename).name.split("_")[0]
    return None


def _appimage_path(info: Gio.DesktopAppInfo) -> str | None:
    try:
        _ok, argv = GLib.shell_parse_argv(info.get_commandline() or "")
    except GLib.Error:
        return None
    return next((a for a in argv if a.lower().endswith(".appimage") and os.path.isfile(a)), None)


# --- Paquets .deb ---------------------------------------------------------

def _scan_debs(infos: dict[str, Gio.DesktopAppInfo], warnings: list[str]) -> list[App]:
    # Une copie personnelle d'un lanceur peut masquer celui fourni par le paquet.
    fallbacks = {}
    for path, info in infos.items():
        desktop_id = info.get_id() or ""
        if not desktop_id or Path(desktop_id).name != desktop_id:
            continue
        for base in GLib.get_system_data_dirs():
            candidate = Path(base) / "applications" / desktop_id
            if str(candidate) == path or not candidate.is_file():
                continue
            try:
                original = Gio.DesktopAppInfo.new_from_filename(str(candidate))
                if original and original.get_executable() == info.get_executable():
                    fallbacks[path] = str(candidate)
                    break
            except (TypeError, GLib.Error):
                continue
    owners = {}
    if infos:
        for line in _run("dpkg", "-S", *infos, *fallbacks.values()).splitlines():
            if line.startswith("diversion ") or ": " not in line:
                continue
            pkgs, path = line.rsplit(": ", 1)
            owners[path] = pkgs.split(",")[0].strip().split(":")[0]
    for path, original in fallbacks.items():
        if path not in owners and original in owners:
            owners[path] = owners[original]

    pkgs = sorted(set(owners.values()))
    meta = {}
    if pkgs:
        out = _run("dpkg-query", "-W", "-f=${Package}\t${Version}\t${Installed-Size}\t${Homepage}\n", *pkgs,
                   warnings=warnings)
        for line in out.splitlines():
            pkg, version, size, homepage = (line.split("\t") + ["", "", ""])[:4]
            meta[pkg] = (version, int(size) * 1024 if size.isdigit() else None, homepage)
    manual = _manual_packages(pkgs, warnings)
    upgradable = _apt_upgradable(warnings)

    apps, seen = [], set()
    for path, info in infos.items():
        pkg = owners.get(path)
        if pkg is None:
            apps.append(App(info.get_display_name(), LOCAL, info.get_id() or path, info=info,
                            note=_short_path(path)))
            continue
        if pkg in seen:  # un paquet peut installer plusieurs lanceurs
            continue
        seen.add(pkg)
        version, size, homepage = meta.get(pkg, ("", None, ""))
        app = App(info.get_display_name(), DEB if pkg in manual else APT, pkg, version, size, info)
        launcher_dir = Path(GLib.get_user_data_dir()) / "applications"
        app.local_launchers = [p for p in infos if owners.get(p) == pkg and Path(p).parent == launcher_dir]
        if app.source == APT:
            app.update = upgradable.get(pkg)
        else:
            _check_github(app, homepage, warnings)
        apps.append(app)
    return apps


def _manual_packages(pkgs: list[str], warnings: list[str] | None = None) -> set[str]:
    """Paquets dont la version installée ne vient d'aucun dépôt APT."""
    manual, current, has_repo, installed_row = set(), None, False, False
    for line in _run("apt-cache", "policy", *pkgs, warnings=warnings).splitlines() if pkgs else []:
        if line and not line[0].isspace() and line.endswith(":"):
            if current and not has_repo:
                manual.add(current)
            current, has_repo, installed_row = line[:-1].split(":")[0], False, False
        elif re.match(r"\s+(?:\*\*\*\s+)?\S+\s+-?\d+\s*$", line):
            installed_row = line.lstrip().startswith("***")
        elif installed_row and (m := re.match(r"\s+-?\d+ (\S+)", line)) and m.group(1) != "/var/lib/dpkg/status":
            has_repo = True
    if current and not has_repo:
        manual.add(current)
    return manual


def _apt_upgradable(warnings: list[str] | None = None) -> dict[str, str]:
    result = {}
    for line in _run("apt", "list", "--upgradable", warnings=warnings).splitlines():
        if m := re.match(r"([^/\s]+)/\S+ (\S+) ", line):
            result[m.group(1)] = m.group(2)
    return result


@cache
def _arch_aliases() -> tuple[str, ...]:
    arch = _run("dpkg", "--print-architecture").strip() or "amd64"
    return {"amd64": ("amd64", "x86_64"), "arm64": ("arm64", "aarch64")}.get(arch, (arch,))


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version.split(":", 1)[-1]))


def _check_github(app: App, homepage: str, warnings: list[str]) -> None:
    """Pour un .deb installé à la main, cherche une version plus récente sur GitHub."""
    repo = KNOWN_GITHUB.get(app.ident)
    if m := re.match(r"https?://github\.com/([^/\s]+/[^/\s#?]+)", homepage or ""):
        repo = m.group(1).removesuffix(".git")
    if not repo:
        app.note = "aucune source de mise à jour connue"
        return
    app.note = f"suivi via GitHub ({repo})"
    request = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest",
                                     headers={"Accept": "application/vnd.github+json", "User-Agent": "Manette"})
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            release = json.load(response)
    except (OSError, ValueError):
        app.note = f"GitHub injoignable ({repo})"
        warnings.append(f"{app.name} : {app.note}")
        return
    latest = release.get("tag_name", "").lstrip("vV")
    if not latest or _version_key(latest) <= _version_key(app.version):
        return
    for asset in release.get("assets", []):
        name = asset.get("name", "").lower()
        if name.endswith(".deb") and any(a in name for a in _arch_aliases()):
            app.update, app.update_url = latest, asset["browser_download_url"]
            return


# --- Flatpak, Snap, AppImage ---------------------------------------------

_UNITS = {"b": 1, "byte": 1, "bytes": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12}


def _parse_size(text: str) -> int | None:
    m = re.match(r"([\d.,]+)\s*([a-zA-Z]+)", text.replace(" ", " ").strip())
    if not m:
        return None
    return int(float(m.group(1).replace(",", ".")) * _UNITS.get(m.group(2).lower(), 1))


def _scan_flatpaks(infos: dict[str, Gio.DesktopAppInfo], warnings: list[str]) -> list[App]:
    if not shutil.which("flatpak"):
        if infos:
            warnings.append("Flatpak introuvable : applications non vérifiées")
        return []
    updates = {}
    out = _run("flatpak", "remote-ls", "--updates", "--app", "--columns=application,version", timeout=60,
               warnings=warnings)
    for line in out.splitlines():
        fid, _, version = line.partition("\t")
        if fid:
            updates[fid] = version or "nouvelle révision"
    apps = []
    for line in _run("flatpak", "list", "--app", "--columns=application,name,version,size,installation",
                     warnings=warnings).splitlines():
        parts = line.split("\t")
        if len(parts) != 5:
            continue
        fid, name, version, size, installation = parts
        info = infos.get(fid)
        update = updates.get(fid)
        if update == version:
            update = "nouvelle révision"
        apps.append(App(info.get_display_name() if info else name, FLATPAK, fid, version, _parse_size(size),
                        info, update, note=fid, installation=installation))
    return apps


def _scan_snaps(infos: dict[str, Gio.DesktopAppInfo], warnings: list[str]) -> list[App]:
    if not infos:
        return []
    updates = {}
    for line in _run("snap", "refresh", "--list", warnings=warnings).splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            updates[parts[0]] = parts[1]
    rows = {}
    for line in _run("snap", "list", warnings=warnings).splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3:
            rows[parts[0]] = (parts[1], parts[2])
    apps = []
    for name, info in infos.items():
        version, revision = rows.get(name, ("", ""))
        snap_file = Path(f"/var/lib/snapd/snaps/{name}_{revision}.snap")
        size = snap_file.stat().st_size if snap_file.exists() else None
        apps.append(App(info.get_display_name(), SNAP, name, version, size, info, updates.get(name), note=name))
    return apps


def _scan_appimages(infos: dict[str, Gio.DesktopAppInfo]) -> list[App]:
    found = dict(infos)
    for folder in APPIMAGE_DIRS:
        base = Path(folder).expanduser()
        if not base.is_dir():
            continue
        for path in [*base.glob("*"), *base.glob("*/*")]:
            if path.suffix.lower() == ".appimage" and path.is_file():
                found.setdefault(str(path.resolve()), None)
    apps = []
    for path, info in found.items():
        stem = Path(path).stem
        name = info.get_display_name() if info else re.split(r"[-_ ]v?\d", stem)[0] or stem
        version = m.group(0) if (m := re.search(r"\d+(\.\d+)+", stem)) else ""
        size = os.path.getsize(path) if os.path.exists(path) else None
        app = App(name, APPIMAGE, path, version, size, info, note=_short_path(path))
        launcher = info.get_filename() if info else None
        if launcher and Path(launcher).parent == Path(GLib.get_user_data_dir()) / 'applications':
            app.local_launchers = [launcher]
        apps.append(app)
    return apps


def _short_path(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home):] if path.startswith(home + "/") else path


# --- Commandes ------------------------------------------------------------

def _apt(*args: str) -> list[str]:
    return ["pkexec", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "-y", *args]


def _flatpak_scope(app: App) -> str:
    if app.installation in ("system", "user"):
        return f"--{app.installation}"
    return f"--installation={app.installation}"


def _command(argv: list[str]) -> Command:
    return Command(argv, shlex.join(argv))


def update_command(app: App) -> Command | None:
    if not app.update:
        return None
    if app.source == APT:
        return _command(_apt("install", "--only-upgrade", app.ident))
    if app.source == DEB and app.update_url:
        target = CACHE_DIR / app.update_url.rsplit("/", 1)[-1]
        q = shlex.quote
        script = "\n".join([
            "set -e",
            f"mkdir -p {q(str(CACHE_DIR))}",
            f"echo {q(f'Téléchargement de {target.name}…')}",
            f"curl -fsSL -o {q(str(target))} {q(app.update_url)}",
            "echo 'Installation…'",
            f"pkexec env DEBIAN_FRONTEND=noninteractive apt-get -y install {q(str(target))}",
            f"rm -f {q(str(target))}",
        ])
        return Command(["bash", "-c", script], f"curl {app.update_url}\napt-get install ./{target.name}")
    if app.source == FLATPAK:
        return _command(["flatpak", "update", "-y", _flatpak_scope(app), app.ident])
    if app.source == SNAP:
        return _command(["pkexec", "snap", "refresh", app.ident])
    return None


def update_all_command(apps: list[App]) -> Command | None:
    """Met à jour toutes les apps données, avec une seule demande de mot de passe."""
    q = shlex.quote
    apps = [a for a in apps if update_command(a)]
    apt = [a.ident for a in apps if a.source == APT]
    debs = [(a, CACHE_DIR / a.update_url.rsplit("/", 1)[-1]) for a in apps if a.source == DEB]
    snaps = [a.ident for a in apps if a.source == SNAP]
    flatpaks: dict[str, list[str]] = {}
    for app in apps:
        if app.source == FLATPAK:
            flatpaks.setdefault(_flatpak_scope(app), []).append(app.ident)
    if not apps:
        return None

    # Côté utilisateur : téléchargement des .deb, puis tout ce qui demande les droits en un seul pkexec.
    script, root, display = ["status=0"], ["export DEBIAN_FRONTEND=noninteractive", "s=0"], []
    if debs:
        script.append(f"mkdir -p {q(str(CACHE_DIR))}")
    for app, target in debs:
        script += [f"echo {q(f'== Téléchargement de {app.name} {app.update} ==')}",
                   f"curl -fsSL -o {q(str(target))} {q(app.update_url)} || {{ status=1; rm -f {q(str(target))}; }}"]
        display.append(f"curl {app.update_url}")
    if apt:
        root += ['echo "== Paquets APT =="', f"apt-get -y install --only-upgrade {shlex.join(apt)} || s=1"]
        display.append(f"apt-get install --only-upgrade {' '.join(apt)}")
    for app, target in debs:
        root += [f"if [ -f {q(str(target))} ]; then",
                 f"  echo {q(f'== Installation de {app.name} {app.update} ==')}",
                 f"  apt-get -y install {q(str(target))} || s=1",
                 "fi"]
        display.append(f"apt-get install ./{target.name}")
    if snaps:
        root += ['echo "== Snap =="', f"snap refresh {shlex.join(snaps)} || s=1"]
        display.append(f"snap refresh {' '.join(snaps)}")
    if apt or debs or snaps:
        script.append(f"pkexec bash -c {q(chr(10).join([*root, 'exit $s']))} || status=1")
    for scope, ids in flatpaks.items():
        script += ['echo "== Flatpak =="', f"flatpak update -y {scope} {shlex.join(ids)} || status=1"]
        display.append(f"flatpak update {' '.join(ids)}")
    for _app, target in debs:
        script.append(f"rm -f {q(str(target))}")
    script.append("exit $status")
    return Command(["bash", "-c", "\n".join(script)], "\n".join(display))


def remove_command(app: App) -> Command | None:
    """Commande de désinstallation ; None pour les AppImage (mises à la corbeille) et les lanceurs locaux."""
    if app.source in (APT, DEB):
        return _command(_apt("remove", app.ident))
    if app.source == FLATPAK:
        return _command(["flatpak", "uninstall", "-y", _flatpak_scope(app), app.ident])
    if app.source == SNAP:
        return _command(["pkexec", "snap", "remove", app.ident])
    return None


class RemovalPreviewError(RuntimeError):
    """La suppression ne doit pas être proposée sans simulation réussie."""


def apt_removal_preview(*args: str) -> list[str]:
    """Simulation sans droits ; une erreur ne représente jamais une liste vide."""
    try:
        result = subprocess.run(["apt-get", "-s", *args], capture_output=True, text=True, timeout=30,
                                env={**os.environ, "LC_ALL": "C.UTF-8"})
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RemovalPreviewError(f"Simulation APT impossible : {error}") from error
    if result.returncode:
        detail = result.stderr.strip() or f"code {result.returncode}"
        raise RemovalPreviewError(f"Simulation APT échouée : {detail}")
    return re.findall(r"^Remv (\S+)", result.stdout, re.M)


def removal_preview(app: App) -> list[str]:
    return apt_removal_preview("remove", app.ident)
