# Manette

Une app GNOME (GTK 4 + libadwaita) pour ne plus taper les commandes courantes.

- **Applications** : repère toutes les apps installées et *comment* elles l'ont été
  (dépôt APT, `.deb` installé à la main, Flatpak, Snap, AppImage, lanceur local),
  avec leur taille, les mises à jour disponibles et les boutons Lancer / Mettre à jour / Désinstaller.
  Pour un `.deb` installé à la main, Manette va chercher la dernière version sur GitHub
  (champ Homepage du paquet, ou table `KNOWN_GITHUB` dans `manette/scanner.py`).
  Le bouton **Ouvrir un fichier…** permet d'installer un `.deb`, un `.flatpakref` ou un
  `.flatpak`, ou de lancer une `.AppImage` téléchargée. Une confirmation présente le fichier
  et l'action. Les AppImages restent à leur emplacement ; les Flatpaks sont installés pour ton compte.
  Chaque application possède aussi un bouton **Données et dossiers associés** (icône de dossier) :
  il distingue la taille du programme de celle des données et permet d'ouvrir les dossiers.
  La détection utilise les identifiants Flatpak/Snap, les dossiers XDG de l'utilisateur courant
  et quelques emplacements connus, dont `~/.lmstudio`. Tu peux associer manuellement un dossier
  à n'importe quelle application, sur n'importe quel PC. Les associations sont conservées dans
  `~/.config/manette/dossiers.json` (ou le dossier de configuration XDG), avec `~` pour les
  chemins du dossier personnel. Retirer une association ne supprime aucun fichier.
  La mesure compte les blocs sur disque sans doubler les sous-dossiers ou liens physiques ;
  les liens symboliques internes ne sont pas parcourus. Les dossiers absents, illisibles ou
  trop longs à mesurer sont signalés. Un même dossier peut servir à plusieurs applications :
  les totaux par application ne doivent donc pas être additionnés comme un total global.
- **Système** : état de la machine, occupation des disques, mises à jour globales,
  nettoyage (cache APT, anciennes révisions Snap, journaux…) et diagnostic.
  **Ce qui prend de la place chez toi** ouvre un résumé graphique du dossier personnel :
  total mesuré, plus gros dossier, classement avec barres de proportion et bouton **Ouvrir**
  pour chaque dossier. L'analyse inclut les dossiers cachés, fonctionne en arrière-plan et
  indique les résultats partiels. Elle reste sur le même système de fichiers et ne suit pas
  les liens symboliques. Un bouton permet de recalculer les tailles après avoir fait du ménage.
- **Mes commandes** : tes propres boutons, rangés dans `~/.config/manette/commandes.json`.

Chaque commande s'exécute dans la console à droite (Ctrl+J), avec sa sortie en direct.
Les commandes qui demandent les droits administrateur passent par `pkexec`, donc par la
fenêtre de mot de passe habituelle de GNOME.

Avant une mise à jour ou une installation, Manette vérifie l'espace libre sur les partitions
concernées et avertit sous **5 Gio**. C'est un seuil de précaution, pas une estimation de
l'espace requis. Tu peux annuler pour faire du ménage ou continuer après l'avertissement.
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
PyInstaller). Dans les autres cas, tu peux choisir le dossier d'installation : il doit contenir
un programme indiqué par le lanceur, t'appartenir et ne pas être un dossier général ou partagé
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

Aucune dépendance à installer sur Ubuntu : Python 3, PyGObject, GTK 4 et libadwaita y sont déjà.

## Vérifications

```bash
python3 -m unittest discover -s tests -v
```

Les tests simulent les gestionnaires de paquets et la fermeture des applications : ils ne modifient pas le système.
