"""A personal category never changes package metadata or removal permissions."""

from gi.repository import Adw, Gtk
from . import app_data, categories
from .i18n import _


class CategoryDialog(Adw.Dialog):
    def __init__(self, app, page):
        super().__init__(title=_('Catégorie de {value0}', value0=app.name), content_width=520, content_height=300)
        header = Adw.HeaderBar()
        save = Gtk.Button(label=_('Enregistrer'), css_classes=['suggested-action'])
        header.pack_end(save)
        content = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(description=_(
            'Le classement automatique utilise les catégories déclarées par l’application. Un choix personnel peut le remplacer.'))
        keys = ['auto', *categories.CATEGORIES]
        automatic = _('Automatique : {value0}', value0=categories.labels(app.category_ids))
        choice = page.category_overrides.get(app_data.app_key(app), 'auto')
        row = Adw.ComboRow(title=_('Catégorie'), selected=keys.index(choice),
            model=Gtk.StringList.new([automatic, *categories.CATEGORIES.values()]))
        group.add(row)
        content.add(group)
        view = Adw.ToolbarView(content=content)
        view.add_top_bar(header)
        self.set_child(view)
        def apply(*unused):
            if page.set_category(app, keys[row.get_selected()]):
                self.close()
        save.connect('clicked', apply)
