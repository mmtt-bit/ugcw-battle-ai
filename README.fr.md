# UGCW Battle AI (français)

Mod non officiel pour **Ultimate General: Civil War** : un modèle de langage (Claude par défaut) commande
l'armée de l'ordinateur pendant que vous jouez l'autre camp. Inspiré de
[rome-battle-ai](https://github.com/Cegli865/rome-battle-ai) de Cegli865. Version bêta.

Démarrage rapide :
1. **Plugin** : sauvegardez `Assembly-CSharp.dll` (dossier `..._Data\Managed` du jeu), puis suivez
   [`plugin/INSTALL.txt`](plugin/INSTALL.txt) avec dnSpy (11 classes et une ligne dans `BattleLogic.Run()`).
2. **Serveur** : copiez `server/` (par exemple dans `C:\ugcw-ai`) et lancez `python planner_server.py`
   (Python 3.8+, aucun paquet à installer).
3. **Modèle** : choisissez `"backend"` dans `server/config.json` (`claude_code`, `ollama`, `openai_compatible`).
   `"dry_run": true` n'envoie pas les ordres ; passez-le à `false` pour laisser jouer l'IA.
4. Lancez une bataille. F6 affiche ou masque le raisonnement de l'IA.

Aucun fichier du jeu n'est dans ce dépôt. Guide complet (en anglais) : [`docs/user-guide.txt`](docs/user-guide.txt).
Licence MIT.
