"""Recognize common package-manager failures without modifying the system."""

from dataclasses import dataclass
from .i18n import _


@dataclass(frozen=True)
class Finding:
    title: str
    explanation: str
    action: str = ''


def analyze(output):
    text = output.casefold()
    findings = []
    rules = [
        (('no space left', 'pas assez d’espace', "pas assez d'espace", 'aucun espace disponible', 'not enough free space', 'not enough disk space', 'espace libre insuffisant'),
         _('Espace disque insuffisant'),
         _('Le téléchargement ou l’installation manque de place. Libérez de l’espace, puis relancez l’opération.'), 'storage'),
        (('timed out', 'timeout', 'délai de connexion dépassé', 'connection failed', 'connexion échouée'),
         _('Téléchargement interrompu'),
         _('Un serveur ne répond pas dans le délai prévu. Vérifiez la connexion, puis réessayez. Les archives déjà téléchargées peuvent être réutilisées.'), 'updates'),
        (('temporary failure resolving', 'could not resolve', 'impossible de résoudre', 'résolution temporaire'),
         _('Résolution réseau impossible'),
         _('Le nom du serveur ne peut pas être résolu. Vérifiez la connexion Internet et les paramètres DNS avant de réessayer.'), 'updates'),
        (('could not get lock', 'unable to acquire', 'impossible de verrouiller', 'impossible d’obtenir le verrou', "impossible d'obtenir le verrou"),
         _('Gestionnaire de paquets occupé'),
         _('Une autre opération utilise les paquets. Attendez sa fin et fermez les autres gestionnaires de logiciels. Ne supprimez pas les fichiers de verrouillage.'), ''),
        (('dpkg was interrupted', 'dpkg a été interrompu'),
         _('Configuration de paquets interrompue'),
         _('La configuration doit être terminée avant une nouvelle installation. La commande « sudo dpkg --configure -a » est à examiner dans un terminal ; elle peut modifier le système.'), ''),
        (('unmet dependencies', 'dépendances non satisfaites', 'held broken packages', 'fix-broken'),
         _('Dépendances à examiner'),
         _('Des paquets sont incomplets ou incompatibles. Examinez la proposition de « sudo apt-get --fix-broken install » dans un terminal avant de l’accepter : elle peut installer ou supprimer des paquets.'), ''),
        (('no_pubkey', 'not signed', "n'est pas signé", 'ne sont pas valables', 'signatures couldn’t be verified', "signatures couldn't be verified", 'does not have a release file', 'ne contient pas de fichier release', '404  not found', '404 not found'),
         _('Dépôt à vérifier'),
         _('Un dépôt est introuvable ou sa signature ne peut pas être vérifiée. Vérifiez son adresse et sa compatibilité avec le système. Ne désactivez pas la vérification des signatures.'), ''),
        (('certificate verification failed', 'certificate verify failed', 'certificat', 'tls handshake'),
         _('Connexion sécurisée impossible'),
         _('Vérifiez la date du système, la connexion et le dépôt concerné. Ne désactivez pas la vérification des certificats.'), ''),
        (('permission denied', 'permission non accordée', 'not authorized', 'not authorised', 'authentication failed', 'mot de passe refusé'),
         _('Autorisation refusée'),
         _('L’opération n’a pas reçu les droits nécessaires. Relancez-la et validez la demande du système si vous souhaitez continuer.'), ''),
    ]
    for patterns, title, explanation, action in rules:
        if any(pattern in text for pattern in patterns):
            findings.append(Finding(title, explanation, action))
    if not findings:
        findings.append(Finding(_('Cause non identifiée'),
            _('Le journal ne permet pas de déterminer une cause précise. Consultez les dernières erreurs et copiez le rapport pour obtenir de l’aide.')))
    return findings
