# Maintenir et tester sa propre version

Cette version dérivée garde la licence MIT et les notices des composants d'origine. Les fichiers du jeu, les clés,
le C généré à partir du jeu, les shaders traduits, les captures et les sauvegardes restent sur votre PC.
Le guide décrit une procédure ; il ne constitue pas une validation du jeu ou d'une amélioration de performances.

## Branches et versions

- `origin` est votre dépôt `ezfn1804-cell/mkw-recomp` ; `upstream` désigne `adriadam10/mkw-recomp`.
- Commencer sur `custom/microfreeze-baseline`. Les prochaines branches de travail suivent `custom/<sujet>`.
- Chaque modification reste petite, avec sa vérification et son commit Conventional Commits en anglais.
- Revoir les mises à jour d'`upstream` dans une branche séparée avant de les intégrer. Ne pas écraser votre base.
- Nommer les candidats `0.1.8-custom.1`, `0.1.8-custom.2`, etc. Le numéro du port est distinct de la version du jeu.
- Ne pousser aucun tag de publication et ne créer aucune release sans autorisation du propriétaire.

La CI dans `.github/workflows/ci.yml` contrôle aussi les branches `custom/**`. Le workflow
`.github/workflows/custom-windows.yml` prépare un ZIP Windows avec les outils de préparation, le diagnostic et un
SHA-256. Il utilise un tag uniquement dans le runner pour identifier l'exécutable ; il ne pousse aucun tag, n'a pas
de permission d'écriture et ne crée aucune GitHub Release. Une compilation réussie ne valide pas le jeu sous Windows.
Le ZIP est un artefact de test conservé sept jours, à extraire dans un nouveau dossier.

Le workflow se déclenche à l'envoi d'une branche `custom/**` (version de test par défaut `0.1.8-custom.2`)
et reste lançable manuellement. Obtenir l'autorisation du propriétaire avant l'envoi : le code et l'artefact auront
la visibilité du dépôt. Une fois l'envoi autorisé, ouvrir Actions → Custom Windows test package → le run correspondant
au commit, puis télécharger son artefact après réussite. Ce premier envoi ne dépend pas de l'enregistrement du workflow
manuel sur la branche par défaut. Pour un lancement manuel ultérieur, une fois le workflow disponible sur la branche
par défaut : Run workflow → sélectionner la branche et le numéro du candidat.
L'empaquetage `0.1.8-custom.1` et la CI ont réussi sur GitHub Actions. Chaque candidat suivant doit réussir ses propres
vérifications. Le ZIP est également contrôlé avec les règles de l'outil de mise à jour avant son envoi en artefact.

## Mises à jour de la version personnalisée

Le lanceur personnalisé utilise les publications de `ezfn1804-cell/mkw-recomp`. Il compare aussi les numéros
`custom.N` : `custom.10` vient après `custom.2`. Une version personnalisée peut recevoir une préversion personnalisée
publiée ; les brouillons et les artefacts Actions ne déclenchent aucune proposition de mise à jour.
Le téléchargement vise exactement la version proposée, vérifie son SHA-256 fourni par GitHub, puis prépare les fichiers
avant le remplacement par le lanceur existant. Sous Windows, le ZIP ne peut contenir que le programme, ses DLL, ses
outils et ses notices ; les données du jeu, les réglages, les sauvegardes et les caches restent dans le dossier.
Le remplacement reprend le mécanisme existant de restauration des fichiers si une étape échoue.

La préparation compare les entrées de chaque étape :

| Changement | Travail relancé |
|---|---|
| Programme seul, ABI et outils inchangés | Préchauffage ; le jeu compilé et les shaders sont réutilisés |
| Traducteur de shaders ou ses outils | Traduction des shaders et préchauffage |
| Générateur CPU, correctifs CPU, ABI ou compilateur | Génération si nécessaire, compilation du jeu et préchauffage |
| Aucun changement | Étapes déjà terminées sautées |
| Compilation interrompue | Reprise des fichiers valides ; objets écartés si leurs entrées ont changé |

Un ancien `setup-state.json` ne mémorisait pas les versions du générateur et de ses modules. Le premier passage à
cette préparation reconstruit donc une fois les fichiers dérivés qui ne peuvent pas être vérifiés. Les fichiers du
jeu déjà copiés restent en place, ainsi que les sauvegardes : cette migration n'est pas une réinstallation. Les mises
à jour suivantes suivent les empreintes ci-dessus. Le contrôle du RomFS reste un contrôle de structure et de nombre
de fichiers, sans vérification complète de son contenu ; seul le dump 1.0.0 non modifié est pris en charge.
Si le dump d'origine a disparu après une préparation en mode copie, la copie installée peut servir à la reprise.

Le port officiel 0.1.6 recherche les publications du dépôt d'origine. Pour passer au canal personnalisé, une première
opération manuelle reste nécessaire : fermer le jeu, extraire le ZIP personnalisé **dans la copie de test existante**
et accepter le remplacement des fichiers du programme, puis cliquer sur **Préparer**. Ne supprimer ni `setup-state.json`,
ni `mkwgame.dll`, ni `exefs/`, ni `romfs/`, ni le profil. Le ZIP ne fournit pas ces fichiers.

Pour préparer une future mise à jour automatique, vérifier le candidat sur Windows, attribuer le prochain numéro,
décrire les changements et les tests dans `CHANGELOG.md`, puis créer une release contenant le ZIP Windows directement
(pas le ZIP extérieur de l'artefact Actions). GitHub doit fournir son `digest` SHA-256. Une release personnalisée peut
être marquée « préversion ». **Ne publier cette release qu'après autorisation du propriétaire.** Le workflow de test
ne la publie pas ; en l'absence de release publiée, aucun bouton de nouvelle version n'apparaît.

Les tests automatisés de sélection, téléchargement et reprise utilisent des réponses GitHub et des modules synthétiques.
Ils ne prouvent pas le remplacement réel d'un programme en cours d'exécution sur votre PC ni le bon fonctionnement
du jeu. Les mesures suivantes restent isolées et désactivent la recherche de mises à jour pendant les essais.

## Première étape sur Windows : une copie indépendante

Pour commencer le plus vite avec un port qui fonctionne déjà : extraire le kit de diagnostic dans une copie du
dossier du port, puis double-cliquer sur `collect-diagnostic.cmd`. Il lit le dernier `logs/mkw.log` et produit
`diagnostics/rapport-.../fluidite.txt` et `compatibilite.txt`. Envoyer ces deux petits fichiers dans la conversation
en cours. Le collecteur ne lance ni le jeu, ni l'installation, ni une mise à jour et ne recopie aucun fichier du jeu.
Si le journal est trop ancien ou ne contient pas de timings, utiliser la mesure détaillée ci-dessous.
Le diagnostic Python est testé sur Linux ; le collecteur `.cmd` est également couvert par un test réservé à la CI Windows.

1. Fermer le jeu. **Copier**, sans déplacer ni écraser, le dossier du port fonctionnel dans un nouveau dossier,
   par exemple `D:\MKW-Test`. Si la copie contient le jeu entier, prévoir environ 30 Go libres supplémentaires.
2. Vérifier dans cette copie la présence de `mkw.exe`, `mkwgame.dll`, des bibliothèques et de `setup/`.
   Les dossiers de jeu attendus sont `exefs/` (`main`, `sdk`, `subsdk0`) et `romfs/`.
   Si les fichiers du jeu sont ailleurs, utiliser leur chemin réel dans la commande, uniquement en lecture.
3. Enregistrer `tools/run/diagnose.py` sous le nom `diagnose.py` dans ce dossier de test. Le ZIP personnalisé le fournit
   déjà. Ce script n'a besoin que du Python fourni avec le port, aucune installation système.
4. Dans l'explorateur, ouvrir ce dossier de test, cliquer dans la barre d'adresse, taper `cmd`, puis Entrée.
   Vérifier la version, en remplaçant `.` si le dump se trouve dans un autre dossier :

```bat
setup\python\python.exe diagnose.py --check-game .
```

Ce contrôle lit seulement les 72 premiers octets de `exefs/main` et vérifie la présence des dossiers/modules.
Il ne vérifie pas l'intégralité des 23 Go de ressources. Un succès signifie « structure et identifiant 1.0.0 reconnus ».
En cas de version différente, arrêter les essais de compatibilité : ne pas appliquer le ZIP de mise à jour au hasard.

## Recueillir une première mesure

Toujours dans la fenêtre `cmd` ouverte **dans la copie de test**, exécuter :

```bat
set "MKW_UPDATE_CHECK=0"
set "MKW_TRACE=perf"
set "MKW_HOST_TIME=1"
set "MKW_TRACE_TL=1"
mkdir test-cache
set "MKW_PIPELINE_CACHE=%CD%\test-cache\pipeline-cache.bin"
mkw.exe --play --exefs ".\exefs" --romfs ".\romfs" --profile ".\test-profile" > test-A.log 2>&1
setup\python\python.exe diagnose.py test-A.log --out diagnostic-A.txt
```

Adapter `--exefs` et `--romfs` si ces dossiers ne sont pas présents dans la copie. Les variables `set` sont locales
à cette fenêtre et disparaissent à sa fermeture. Le profil séparé crée ses propres sauvegardes ; votre progression
habituelle n'est pas utilisée. Le lancement direct avec `--play` évite une préparation ou une mise à jour automatique.

Choisir une course reproductible, noter son nom, le mode et les réglages. Mesurer son début puis au moins un tour et
quitter normalement pour enregistrer le résumé final. Refaire le même parcours dans la copie en remplaçant `test-A.log`
par `test-B.log` et `diagnostic-A.txt` par `diagnostic-B.txt`. Garder les caches de la copie et noter si les saccades
arrivent seulement au premier passage. Ne pas vider les caches de votre installation habituelle.

Pour la cible 1440p, tester dans la copie à une résolution interne de 1440 et une sortie 2560 × 1440, avec une cible
de 60 fps. Un essai complémentaire à 720p aide à distinguer une limite GPU d'une limite CPU. Garder les mêmes réglages
entre deux candidats ; la fréquence 165 Hz de l'écran n'implique pas que le moteur fonctionne correctement à 165 fps.

Transmettre **dans cette même conversation** uniquement `diagnostic-A.txt`, `diagnostic-B.txt`, le numéro de version
du port, la version du pilote NVIDIA, le circuit, les réglages et le moment de la saccade. Le rapport ne recopie que
des nombres de timing reconnus. Il omet les chemins, dumps mémoire, images et autres lignes brutes du journal.
Les erreurs structurées de soumission Vulkan et de pointeur d'instruction GPU sont aussi conservées, sans adresse brute.
Ne pas transmettre `test-A.log` entier, une ROM, des clés, `mkwgame.dll`, `spirv/`, une capture GPU ni `romfs/`.
Si le jeu plante avant de produire des timings, décrire l'erreur et copier quelques lignes textuelles après avoir
masqué les chemins personnels. Aucun nouveau chat n'est nécessaire.

Les mesures incluent aussi les menus et chargements. Le résumé par fenêtre de 60 images ne donne pas le p95/p99
par image. Les cinq pires images par période et les compteurs >50/>100 ms sont utiles pour trouver les pics.
Avec `MKW_TRACE=perf`, les lignes « Pic trace » recensent aussi les images dépassant le seuil du moteur (50 ms par
défaut). Une image peut figurer à la fois dans cette trace et dans le résumé des pires images : ne pas la compter deux fois.
Les temps textures, ASTC et replay peuvent se recouvrir : leur somme n'est pas un temps de frame.

## Première correction des micro-freezes : critères et ordre

1. Utiliser les images lentes pour départager compilation de pipelines, uploads de textures, enregistrement Vulkan,
   attente GPU et pression mémoire. Les diagnostics ne prouvent pas à eux seuls une causalité.
2. Si les pics viennent des uploads, commencer par le coût CPU du deswizzle et les allocations du staging :
   `runtime/gfx/vk/tex/vk_tex_upload.c`, `runtime/gfx/nvn/tex/tex_deswizzle.c` et
   `runtime/gfx/vk/device/vk_vma.cpp`. Préparer des textures synthétiques, des dimensions impaires, des mipmaps,
   des tableaux et des volumes ; vérifier les octets et les bornes avant d'optimiser le transfert.
3. Si les pics viennent des pipelines, vérifier d'abord que le préchauffage et les caches persistants sont utilisés,
   puis cibler `runtime/gfx/vk/pipe/vk_pipe_keys.c` et `vk_pipe_gpl.c`. L'autosauvegarde hors du thread de présentation
   existe déjà ; ne pas la présenter comme une nouvelle correction.
4. Si le replay domine de façon permanente plutôt que par pics, cibler les états dynamiques redondants et les caches
   de descripteurs dans `runtime/gfx/vk/exec/`. Un FPS moyen faible est distinct d'une micro-saccade isolée.
5. Introduire un changement mesurable à la fois. Ajouter un test reproduisant le défaut, conserver les réglages
   standards, puis vérifier le résultat sur le PC de test. Pour un changement commutable, employer l'A/B dans une
   seule partie et l'ordre inversé (`MKW_AB`, `MKW_AB_INVERT`, `tools/run/ab.py`), conformément à `AGENTS.md`.
6. Accepter le correctif lorsque les pics et leur durée diminuent dans la scène reproduite, sans régression de rendu,
   de vitesse du jeu ou de stabilité. Confirmer sans instrumentation et sur une autre configuration avant généralisation.

La cible de 60 fps correspond à 16,67 ms par image. Aucun gain, seuil de p99 ou maintien de 60 fps ne peut être annoncé
avant mesure en jeu. La première piste reste conditionnée par le diagnostic, pas par le nom de la carte graphique.

## Vérifications à chaque changement

```sh
uv run --frozen pytest tests -q
uv run --frozen ruff check tools sm86
uv run --frozen tools/docs/check.py
uv run --frozen tools/git/cfg_rows.py
uv run --frozen tools/build/build.py --dist --runtime-only --jobs 4
```

La CI complète construit également le runtime Windows et exécute les tests Python sur Windows. Vérifier les résultats
du run, y compris les tests sautés. Les contrôles de code ne remplacent ni une partie, ni un test du pilote Vulkan.
Les sondes du runtime initialisent l'espace du jeu et ne sont pas toutes disponibles avec le seul lanceur.
Une modification de shader exige les contrôles hors GPU de `AGENTS.md` avant toute exécution GPU.
