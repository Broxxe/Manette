# Manette

[English](README.md) · Français

Une application de bureau GTK 4 + libadwaita pour gérer les applications et les tâches système courantes sur Ubuntu et les distributions Linux utilisant APT.

## Fonctionnalités

- **Applications :** lancer, mettre à jour et retirer les applications détectées : APT, Flatpak, Snap, AppImage et applications locales. Installer des fichiers `.deb` et Flatpak téléchargés ou lancer des AppImages.
- **Interface adaptable :** cartes compactes ou liste, favoris, français/anglais et opacité du fond réglable.
- **Recherche globale :** retrouver applications, commandes, réglages et dossiers associés avec **Ctrl+K**.
- **Stockage :** occupation graphique des dossiers, données associées aux applications, estimation avant installation et bilan des données conservées après retrait.
- **Maintenance :** mises à jour du système, nettoyage, diagnostic des erreurs de mise à jour et suivi des ressources en direct.
- **Commandes personnelles :** enregistrer des commandes sous forme de boutons, avec ouverture possible dans un terminal.
- **Historique :** consulter les 500 dernières opérations, filtrer les échecs et copier les rapports avec **Ctrl+H**. Afficher la console avec **Ctrl+J**.

## Lancer

Nécessite Python 3, PyGObject, GTK 4 et une version récente de libadwaita. `python3-apt` permet les estimations d’espace APT ; Flatpak et Snap nécessitent leurs outils respectifs.

```sh
./bin/manette
```

Pour installer dans le compte utilisateur et ajouter une entrée au menu des applications :

```sh
./install.sh
```

L’installation ne demande aucun droit administrateur et crée une copie isolée, en conservant le dépôt de travail et les préférences.

## Mises à jour et protections

Les installations gérées peuvent télécharger automatiquement les mises à jour de Manette depuis la branche par défaut du dépôt GitHub **Broxxe/Manette**. Elles s’appliquent au prochain lancement ; la recherche automatique peut être désactivée dans les réglages.

Les modifications système utilisent la demande d’autorisation administrateur habituelle lorsque nécessaire. Les nettoyages et retraits demandent confirmation ; les désinstallations APT présentent une simulation. Les données des applications sont conservées sauf retrait demandé séparément. Les dossiers protégés ou identifiés comme partagés sont bloqués, mais leur détection peut être incomplète.

Les estimations d’espace utilisent les métadonnées APT locales. Les tailles Snap, Flatpak et non résolues sont signalées comme inconnues. Le diagnostic propose des pistes sans réparation automatique. Les commandes personnelles restent du code exécutable ; la validation d’un fichier téléchargé ne garantit pas sa fiabilité.

## Développement

```sh
python3 -m unittest discover -s tests -v
```

Les tests simulent les gestionnaires de paquets et les opérations privilégiées sans modifier les applications installées.
