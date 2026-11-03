# Manette

[English](README.en.md) · Français

Une app GNOME (GTK 4 + libadwaita) pour ne plus taper les commandes courantes.

- **Applications** : repère toutes les apps installées et *comment* elles l'ont été
  (dépôt APT, `.deb` installé à la main, Flatpak, Snap, AppImage, lanceur local),
  avec leur taille, les mises à jour disponibles et les boutons Lancer / Mettre à jour / Désinstaller.
  L'affichage peut être une **mosaïque de grandes cartes** ou une **liste**. Chaque carte
  propose un grand bouton de lancement et un menu **⋯** en bas à droite pour les dossiers,
  les mises à jour et le retrait. La recherche, les filtres et le tri fonctionnent dans les
  deux vues ; le choix d'affichage est mémorisé.
  Pour un `.deb` installé à la main, Manette va chercher la dernière version sur GitHub
  (champ Homepage du paquet, ou table `KNOWN_GITHUB` dans `manette/scanner.py`).
  Le bouton **Ouvrir un fichier…** permet d'installer un `.deb`, un `.flatpakref` ou un
  `.flatpak`, ou de lancer une `.AppImage` téléchargée. Une confirmation présente le fichier
  et l'action. Les AppImages restent à leur emplacement ; les Flatpaks sont installés pour votre compte.
  Chaque application possède aussi un bouton **Données et dossiers associés** (icône de dossier) :
  il distingue la taille du programme de celle des données et permet d'ouvrir les dossiers.
  La détection utilise les identifiants Flatpak/Snap, les dossiers XDG de l'utilisateur courant
  et quelques emplacements connus, dont `~/.lmstudio`. Vous pouvez associer manuellement un dossier
  à n'importe quelle application, sur n'importe quel PC. Les associations sont conservées dans
  `~/.config/manette/dossiers.json` (ou le dossier de configuration XDG), avec `~` pour les
  chemins du dossier personnel. Retirer une association ne supprime aucun fichier.
  La mesure compte les blocs sur disque sans doubler les sous-dossiers ou liens physiques ;
  les liens symboliques internes ne sont pas parcourus. Les dossiers absents, illisibles ou
  trop longs à mesurer sont signalés. Un même dossier peut servir à plusieurs applications :
  les totaux par application ne doivent donc pas être additionnés comme un total global.
- **Système** : état de la machine, occupation des disques, mises à jour globales,
  nettoyage (cache APT, anciennes révisions Snap, journaux…) et diagnostic.
  **Occupation du dossier personnel** ouvre un résumé graphique du dossier personnel :
  total mesuré, plus gros dossier, classement avec barres de proportion et bouton **Ouvrir**
  pour chaque dossier. L'analyse inclut les dossiers cachés, fonctionne en arrière-plan et
  indique les résultats partiels. Elle reste sur le même système de fichiers et ne suit pas
  les liens symboliques. Un bouton permet de recalculer les tailles après avoir fait du ménage.
- **Mes commandes** : vos boutons personnels, rangés dans `~/.config/manette/commandes.json`.

Chaque commande s'exécute dans la console à droite (Ctrl+J), avec sa sortie en direct.
Les commandes qui demandent les droits administrateur passent par `pkexec`, donc par la
fenêtre de mot de passe habituelle de GNOME.

Avant une mise à jour ou une installation, Manette vérifie l'espace libre sur les partitions
concernées et avertit sous **5 Gio**. C'est un seuil de précaution, pas une estimation de
l'espace requis. Vous pouvez annuler pour faire du ménage ou continuer après l'avertissement.
Les fichiers AppImage se lancent séparément pour laisser la console disponible.

Les nettoyages demandent confirmation et expliquent leurs effets. Les désinstallations APT
et le nettoyage des paquets inutilisés présentent la liste simulée des suppressions ; si la
simulation échoue, l'action est bloquée. Les nouvelles commandes personnelles demandent
confirmation par défaut. Cette confirmation est obligatoire lorsque l'option « Droits
administrateur » est activée, y compris pour les commandes enregistrées auparavant.
Une commande personnelle reste du code libre : Manette n'analyse pas sa dangerosité.
La validation d'un fichier téléchargé ne certifie pas sa provenance ou sa fiabilité.

Le retrait des applications utilise leur mode d'installation : APT, Flatpak, Snap,
AppImage ou application locale. Les copies personnelles des lanceurs sont reliées au paquet
système lorsqu'un lanceur de même identifiant et de même exécutable est fourni par ce paquet.
Pour les applications locales, Manette reconnaît certains dossiers portables (AppImage extraite,
PyInstaller). Dans les autres cas, vous pouvez choisir le dossier d'installation : il doit contenir
un programme indiqué par le lanceur, vous appartenir et ne pas être un dossier général ou partagé
avec une autre application détectée. Une confirmation affiche les chemins exacts avant la mise
à la corbeille. Les données en dehors du dossier choisi sont conservées. Retirer seulement un
raccourci reste possible et est présenté comme tel ; cela ne désinstalle pas le programme.
Manette ne devine pas une procédure destructive pour les installations qu'elle ne sait pas gérer.

## Lancer

```bash
./bin/manette
```

## Ajouter au menu des applications

```bash
./install.sh
```

L'installation se fait dans le compte utilisateur, sans droits administrateur. Elle conserve
une copie isolée de la version courante et active les mises à jour automatiques. Le dépôt de
travail et les commandes personnelles ne sont pas modifiés.

## Langue et mises à jour de Manette

Le menu **Préférences et mises à jour** permet de choisir **Français**, **English** ou la langue
du système. Relancer Manette applique la nouvelle langue. Les noms et commandes saisis par
l'utilisateur sont conservés tels quels ; les sorties des outils système restent celles des outils.
Le bouton de réglages dans l'en-tête donne aussi accès au choix mosaïque/liste et au **fond
translucide**. Ce dernier conserve les textes et boutons opaques, respecte le thème clair/sombre
et se désactive en contraste élevé. Son rendu dépend du bureau utilisé.

Pour une ancienne installation lancée directement depuis le dépôt, sélectionner **Activer les
mises à jour**, puis relancer Manette depuis le menu des applications. Il est également possible
de relancer `./install.sh`.

Les nouvelles versions publiées sur la branche par défaut du dépôt **Broxxe/Manette** sont
recherchées au démarrage puis chaque jour tant que Manette est ouverte, au maximum une fois par
24 heures. Elles sont téléchargées en arrière-plan, vérifiées puis préparées dans
`$XDG_DATA_HOME/manette/versions` (par défaut `~/.local/share/manette/versions`). Elles prennent
effet au prochain lancement ; aucune commande en cours n'est interrompue. La mise à jour ne
nécessite ni Git sur l'installation gérée, ni droits administrateur. Une erreur réseau ou une archive
invalide conserve la version active. Une version distante plus ancienne ou divergente est refusée.

La version précédente est conservée derrière le lien `previous`. En cas de besoin, elle peut
être lancée avec `~/.local/share/manette/previous/bin/manette` (adapter le chemin si XDG_DATA_HOME
est personnalisé). Les mises à jour automatiques peuvent être désactivées dans les préférences ;
**Rechercher maintenant** reste disponible. Ce mécanisme installe le code publié dans le dépôt :
les changements locaux non publiés ne sont pas distribués aux autres installations.

Aucune dépendance à installer sur Ubuntu : Python 3, PyGObject, GTK 4 et libadwaita y sont déjà.

## Vérifications

```bash
python3 -m unittest discover -s tests -v
```

Les tests simulent les gestionnaires de paquets et la fermeture des applications : ils ne modifient pas le système.
