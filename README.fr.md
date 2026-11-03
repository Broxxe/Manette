# Manette — gestionnaire d’applications et du système Linux

[English](README.md) · Français

Un gestionnaire graphique d’applications et un outil de maintenance pour Ubuntu : gérer les applications APT, Flatpak, Snap et AppImage, rechercher les mises à jour du système, analyser l’espace disque et surveiller le processeur et la carte graphique.

Un projet indépendant sous GPLv3, développé avec Python, GTK 4 et libadwaita. La section [Compatibilité](#compatibilité) précise les dépendances et l’environnement testé.

## Fonctionnalités

- **Applications :** lancer, mettre à jour et retirer les applications détectées : APT, Flatpak, Snap, AppImage et applications locales. Installer des fichiers `.deb` et Flatpak téléchargés ou lancer des AppImages.
- **Catégories :** classement automatique par usage (système, jeux, travail, création, développement…), avec sections repliables et compteurs dans les vues grille et liste. Un clic sur le titre replie ou déplie la catégorie ; ce choix est mémorisé et partagé entre les vues. Recherche, filtres, favoris et tri fonctionnent dans ces sections. Chaque application apparaît une seule fois ; le filtre retrouve aussi ses catégories secondaires. Les informations manquantes donnent « Autres ». Le menu **⋯ → Modifier la catégorie…** permet un choix personnel.
- **Interface adaptable :** cartes compactes ou liste, favoris, français/anglais et opacité du fond réglable.
- **Recherche globale :** retrouver applications, commandes, réglages et dossiers associés avec **Ctrl+K**.
- **Stockage :** occupation graphique des dossiers, données associées aux applications, estimation avant installation et bilan des données conservées après retrait.
- **Maintenance :** mises à jour du système, nettoyage, diagnostic des erreurs de mise à jour et suivi des ressources en direct, avec les barres des processeurs logiques regroupées par cœur physique.
- **Commandes personnelles :** enregistrer des commandes sous forme de boutons, avec ouverture possible dans un terminal.
- **Historique :** consulter les 500 dernières opérations, filtrer les échecs et copier les rapports avec **Ctrl+H**. Afficher la console avec **Ctrl+J**.

## Compatibilité

| Environnement | État |
| --- | --- |
| Ubuntu 26.04 LTS, x86_64 | Environnement de développement actuel : 26.04.1 ; tests locaux et vérifications GTK réussis. |
| Ubuntu 22.04 / 24.04, paquets standards | Incompatible avec les dépendances actuelles de l’interface. |
| Autres distributions Linux, bureaux ou architectures | Non validés ; la maintenance des paquets cible les systèmes utilisant APT. |

Socle d’API : **Python 3.10+, GTK 4.18+, libadwaita 1.7+ et PyGObject**. Respecter ces versions ne garantit pas une configuration testée. L’environnement de référence utilise Python 3.14.4, GTK 4.22.4 et libadwaita 1.9.1.

L’interface utilise [Adw.WrapBox, disponible depuis libadwaita 1.7](https://gnome.pages.gitlab.gnome.org/libadwaita/doc/main/class.WrapBox.html), et les [variables CSS de GTK](https://docs.gtk.org/gtk4/css-properties.html). Ubuntu 24.04 fournit [libadwaita 1.5](https://packages.ubuntu.com/fr/noble/libadwaita-1-0). Sa prise en charge nécessite des adaptations du code ou un paquet embarquant un environnement adapté.

Flatpak, Snap, les outils de firmware et de carte graphique activent les fonctions correspondantes lorsqu’ils sont installés. La gestion des services nécessite systemd ; les actions administrateur nécessitent `pkexec` et un agent d’autorisation du bureau. Les mesures GPU concernent actuellement NVIDIA (`nvidia-smi`) et AMD (`sysfs`), selon les pilotes ; les mesures GPU Intel ne sont pas implémentées. La transparence du fond dépend du bureau.

## Lancer

Sur l’environnement Ubuntu de référence, installer les dépendances si nécessaire :

```sh
sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-apt pkexec curl
```

`python3-apt` permet les estimations d’espace APT. Cette commande ne rend pas les anciennes versions d’Ubuntu compatibles.

Lancer depuis le dépôt :

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

## Licence

Copyright © 2026 Broxxe. Manette est distribué sous **GNU General Public License version 3 uniquement** (`GPL-3.0-only`) ; voir [LICENSE](LICENSE). L’utilisation, la modification et la redistribution, y compris commerciales, sont autorisées. Les versions modifiées redistribuées doivent fournir le code source correspondant sous GPLv3 et conserver les mentions requises. Aucune garantie n’est fournie.
