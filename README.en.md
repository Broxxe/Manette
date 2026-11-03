# Manette

English · [Français](README.md)

A GNOME application built with GTK 4, libadwaita and Python for managing applications,
system maintenance and custom commands.

- **Applications:** inspect APT, manually installed .deb packages, Flatpak, Snap, AppImage
  and local launchers. Launch, update or remove applications using their installation method.
  Open downloaded .deb, .flatpakref, .flatpak and AppImage files with confirmation.
  Choose large cards in **Grid** view or a **List**. Each card has a large Play button and
  a **⋯** menu in the bottom right for linked folders, updates and removal. Search, filters
  and sorting work in both views, and the layout preference is saved.
- **Data and linked folders:** inspect application data separately from program size,
  open detected folders, and manually link folders to any application. Unlinking never deletes files.
- **System:** check updates, manage cleanup, inspect drives and run diagnostics.
  **Home folder storage** shows a graphical summary with sizes, proportional bars and an
  **Open** button for every folder, including hidden folders.
- **Monitor:** live CPU, memory, GPU and application usage.
- **My commands:** create, edit and duplicate command buttons. New commands ask for confirmation
  by default; confirmation is required when the administrator option is enabled.

Commands run in the console with live output. Administrator operations use system authorization
through pkexec, or sudo for custom commands opened in a terminal. Cleanup actions explain their
effects before confirmation. APT removal previews list affected packages and block the operation
if simulation fails. Low disk space triggers a warning before updates and installations.

Local portable applications are moved to the trash only after reviewing the exact paths.
An unknown installation can be handled by selecting its installation folder, subject to safety
checks, or by removing its shortcut only. Removing a shortcut is not an uninstall. Data outside
the selected installation folder is preserved. Download format validation does not certify trust.

## Run and install

```sh
./bin/manette
./install.sh
```

The installer creates an isolated user installation, registers it in the applications menu
and enables automatic updates. No administrator privileges are needed. The working repository,
personal commands and preferences are preserved. Python 3, PyGObject, GTK 4 and a recent
libadwaita must be available on the system.

## Language and automatic updates

Open **Preferences and updates** to select **English**, **Français** or **System language**.
Restart Manette to apply the language. User-provided names and commands are not translated;
system tools produce their own output.
The settings button in the header also provides the layout and translucent background options.
Translucency leaves text and controls opaque, adapts to light and dark themes, and is disabled
in high contrast mode. Its appearance depends on desktop support.

For an older installation launched directly from the repository, choose **Enable updates**, then
restart Manette from the applications menu. Running `./install.sh` also enables managed updates.

Manette checks the default branch of the **Broxxe/Manette** GitHub repository on startup and
daily while open, at most once every 24 hours. Downloads are prepared in the background and
activated on the next launch. Running commands are not interrupted. Automatic updates can be
disabled; **Check now** remains available.

Updates use HTTPS, validate archive paths, sizes and Python syntax, and keep the active version
if downloading or validation fails. Older or divergent remote revisions are rejected. Updates
require neither Git in the managed installation nor administrator privileges. This mechanism
distributes published repository code; unpublished local changes are not sent to other installations.

Versions are stored in `$XDG_DATA_HOME/manette/versions`, normally
`~/.local/share/manette/versions`. The preceding version is kept through the `previous` link and
can be launched with `~/.local/share/manette/previous/bin/manette` if needed. Adjust the path
when using a custom XDG data directory.

## Checks

```sh
python3 -m unittest discover -s tests -v
```

Tests simulate package managers and privileged operations. They do not update or uninstall
applications on the host system.
