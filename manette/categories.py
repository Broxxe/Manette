"""Purpose-based categories from desktop metadata, with optional personal choices."""

from . import app_data, preferences
from .i18n import _

CATEGORIES = {
    'system': _('Système'),
    'games': _('Jeux'),
    'work': _('Travail et bureautique'),
    'creation': _('Création et graphisme'),
    'development': _('Développement'),
    'internet': _('Internet et communication'),
    'multimedia': _('Audio et vidéo'),
    'education': _('Sciences et éducation'),
    'utilities': _('Utilitaires'),
    'other': _('Autres'),
}

# Freedesktop categories are case-sensitive. A launcher may declare several.
TAGS = {
    'system': {'System', 'Settings', 'DesktopSettings', 'HardwareSettings', 'PackageManager',
               'SystemSetup', 'Monitor', 'Security', 'NetworkSettings'},
    'games': {'Game', 'ActionGame', 'AdventureGame', 'ArcadeGame', 'BoardGame', 'BlocksGame',
              'CardGame', 'KidsGame', 'LogicGame', 'RolePlaying', 'Shooter', 'Simulation',
              'SportsGame', 'StrategyGame', 'Emulator'},
    'work': {'Office', 'Calendar', 'ContactManagement', 'Database', 'Dictionary', 'Chart',
             'Finance', 'FlowChart', 'PDA', 'ProjectManagement', 'Presentation', 'Spreadsheet',
             'WordProcessor', 'TextEditor'},
    'creation': {'Graphics', '2DGraphics', '3DGraphics', 'RasterGraphics', 'VectorGraphics',
                 'Photography', 'Publishing', 'Scanning', 'OCR', 'AudioVideoEditing',
                 'AudioEditing', 'VideoEditing', 'Midi', 'Sequencer', 'GUIDesigner', 'CAD'},
    'development': {'Development', 'Building', 'Debugger', 'IDE', 'Profiling', 'RevisionControl',
                    'Translation', 'WebDevelopment'},
    'internet': {'Network', 'WebBrowser', 'Email', 'Chat', 'InstantMessaging', 'IRCClient',
                 'VideoConference', 'FileTransfer', 'RemoteAccess', 'Telephony', 'Feed'},
    'multimedia': {'AudioVideo', 'Audio', 'Video', 'Player', 'Recorder', 'TV', 'DiscBurning',
                   'Music', 'AudioVideoEditing', 'AudioEditing', 'VideoEditing'},
    'education': {'Education', 'Science', 'Math', 'Astronomy', 'Biology', 'Chemistry',
                  'ComputerScience', 'DataVisualization', 'Economy', 'Electricity', 'Geography',
                  'Geology', 'Geoscience', 'History', 'Languages', 'Literature', 'Maps',
                  'NumericalAnalysis', 'Physics', 'Robotics', 'Spirituality', 'Sports',
                  'HealthFitness', 'MedicalSoftware', 'Engineering'},
    'utilities': {'Utility', 'Accessibility', 'Archiving', 'Calculator', 'Clock', 'Compression',
                  'FileManager', 'FileTools', 'TerminalEmulator', 'TextTools'},
}


def detect(info):
    if info is None:
        return ('other',)
    raw = info.get_categories()
    if not isinstance(raw, str):
        return ('other',)
    declared = {item.strip() for item in raw.split(';') if item.strip()}
    found = [key for key, tags in TAGS.items() if tags & declared]
    if len(found) > 1 and 'utilities' in found:
        found.remove('utilities')
    return tuple(found) or ('other',)


def overrides_from(settings):
    raw = settings.get('application_categories', {})
    return {key: value for key, value in raw.items() if isinstance(key, str)
            and isinstance(value, str) and value in CATEGORIES} if isinstance(raw, dict) else {}


def collapsed_from(settings):
    raw = settings.get('collapsed_categories', [])
    return {key for key in raw if isinstance(key, str) and key in CATEGORIES} if isinstance(raw, list) else set()


def for_app(app, overrides):
    choice = overrides.get(app_data.app_key(app))
    return (choice,) if choice in CATEGORIES else app.category_ids


def labels(ids):
    return ' · '.join(CATEGORIES[key] for key in ids)


PRIMARY_ORDER = ('system', 'games', 'development', 'creation', 'work', 'internet',
                 'multimedia', 'education', 'utilities', 'other')

ICONS = {
    'system': 'computer-symbolic', 'games': 'applications-games-symbolic',
    'work': 'x-office-document-symbolic', 'creation': 'applications-graphics-symbolic',
    'development': 'applications-engineering-symbolic', 'internet': 'network-workgroup-symbolic',
    'multimedia': 'multimedia-player-symbolic', 'education': 'applications-science-symbolic',
    'utilities': 'applications-utilities-symbolic', 'other': 'application-x-executable-symbolic',
}


def grouped(apps, get_categories, selected='all'):
    """One visible home per app; a category filter also includes secondary matches."""
    groups = {key: [] for key in CATEGORIES}
    for app in apps:
        ids = get_categories(app)
        if selected != 'all':
            if selected not in ids:
                continue
            key = selected
        else:
            key = next((key for key in PRIMARY_ORDER if key in ids), 'other')
        groups[key].append(app)
    return [(key, members) for key, members in groups.items() if members]


def save_choice(app, choice):
    if choice != 'auto' and choice not in CATEGORIES:
        raise ValueError(_('Catégorie inconnue.'))
    choices = overrides_from(preferences.load())
    key = app_data.app_key(app)
    if choice == 'auto':
        choices.pop(key, None)
    else:
        choices[key] = choice
    preferences.save(application_categories=choices)
    return choices
