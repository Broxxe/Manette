"""Infos sur la machine et actions système toutes prêtes."""

from __future__ import annotations

import os
import platform
import re
import shutil
import socket
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REAL_FS = {"ext2", "ext3", "ext4", "btrfs", "xfs", "f2fs", "vfat", "exfat", "ntfs", "ntfs3", "fuseblk", "zfs",
           "bcachefs"}


def space_warnings(paths: list[str | Path]) -> list[str]:
    """Seuil préventif, pas une estimation de la taille de l'opération."""
    warnings, seen = [], set()
    for value in paths:
        path = Path(value).expanduser()
        while not path.exists() and path != path.parent:
            path = path.parent
        try:
            device = path.stat().st_dev
            if device in seen:
                continue
            seen.add(device)
            free = shutil.disk_usage(path).free
            if free < 5 * 1024**3:
                amount = f"{free / 1024**3:.1f}".replace(".", ",")
                warnings.append(f"{path} : {amount} Gio libres (moins de 5 Gio)")
        except OSError:
            warnings.append(f"{path} : espace libre impossible à vérifier")
    return warnings


@dataclass
class Disk:
    label: str
    mount: str
    device: str
    total: int
    used: int
    free: int


def disks() -> list[Disk]:
    result, seen = [], set()
    with open("/proc/mounts") as mounts:
        for line in mounts:
            device, mount, fstype = line.split()[:3]
            mount = re.sub(r"\\(\d{3})", lambda m: chr(int(m.group(1), 8)), mount)
            if fstype not in REAL_FS or device in seen or mount.startswith(("/boot", "/snap", "/var/snap", "/var/lib")):
                continue
            try:
                st = os.statvfs(mount)
            except OSError:
                continue
            total = st.f_blocks * st.f_frsize
            if not total:
                continue
            seen.add(device)
            used = total - st.f_bfree * st.f_frsize
            result.append(Disk(_disk_label(mount), mount, device, total, used, st.f_bavail * st.f_frsize))
    return result


def _disk_label(mount: str) -> str:
    if mount == "/":
        return "Système"
    if mount == str(Path.home()) or mount == "/home":
        return "Dossier personnel"
    return Path(mount).name


def overview() -> dict[str, str | float]:
    os_name = platform.system()
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                os_name = line.split("=", 1)[1].strip('"')
    except OSError:
        pass

    seconds = int(float(Path("/proc/uptime").read_text().split()[0]))
    days, rest = divmod(seconds, 86400)
    hours, minutes = rest // 3600, rest % 3600 // 60
    uptime = f"{days} j {hours} h" if days else f"{hours} h {minutes:02d}" if hours else f"{minutes} min"

    mem = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        mem[key] = int(value.split()[0]) * 1024
    total, available = mem.get("MemTotal", 0), mem.get("MemAvailable", 0)

    return {"os": os_name, "kernel": platform.release(), "host": socket.gethostname(), "uptime": uptime,
            "mem_total": total, "mem_used": total - available,
            "mem_fraction": (total - available) / total if total else 0}


# --- Ce que chaque nettoyage peut libérer ---------------------------------

def _du(path: str | Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def _c_output(*argv: str) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=20,
                              env={**os.environ, "LC_ALL": "C.UTF-8"}).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _journal_size() -> int | None:
    m = re.search(r"take up ([\d.]+)([KMGT]?)", _c_output("journalctl", "--disk-usage"))
    if not m:
        return None
    return int(float(m.group(1)) * 1024 ** " KMGT".index(m.group(2) or " "))


def _old_snaps_size() -> int:
    total = 0
    for line in _c_output("snap", "list", "--all").splitlines()[1:]:
        parts = line.split()
        if "disabled" in line and len(parts) >= 3:
            path = Path(f"/var/lib/snapd/snaps/{parts[0]}_{parts[2]}.snap")
            total += path.stat().st_size if path.exists() else 0
    return total


# --- Actions --------------------------------------------------------------

@dataclass
class Action:
    title: str
    subtitle: str
    icon: str
    command: str
    display: str = ""
    root: bool = False
    rescan: bool = False  # relancer l'analyse des applications ensuite
    confirm: bool = False
    measure: Callable[[], int | None] | None = None
    check_space: bool = False
    destructive: bool = False
    confirmation: str = ""
    preview_autoremove: bool = False
    view: str = ""


CHECK_UPDATES = """
pkexec apt-get update -q || exit $?
status=0
echo; echo "== Paquets APT =="
apt list --upgradable || status=1
if command -v snap >/dev/null 2>&1; then
  echo; echo "== Snap =="
  snap refresh --list || status=1
fi
if command -v flatpak >/dev/null 2>&1; then
  echo; echo "== Flatpak =="
  flatpak remote-ls --updates --app || status=1
fi
exit $status
"""

UPDATE_ALL = """
with_snap=0
command -v snap >/dev/null 2>&1 && with_snap=1
pkexec bash -c '
  s=0
  echo "== APT =="
  apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get -y --with-new-pkgs upgrade; a=$?
  if [ "$1" = 1 ]; then
    echo; echo "== Snap =="
    snap refresh; s=$?
  fi
  exit $((a || s))
' manette "$with_snap"; root=$?
f=0
if command -v flatpak >/dev/null 2>&1; then
  echo; echo "== Flatpak =="
  flatpak update -y; f=$?
fi
exit $((root || f))
"""

OLD_SNAPS = """
pkexec bash -c '
  LC_ALL=C snap list --all | awk "/disabled/{print \\$1, \\$3}" | while read name rev; do
    echo "Suppression de $name (révision $rev)"
    snap remove "$name" --revision="$rev"
  done
  echo "Plus aucune ancienne révision."
'
"""

BIG_PACKAGES = r"""dpkg-query -W -f='${Installed-Size}\t${Package}\n' | sort -rn | head -n 25 | awk -F'\t' '{printf "%9.1f Mo  %s\n", $1/1024, $2}'"""


def action_groups() -> list[tuple[str, str, list[Action]]]:
    updates = [
        Action("Vérifier les mises à jour", "Actualise les sources et liste ce qui peut être mis à jour",
               "view-refresh-symbolic", CHECK_UPDATES, "apt-get update · apt list --upgradable · snap · flatpak",
               root=True, rescan=True),
        Action("Tout mettre à jour", "APT, Snap et Flatpak en une seule fois", "software-update-available-symbolic",
               UPDATE_ALL, "apt-get upgrade · snap refresh · flatpak update", root=True, rescan=True, confirm=True,
               check_space=True),
    ]
    if shutil.which("fwupdmgr"):
        updates.append(Action("Firmwares", "Mises à jour du BIOS et des périphériques (fwupd)",
                              "application-x-firmware-symbolic", "fwupdmgr refresh --force; fwupdmgr get-updates"))

    cleanup = [
        Action("Paquets devenus inutiles", "Dépendances qui ne servent plus à rien", "edit-clear-all-symbolic",
               "pkexec env DEBIAN_FRONTEND=noninteractive apt-get -y autoremove", root=True, rescan=True,
               confirm=True, destructive=True, preview_autoremove=True),
        Action("Cache des paquets APT", "Les .deb déjà installés, gardés pour rien", "folder-download-symbolic",
               "pkexec apt-get clean && echo 'Cache APT vidé.'", root=True, confirm=True, destructive=True,
               confirmation="Les paquets téléchargés du cache APT seront supprimés. Une prochaine installation "
                            "pourra devoir les télécharger à nouveau. Les applications installées sont conservées.",
               measure=lambda: _du("/var/cache/apt/archives")),
        Action("Anciennes versions des Snaps", "Snap garde les révisions précédentes de chaque app",
               "view-paged-symbolic", OLD_SNAPS, "snap remove --revision (révisions désactivées)", root=True,
               confirm=True, destructive=True, measure=_old_snaps_size,
               confirmation="Les révisions désactivées seront supprimées. Tu perdras la possibilité de revenir "
                            "à ces anciennes versions. Les révisions actives sont conservées."),
        Action("Runtimes Flatpak inutilisés", "Bibliothèques qui ne servent plus à aucune app",
               "application-x-addon-symbolic", "flatpak uninstall --unused -y", confirm=True, destructive=True,
               confirmation="Les runtimes Flatpak considérés comme inutilisés seront supprimés. Ils pourront "
                            "être téléchargés à nouveau si une application en a besoin."),
        Action("Journaux système", "Ne garde que les 200 derniers Mo de journaux", "text-x-generic-symbolic",
               "pkexec journalctl --vacuum-size=200M", root=True, confirm=True, destructive=True, measure=_journal_size,
               confirmation="Les anciens journaux archivés seront supprimés pour viser 200 Mo. "
                            "Cet historique de diagnostic ne pourra pas être récupéré."),
        Action("Miniatures en cache", "Aperçus d'images régénérés automatiquement", "image-x-generic-symbolic",
               'rm -rf "$HOME/.cache/thumbnails/"* && echo "Miniatures supprimées."',
               confirm=True, destructive=True,
               confirmation="Les miniatures en cache seront supprimées puis régénérées au besoin. "
                            "Les photos et documents d'origine sont conservés.",
               measure=lambda: _du(Path.home() / ".cache" / "thumbnails")),
    ]

    diagnostic = [
        Action("Ce qui prend de la place chez toi", "Les plus gros dossiers de ton dossier personnel",
               "folder-symbolic", "", view="storage"),
        Action("Les plus gros paquets", "Les 25 paquets APT qui pèsent le plus lourd", "package-x-generic-symbolic",
               BIG_PACKAGES, "dpkg-query … | sort -rn | head -n 25"),
        Action("Services en échec", "Services système et utilisateur qui ont planté", "dialog-warning-symbolic",
               "systemctl --failed --no-pager; echo; systemctl --user --failed --no-pager"),
        Action("Erreurs depuis le démarrage", "Les 60 dernières erreurs du journal", "dialog-error-symbolic",
               "journalctl -b -p 3 --no-pager -n 60"),
        Action("Réseau", "Interfaces, adresses IP et route par défaut", "network-wired-symbolic",
               "ip -br address; echo; ip route | head -n 5"),
    ]
    if shutil.which("sensors"):
        diagnostic.append(Action("Températures", "Capteurs du processeur, de la carte mère et des disques",
                                 "weather-clear-symbolic", "sensors"))

    return [("Mises à jour", "Garder tout le système à jour", updates),
            ("Nettoyage", "Récupérer de l'espace disque", cleanup),
            ("Diagnostic", "Comprendre ce qui se passe sur la machine", diagnostic)]
