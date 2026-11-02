# Manette

Une app GNOME (GTK 4 + libadwaita) pour ne plus taper les commandes courantes.

- **Applications** : repère toutes les apps installées et *comment* elles l'ont été
  (dépôt APT, `.deb` installé à la main, Flatpak, Snap, AppImage, lanceur local),
  avec leur taille, les mises à jour disponibles et les boutons Lancer / Mettre à jour / Désinstaller.
  Pour un `.deb` installé à la main, Manette va chercher la dernière version sur GitHub
  (champ Homepage du paquet, ou table `KNOWN_GITHUB` dans `manette/scanner.py`).
- **Système** : état de la machine, occupation des disques, mises à jour globales,
  nettoyage (cache APT, anciennes révisions Snap, journaux…) et diagnostic.
- **Mes commandes** : tes propres boutons, rangés dans `~/.config/manette/commandes.json`.

Chaque commande s'exécute dans la console à droite (Ctrl+J), avec sa sortie en direct.
Les commandes qui demandent les droits administrateur passent par `pkexec`, donc par la
fenêtre de mot de passe habituelle de GNOME.

## Lancer

```bash
./bin/manette
```

## Ajouter au menu des applications

```bash
./install.sh
```

Aucune dépendance à installer sur Ubuntu : Python 3, PyGObject, GTK 4 et libadwaita y sont déjà.
