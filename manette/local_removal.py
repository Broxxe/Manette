"""Retrait prudent des applications portables et des lanceurs personnels."""

from .i18n import _ as tr

from dataclasses import dataclass
import os
import shutil
from pathlib import Path

from gi.repository import Gio, GLib


@dataclass
class Plan:
    launcher: Path
    bundle: Path | None
    stamps: list[tuple]
    manual: bool = False


def _stamp(path):
    info = path.lstat()
    return (info.st_dev, info.st_ino, info.st_mtime_ns)


def _executable(info):
    try:
        _, argv = GLib.shell_parse_argv(info.get_commandline() or '')
    except GLib.Error:
        return None
    if not argv or not Path(argv[0]).is_absolute():
        return Path(found) if argv and (found := shutil.which(argv[0])) else None
    return Path(argv[0])


def _program_paths(info):
    try:
        _, argv = GLib.shell_parse_argv(info.get_commandline() or '')
    except GLib.Error:
        return []
    targets = []
    executable = _executable(info)
    if executable is not None:
        targets.append(executable.resolve())
    targets.extend(Path(arg).resolve() for arg in argv[1:] if Path(arg).is_absolute() and Path(arg).is_file())
    return targets


def _manual_bundle(info, directory):
    root = Path(directory).absolute()
    protected = {Path('/'), Path.home(), Path.home().parent,
                 *(Path.home() / name for name in (tr('Applications'), 'AppImages', 'opt', '.local', '.local/bin',
                                                    '.local/opt', '.local/share', '.config', '.cache', '.var', 'snap')),
                 *(Path(p) for p in (GLib.get_user_config_dir(), GLib.get_user_data_dir(), GLib.get_user_cache_dir()))}
    for value in range(int(GLib.UserDirectory.N_DIRECTORIES)):
        special = GLib.get_user_special_dir(GLib.UserDirectory(value))
        if special:
            protected.add(Path(special))
    if root in protected or root in Path.home().parents or root == root.parent or os.path.ismount(root):
        raise ValueError(tr('Choisissez le dossier propre à cette application, pas un dossier général ou un disque entier.'))
    if not root.is_dir() or root.resolve() != root or root.stat().st_uid != os.getuid():
        raise ValueError(tr('Choisissez un dossier vous appartenant, sans lien symbolique. Aucun droit administrateur ne sera demandé.'))
    targets = _program_paths(info)
    if not any(target.is_relative_to(root) for target in targets):
        raise ValueError(tr("Ce dossier ne contient aucun fichier de programme indiqué dans le lanceur. Manette ne peut pas le retirer comme dossier d'installation."))
    return root


def preview(app, directory=None) -> Plan:
    if app.info is None:
        raise ValueError(tr('Aucun lanceur personnel identifié.'))
    launcher = Path(app.info.get_filename() or '')
    launcher_dir = Path(GLib.get_user_data_dir()) / 'applications'
    if launcher.parent != launcher_dir or launcher.suffix != '.desktop' or launcher.is_symlink() or not launcher.is_file():
        raise ValueError(tr("Ce lanceur n'est pas un fichier personnel que Manette peut retirer."))
    executable = _executable(app.info)
    bundle = None
    if directory is not None:
        bundle = _manual_bundle(app.info, directory)
    elif executable is not None and executable.is_file() and executable.resolve() == executable:
        root = executable.parent
        bases = [Path.home() / name for name in (tr('Applications'), 'AppImages', 'opt', '.local/opt')]
        contained = any(root != base and root.is_relative_to(base) for base in bases)
        appimage = (root / 'AppRun').is_file() and any(root.glob('*.desktop'))
        pyinstaller = root.name == executable.name and (root / '_internal').is_dir()
        if contained and (appimage or pyinstaller):
            bundle = root
    if bundle is not None:
        # Ne pas proposer un dossier qui contient d'autres applications enregistrées.
        for other in Gio.AppInfo.get_all():
            if not isinstance(other, Gio.DesktopAppInfo) or other.get_filename() == str(launcher):
                continue
            if any(target.is_relative_to(bundle) for target in _program_paths(other)):
                if directory is not None:
                    raise ValueError(tr("Ce dossier contient aussi le programme d'une autre application. Son retrait est bloqué."))
                bundle = None
                break
    paths = ([bundle] if bundle else []) + [launcher]
    return Plan(launcher, bundle, [_stamp(path) for path in paths], directory is not None)


def execute(app, plan, trash):
    """Revérifie le plan avant toute action ; trash est la corbeille du bureau."""
    current = preview(app, plan.bundle if plan.manual else None)
    if (current.launcher, current.bundle, current.stamps) != (plan.launcher, plan.bundle, plan.stamps):
        raise ValueError(tr('Les fichiers ont changé depuis la confirmation. Réessayez pour revoir les éléments à retirer.'))
    for path in ([plan.bundle] if plan.bundle else []) + [plan.launcher]:
        trash(path)
