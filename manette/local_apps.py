"""Préparation des applications téléchargées, sans les exécuter."""

from .i18n import _ as tr

from dataclasses import dataclass
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import tempfile

from .scanner import Command


@dataclass
class Download:
    path: Path
    kind: str
    description: str
    command: Command | None = None


def inspect_file(filename: str) -> Download:
    path = Path(filename).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError(tr("Sélectionnez un fichier d'application."))
    suffix = path.suffix.lower()
    if suffix == '.deb':
        result = subprocess.run(['dpkg-deb', '--show', '--showformat=${Package}\n${Version}\n${Architecture}\n', str(path)],
                                capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise ValueError(tr("Ce fichier n'est pas un paquet .deb valide."))
        fields = result.stdout.strip().splitlines()
        if len(fields) != 3:
            raise ValueError(tr('Les informations du paquet .deb sont incomplètes.'))
        name, version, arch = fields
        argv = ['pkexec', 'env', 'DEBIAN_FRONTEND=noninteractive', 'apt-get', '-y', '--no-remove', 'install', str(path)]
        return Download(path, 'deb', tr('{value0} · {value1} · {value2}\n\nInstallation avec APT et ses dépendances, avec autorisation administrateur. Ce paquet peut exécuter des scripts avec ces droits. La validation du format ne garantit pas sa fiabilité.', value0=name, value1=version, value2=arch),
                        Command(argv, shlex.join(argv)))
    if suffix == '.appimage':
        with path.open('rb') as stream:
            header = stream.read(11)
        if header[:4] != b'\x7fELF' or header[8:11] not in (b'AI\x01', b'AI\x02'):
            raise ValueError(tr("Ce fichier n'est pas une AppImage reconnue."))
        return Download(path, 'appimage', tr("L'application sera lancée depuis ce fichier, sans installation. Si nécessaire, Manette lui donnera le droit d'exécution. Elle aura accès à vos fichiers avec les droits de votre compte, sans isolation par Manette."))
    if suffix in ('.flatpakref', '.flatpak'):
        if not shutil.which('flatpak'):
            raise ValueError(tr('Flatpak doit être installé pour ouvrir ce fichier.'))
        argv = ['flatpak', 'install', '--user', '-y', str(path)]
        return Download(path, 'flatpak', tr('Installation Flatpak pour votre compte utilisateur, avec ses dépendances.'),
                        Command(argv, shlex.join(argv)))
    raise ValueError(tr('Formats pris en charge : .deb, .AppImage, .flatpakref et .flatpak.'))


def launch_appimage(download: Download) -> None:
    # Appelé uniquement après la confirmation de l'utilisateur.
    if download.kind != 'appimage':
        raise ValueError(tr("Ce fichier n'est pas une AppImage."))
    path = download.path
    path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IXUSR)
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen([str(path)], cwd=path.parent, start_new_session=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors)
        try:
            code = proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            return  # L'application continue indépendamment de Manette.
        if code:
            errors.seek(0)
            detail = errors.read(4096).decode('utf-8', 'replace').strip()
            raise ValueError(detail or tr("L'application s'est arrêtée avec le code {value0}.", value0=code))
