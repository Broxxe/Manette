# Manette

English · [Français](README.fr.md)

A GTK 4 + libadwaita desktop app for managing applications and everyday system tasks on Ubuntu and APT-based Linux systems.

## Features

- **Applications:** launch, update and remove detected APT, Flatpak, Snap, AppImage and local applications. Install downloaded `.deb` and Flatpak files, or launch AppImages.
- **Flexible interface:** compact cards or list view, favorites, English/French interface and adjustable background opacity.
- **Global search:** find applications, commands, settings and associated folders with **Ctrl+K**.
- **Storage:** graphical folder usage, linked application data, space estimates before installation and a retained-data summary after removal.
- **Maintenance:** system updates, cleanup, update diagnostics and live resource monitoring.
- **Custom commands:** save commands as buttons, with optional terminal execution.
- **History:** review the last 500 operations, filter failures and copy reports with **Ctrl+H**. Show the live console with **Ctrl+J**.

## Run

Requires Python 3, PyGObject, GTK 4 and a recent libadwaita. `python3-apt` enables APT space estimates; Flatpak and Snap support requires their respective tools.

```sh
./bin/manette
```

To install for the current user and add an application-menu entry:

```sh
./install.sh
```

Installation requires no administrator privileges and creates an isolated copy, preserving the working repository and user preferences.

## Updates and safeguards

Managed installations can automatically download Manette updates from the default branch of **Broxxe/Manette** on GitHub. Updates apply on the next launch; automatic checks can be disabled in settings.

System changes use the normal administrator authorization prompt when needed. Cleanup and removals ask for confirmation; APT removals show a package preview. Application data is kept unless separately selected for removal. Protected or identified shared folders are blocked, but folder detection can be incomplete.

Space estimates use local APT metadata. Snap, Flatpak and unresolved sizes are marked as unknown. Diagnostics suggest causes without automatically repairing the system. Custom commands remain executable code; downloaded-file validation does not establish trust.

## Development

```sh
python3 -m unittest discover -s tests -v
```

Tests simulate package managers and privileged operations without changing installed applications.
