# Waze sur iOS 6 jailbreak — serveurs et cartes reconstruits

Les serveurs Waze d’origine sont éteints. Ce projet les remplace par un PC Linux
sur le réseau local, et **fabrique les cartes** à partir d’OpenStreetMap.

Cible principale : **Waze 2.4.0.0**, la dernière version publiée sous GPL v2.
Comme on a sa source complète, rien n’est deviné — protocole, format de carte,
tout est lu dans le code. Waze 3.9.6 reste supporté au mieux (voir plus bas).

---

## Pourquoi la 2.4.0.0

La v3 de Waze est une réécriture complète, passée en propriétaire. La dernière
version open source pour iPhone et Android est la **2.4.0.0** — confirmé par
Wikipédia et par `iphone/Xcode/Info.plist` du dépôt source
(`CFBundleVersion 2.4.0.0`).

Sa source est sur [github.com/mkoloberdin/waze](https://github.com/mkoloberdin/waze),
**branche `iphone`** (pas la branche `android` par défaut, qui est un autre port).
On y lit directement :

| Question | Fichier source | Réponse |
|---|---|---|
| Format de la réponse de login | `Realtime/RealtimeNetRec.c` | 11 champs, ordre fixe |
| Numéro de protocole | `Realtime/RealtimeNetDefs.h` | `RTNET_PROTOCOL_VERSION (150)` |
| Identifiant d’une tuile | `roadmap_tile.c` | `base + lon×lignes + lat` |
| Format d’une tuile | `roadmap_data_format.h` | `WZDF` + zlib + 28 sections |
| Format d’un paquet de région | `roadmap_gzm.c` | `WGZM` + index trié |

### Le login

```
RC,200,OK
LoginSuccessful,<id>,<cookie>,<rank>,<points>,<rating>,<prevRank>,<addon>,<pointsTs>,<moods>,<maxProto>,<version>
```

Le catcher **détecte le protocole tout seul**, il n’y a aucun réglage :

| Requête reçue | Mode |
|---------------|------|
| `Login,150,<user>,…` (protocole en tête) | réponse GPL exacte, login OK du 1er coup |
| `ClientInfo,202,…` puis `Login,<user>,…` | balayage de 16 formats candidats (3.9.6) |

---

## Les cartes

`scripts/wazemap.py` construit un paquet de carte Waze depuis OpenStreetMap.
Chacun génère sa région — il n’y a pas de carte pré-faite dans le dépôt, parce
qu’un fond de carte suisse n’aide personne ailleurs.

```bash
# Vérifie le format sans réseau (aucune donnée téléchargée)
python3 scripts/wazemap.py selftest

# Boston
python3 scripts/wazemap.py build --bbox -71.19,42.28,-70.95,42.42 --name boston

# Lac Léman
python3 scripts/wazemap.py build --bbox 6.42,46.33,6.56,46.40 --name leman

# Envoi sur l'iPhone (le dossier cible est découvert sur l'appareil)
sh maps.sh boston
```

Le résultat est un unique fichier `maps/<région>/map00000.wzm`. Waze sait aussi
le télécharger tout seul : le catcher annonce `Download.Source` et sert le
dossier `maps/`.

Comment ça marche, en bref : chaque route OSM est découpée aux frontières de
tuiles, chaque tuile devient une base RoadMap compressée (points en 16 bits
relatifs au coin sud-ouest, lignes triées par catégorie), et l’ensemble est
empaqueté dans un `.wzm` à index trié. Les points de coupe portent
`POINT_FAKE_FLAG` pour que le rendu sache que la route continue sur la tuile
voisine. Détails dans `docs/PROGRESS.md`.

Options utiles : `--max-scale N` (échelles 0..N ; les échelles grossières ne
gardent que les grands axes), `--osm fichier.json` pour repartir d’un export
Overpass déjà téléchargé, `--fips` pour changer le numéro de carte.

---

## T480 — lancement

```bash
cd /home/tordjman/Documents/Projets/waze-ios6
sh pull.sh
sh stop.sh
sudo sh go.sh          # reste ouvert
```

Autre terminal : `sh phone.sh` (patch du téléphone, déjà OK)

**iPhone :** Wi-Fi → DNS manuel → `192.168.1.191` → ouvre Waze, et **laisse tourner
3–4 minutes**. Chaque relance de login teste un format de plus.

Ce que tu dois voir défiler :

```
variante login [essai 3/16] ver+1int
  LoginSuccessful,1,...,202,3.9.6.1,0
```

et, quand c’est bon :

```
★★★ LOGIN ACCEPTÉ — variante « ... » (commande At)
```

La variante est mémorisée dans `logs/login-variant.txt` et réutilisée aux
lancements suivants. Pour recommencer le balayage : `rm logs/login-variant.txt`.
Pour forcer un format : `LOGIN_VARIANT=ver+2int sudo -E sh go.sh`.

---

## Trouver le format sans attendre : `diag.sh`

Le binaire Waze contient les messages d’erreur du parseur, dans l’ordre des champs
lus (`RTNet::OnLoginResponse() - Failed to read my rating`, etc.). C’est la réponse
exacte, pas une hypothèse.

```bash
sh diag.sh              # 4S @ .60
sh diag.sh 192.168.1.61
```

Sortie enregistrée dans `logs/phone-diag.txt`. Colle-la : la section 3 donne la
liste des champs, la section 2 l’erreur exacte du dernier login.

---

## Dépannage

| Problème | Solution |
|----------|----------|
| Port 80 occupé | `sh stop.sh` puis `sudo systemctl stop nginx` |
| « catcher déjà lancé » | `sh stop.sh` |
| `./scripts/run-ultimate.sh` refusé | utiliser `sudo python3 scripts/run-ultimate.py` |
| SSH refusé | mot de passe = root du jailbreak (`passwd root` sur le tel) |

---

## Matériel

| Rôle | IP |
|------|-----|
| PC (T480) | 192.168.1.191 |
| iPhone 4S | 192.168.1.60 |
| IP RTS morte (DNAT) | 75.101.158.200 |

---

## Fichiers importants

- `go.sh` — lance le catcher
- `stop.sh` — arrête le catcher (sans toucher nginx)
- `phone.sh` — patch prefs Waze sur le tel
- `diag.sh` — récupère journal + champs Login depuis le tel
- `maps.sh` — envoie une carte générée sur le tel
- `pull.sh` — sync GitHub → T480
- `scripts/wazemap.py` — génère les cartes depuis OpenStreetMap (`selftest`, `build`)
- `scripts/rts_catcher_min.py` — mock RTS, détection de protocole
- `docs/PROGRESS.md` — notes techniques détaillées

---

## Et la 3.9.6 ?

Elle reste utilisable, mais deux inconnues subsistent, là où la 2.4.0.0 n’en a
aucune :

1. **Login** — protocole 202, format de réponse non documenté. Le catcher balaie
   16 candidats ; `sh diag.sh` donne la réponse exacte en lisant le binaire.
2. **Carte** — le format `.wzm`/`.wdf` n’a *probablement* pas changé (signature
   `WZDF`, version `0x00030000`), donc une carte générée ici a de bonnes chances
   de marcher aussi. À tester, ce n’est pas vérifié.

Le catcher journalise, dès le `MapDisplayed` et avant même que le login passe,
les tuiles que le client va réclamer :

```
centre 6.484638,46.365392 → tuiles attendues: s0=335677636, s1=668982409, …
```

---

## Pourquoi

Waze 3.9.6 sur iOS 6 parlait à des serveurs Waze depuis éteints. On redirige le trafic vers le PC et on répond au protocole legacy.
