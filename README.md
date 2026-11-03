# Manette — Linux application and system manager

English · [Français](README.fr.md)

A graphical application manager and system maintenance tool for Ubuntu: manage APT, Flatpak, Snap and AppImage applications, check system updates, analyze disk usage and monitor CPU/GPU resources.

An independent GPLv3 project built with Python, GTK 4 and libadwaita. See [Compatibility](#compatibility) for supported dependencies and the tested environment.

<img width="1266" height="816" alt="Capture d’écran du 2026-11-03 17-51-38" src="https://github.com/user-attachments/assets/fbf361f0-2017-4e8a-9505-23dd8f1bb172" />

<img width="1248" height="821" alt="Capture d’écran du 2026-11-03 17-50-30" src="https://github.com/user-attachments/assets/af5874e7-dd7e-47ff-9328-a54727ec9ec0" />


## Features

- **Applications:** launch, update and remove detected APT, Flatpak, Snap, AppImage and local applications. Install downloaded `.deb` and Flatpak files, or launch AppImages.
- **Categories:** automatic grouping by purpose (system, games, work, creative, development and more), with collapsible titled sections and counters in both grid and list views. Click a heading to fold or unfold its category; this choice is saved and shared between views. Search, filters, favorites and sorting work within these sections. Classification uses desktop metadata; each app appears once, and category filters also match its secondary categories. Missing metadata falls under Other. Personal choices are available from the **⋯ → Change category…** menu.
- **Flexible interface:** compact cards or list view, favorites, English/French interface and adjustable background opacity.
- **Global search:** find applications, commands, settings and associated folders with **Ctrl+K**.
- **Storage:** graphical folder usage, linked application data, space estimates before installation and a retained-data summary after removal.
- **Maintenance:** system updates, cleanup, update diagnostics and live resource monitoring, with logical CPU bars grouped by physical core.
- **Custom commands:** save commands as buttons, with optional terminal execution.
- **History:** review the last 500 operations, filter failures and copy reports with **Ctrl+H**. Show the live console with **Ctrl+J**.

## Compatibility

| Environment | Status |
| --- | --- |
| Ubuntu 26.04 LTS, x86_64 | Current development environment: 26.04.1; local tests and GTK checks pass. |
| Ubuntu 22.04 / 24.04, standard packages | Not compatible with the current interface dependencies. |
| Other Linux distributions, desktops or architectures | Not validated; package maintenance targets APT-based systems. |

API baseline: **Python 3.10+, GTK 4.18+, libadwaita 1.7+ and PyGObject**. Meeting these versions is not a tested-platform guarantee. The reference environment uses Python 3.14.4, GTK 4.22.4 and libadwaita 1.9.1.

The interface uses [Adw.WrapBox, introduced in libadwaita 1.7](https://gnome.pages.gitlab.gnome.org/libadwaita/doc/main/class.WrapBox.html), and [GTK CSS variables](https://docs.gtk.org/gtk4/css-properties.html). Ubuntu 24.04 provides [libadwaita 1.5](https://packages.ubuntu.com/fr/noble/libadwaita-1-0). Supporting it requires code adaptations or a suitable runtime package.

Flatpak, Snap, firmware tools and GPU tools enable their respective features when installed. Service management needs systemd; administrator actions need `pkexec` and a desktop authorization agent. GPU metrics currently cover NVIDIA (`nvidia-smi`) and AMD (`sysfs`), depending on driver support; Intel GPU metrics are not implemented. Background transparency depends on desktop support.

## Run

On the reference Ubuntu environment, install the runtime dependencies if needed:

```sh
sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-apt pkexec curl
```

`python3-apt` enables APT space estimates. This command does not make older Ubuntu releases compatible.

Start from the repository:

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

## License

Copyright © 2026 Broxxe. Manette is licensed under the **GNU General Public License v3.0 only** (`GPL-3.0-only`); see [LICENSE](LICENSE). You may use, modify and redistribute it, including commercially. Redistributed modified versions must provide the corresponding source under GPLv3 and retain the required notices. No warranty is provided.
