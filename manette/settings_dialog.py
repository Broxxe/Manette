"""Langue et mises à jour de Manette."""

import threading

from gi.repository import Adw, GLib, Gtk

from . import preferences, updater
from .i18n import _


class SettingsDialog(Adw.Dialog):
    def __init__(self, window):
        super().__init__(title=_('Préférences'), content_width=620, content_height=480)
        self.window = window
        self.closed = False
        self._opacity_save_source = 0
        self.connect('closed', self._closed)
        try:
            settings = preferences.load()
        except (OSError, ValueError):
            settings = {}
        page = Adw.PreferencesPage()
        appearance = Adw.PreferencesGroup(title=_('Apparence'))
        view = settings.get('applications_view', 'grid')
        self.view = Adw.ComboRow(title=_('Présentation des applications'),
                                 model=Gtk.StringList.new([_('Mosaïque'), _('Liste')]),
                                 selected=1 if view == 'list' else 0)
        self.view.connect('notify::selected', lambda row, *_: self.window.apps_page.set_view(
                          'list' if row.get_selected() == 1 else 'grid'))
        appearance.add(self.view)
        self.translucent = Adw.SwitchRow(title=_('Fond translucide'),
            subtitle=_('Selon le bureau utilisé. Désactivé en mode contraste élevé.'),
            active=bool(settings.get('translucent', True)))
        self.translucent.connect('notify::active', self._save_translucency)
        appearance.add(self.translucent)
        opacity = preferences.background_opacity(settings)
        opacity_row = Adw.ActionRow(title=_('Opacité du fond'),
                                    subtitle=_('0 % : transparent · 100 % : opaque'))
        controls = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        self.opacity_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.opacity_scale.set_size_request(160, -1)
        self.opacity_scale.set_draw_value(False)
        self.opacity_scale.set_value(opacity)
        self.opacity_scale.set_sensitive(self.translucent.get_active())
        self.opacity_scale.update_property([Gtk.AccessibleProperty.LABEL], [_('Opacité du fond')])
        self.opacity_value = Gtk.Label(label=f'{opacity} %', width_chars=5, xalign=1)
        self.opacity_scale.connect('value-changed', self._preview_opacity)
        controls.append(self.opacity_scale)
        controls.append(self.opacity_value)
        opacity_row.add_suffix(controls)
        appearance.add(opacity_row)
        page.add(appearance)
        language_group = Adw.PreferencesGroup(title=_('Langue de l’interface'))
        choices = ['system', 'fr', 'en']
        self.language = Adw.ComboRow(title=_('Langue'), model=Gtk.StringList.new([_('Langue du système'), 'Français', 'English']))
        self.language.set_selected(choices.index(settings.get('language', 'system')) if settings.get('language', 'system') in choices else 0)
        self.language.connect('notify::selected', lambda row, *_: self._save_language(choices[row.get_selected()]))
        language_group.add(self.language)
        page.add(language_group)
        group = Adw.PreferencesGroup(title=_('Mises à jour de Manette'),
            description=_('Les nouvelles versions proviennent du dépôt GitHub Broxxe/Manette. '
                          'Elles sont préparées sans droits administrateur et appliquées au prochain lancement.'))
        managed = updater.managed()
        self.automatic = Adw.SwitchRow(title=_('Mises à jour automatiques'),
            subtitle=_('Recherche au démarrage puis chaque jour, au maximum une fois par jour.'),
            active=settings.get('automatic_updates', True) if managed else False, sensitive=managed)
        self.automatic.connect('notify::active', self._save_automatic)
        group.add(self.automatic)
        self.status = Adw.ActionRow(title=_('État'), subtitle=_('Prêt à rechercher une nouvelle version.') if managed else
            _('Activez les mises à jour pour cette installation, puis relancez Manette.'))
        self.button = Gtk.Button(label=_('Rechercher maintenant') if managed else _('Activer les mises à jour'),
                                 valign=Gtk.Align.CENTER, css_classes=['suggested-action'])
        self.button.connect('clicked', lambda *_: self._check() if managed else self._enable())
        self.status.add_suffix(self.button)
        group.add(self.status)
        page.add(group)
        view = Adw.ToolbarView(content=page)
        view.add_top_bar(Adw.HeaderBar())
        self.set_child(view)

    def _save_language(self, selected):
        try:
            preferences.save(language=selected)
            self.status.set_subtitle(_('Relancez Manette pour appliquer la langue choisie.'))
        except (OSError, ValueError) as error:
            self.status.set_subtitle(_('Préférences non enregistrées : {value0}', value0=error))

    def _save_translucency(self, row, *unused):
        try:
            preferences.save(translucent=row.get_active())
            self.opacity_scale.set_sensitive(row.get_active())
            self.window.apply_appearance(opacity=round(self.opacity_scale.get_value()))
        except (OSError, ValueError) as error:
            self.status.set_subtitle(_('Préférences non enregistrées : {value0}', value0=error))

    def _preview_opacity(self, scale):
        opacity = round(scale.get_value())
        self.opacity_value.set_label(f'{opacity} %')
        self.window.apply_appearance(opacity=opacity)
        if self._opacity_save_source:
            GLib.source_remove(self._opacity_save_source)
        self._opacity_save_source = GLib.timeout_add(250, self._save_opacity)

    def _save_opacity(self):
        self._opacity_save_source = 0
        try:
            preferences.save(background_opacity=round(self.opacity_scale.get_value()))
        except (OSError, ValueError) as error:
            self.status.set_subtitle(_('Préférences non enregistrées : {value0}', value0=error))
        return False

    def _closed(self, *unused):
        self.closed = True
        if self._opacity_save_source:
            GLib.source_remove(self._opacity_save_source)
            self._save_opacity()

    def _save_automatic(self, row, *unused):
        try:
            preferences.save(automatic_updates=row.get_active())
            if row.get_active():
                automatic_check(self.window)
        except (OSError, ValueError) as error:
            self.status.set_subtitle(_('Préférences non enregistrées : {value0}', value0=error))

    def _enable(self):
        self.window.confirm(_('Activer les mises à jour de Manette ?'),
            _('Une installation utilisateur sera créée sans modifier les fichiers de travail actuels. '
              'Les futures versions seront téléchargées automatiquement depuis GitHub Broxxe/Manette. '
              'Les préférences et commandes personnelles sont conservées.'),
            _('Activer'), lambda: self._start('install'), destructive=False)

    def _check(self):
        self._start('check')

    def _start(self, operation):
        self.button.set_sensitive(False)
        self.status.set_subtitle(_('Préparation en cours…'))
        threading.Thread(target=self._work, args=(operation,), daemon=True).start()

    def _work(self, operation):
        try:
            if operation == 'install':
                updater.install_local()
                result = 'installed'
            else:
                result = updater.check(force=True)
            error = None
        except Exception as exc:
            result, error = None, str(exc)
        message = error or {
            'installed': _('Nouvelle version prête. Relancez Manette pour l’utiliser.'),
            'updated': _('Nouvelle version prête. Relancez Manette pour l’utiliser.'),
            'unmanaged': _('Relancez Manette depuis le menu des applications pour activer les mises à jour.')
        }.get(result, _('Manette est à jour.'))
        GLib.idle_add(self.window.record_operation,
                     _('Installation de Manette') if operation == 'install' else _('Recherche de mise à jour de Manette'),
                     error is None, message)
        GLib.idle_add(self._finished, result, error)

    def _finished(self, result, error):
        if self.closed:
            return
        self.button.set_sensitive(result != 'installed')
        if error:
            self.status.set_subtitle(_('Mise à jour impossible : {value0}', value0=error))
        elif result in ('installed', 'updated'):
            self.status.set_subtitle(_('Nouvelle version prête. Relancez Manette pour l’utiliser.'))
        elif result == 'unmanaged':
            self.status.set_subtitle(_('Relancez Manette depuis le menu des applications pour activer les mises à jour.'))
        else:
            self.status.set_subtitle(_('Manette est à jour.'))


def automatic_check(window):
    try:
        enabled = updater.managed() and preferences.load().get('automatic_updates', True)
    except (OSError, ValueError):
        return False
    if not enabled:
        return False
    def work():
        try:
            if updater.check() == 'updated':
                GLib.idle_add(window.record_operation, _('Mise à jour de Manette'), True,
                             _('Nouvelle version prête. Relancez Manette pour l’utiliser.'))
                GLib.idle_add(window.toast, _('Une mise à jour de Manette est prête pour le prochain lancement.'))
        except Exception as error:
            GLib.idle_add(window.record_operation, _('Recherche de mise à jour de Manette'), False, str(error))
            # Une connexion absente ne doit pas perturber l'utilisation de l'application.
            pass
    threading.Thread(target=work, daemon=True).start()
    return False


def periodic_check(window):
    automatic_check(window)
    return True
