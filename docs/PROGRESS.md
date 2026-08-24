# Waze iOS 6 — progression

**Date:** 2026-08-24  
**Repo:** `waze-ios6-github` (sync `/home/tordjman/Documents/Projets/waze-ios6` sur T480)  
**But:** Waze **3.9.6** sur iPhone jailbreaké iOS 6 — mock RTS morts depuis le PC.

---

## Démarrage rapide (depuis la racine du repo)

```bash
cd /home/tordjman/Documents/Projets/waze-ios6

# 1) Récupérer GitHub (si conflit git pull)
sh scripts/sync-github.sh

# 2) Catcher + DNAT + dnsmasq
sudo bash scripts/start-all.sh

# 3) Patch iPhone (dans un autre terminal)
sh scripts/patch-iphone.sh              # 4S @ .60
sh scripts/patch-iphone.sh 192.168.1.61 # autre iPhone
```

**Erreurs fréquentes :**
- `sed: scripts/...` introuvable → tu es dans `scripts/`, remonte d'un niveau
- `git pull` conflit → `sh scripts/sync-github.sh`
- `Host key verification failed` → `patch-iphone.sh` efface l'ancienne clé automatiquement
- `pipefail` / port 80 → sync GitHub d'abord (start-all.sh corrigé)

---

## État actuel

| Étape | Statut |
|--------|--------|
| Carte / licence sans GetGeo (`System.ServerId: 1`) | OK |
| DNAT `75.101.158.200:80/443` → PC | OK |
| Trafic HTTP `:80` `POST /rtserver/distrib/login` | OK |
| Prefs `iphone_no` + creds → Login POST (plus Register) | OK |
| `Download.*` → PC (icônes UI téléchargées) | OK — prouve que les prefs sont lues |
| Login accepté → plus de « Searching network » | **balayage auto** (rev `login-sweep-20260824d`) |
| GET tuiles | après login ; journalisé, 404 (pas de données de carte) |

**Rev catcher :** `login-sweep-20260824d`

### Pourquoi le login échouait (analyse source)

Le client envoie `ClientInfo,**202**`. La source GPL disponible
(`mkoloberdin/waze`, `Realtime/RealtimeNet.h`) définit
`RTNET_PROTOCOL_VERSION (150)` — deux protocoles différents.

En 150, `OnLoginResponse` (RealtimeNetRec.c) lit exactement :

```
id, cookie, rank, points, rating, prevRank, addon, pointsTs,
exclusiveMoods, maxProtocol, serverVersion        →  11 champs
```

Puis `bLoggedIn = TRUE`.

Le format 202 n’est pas public. Les deux erreurs possibles sont symétriques
(`websvc_trans.c`, `OnCustomResponse`) :

| Cas | Chemin | Résultat |
|-----|--------|----------|
| trop peu de champs | `ReadIntFromString` → NULL | `err_parser_unexpected_data` |
| trop de champs | reste de ligne lu comme tag | `err_parser_missing_tag_handler` |

`trans_failed` → `OnLoginResult` échoue → Waze renvoie `Login`. Symptôme observé.

Le format de la requête confirme le décalage :

- GPL 150 : `Login,%d,%s,%s,%d,%s,%s,%s,%d,%s` (commence par le n° de protocole)
- observé : `Login,ios6user,ios6pass,,1,0,<ts>,normal` (7 champs, protocole déplacé dans `ClientInfo`)

### Balayage automatique

16 formats candidats, un par tentative de login (~20 s d’intervalle) :

- `gpl11-seul`, `gpl11+inbox`
- `ver+1int` … `ver+6int` (entiers ajoutés après la version)
- `1int+ver` … `4int+ver` (entiers avant la version)
- `ipa17`, `ipa17+pad`, `ver+user`, `ver+8int`

Détection de succès : le client envoie une commande qui n’existe que si
`bLoggedIn == TRUE` (`At`, `SeeMe`, `GPSPath`, `NodePath`…). La variante gagnante
est écrite dans `logs/login-variant.txt` et réutilisée ensuite.

Forcer : `LOGIN_VARIANT=ver+2int sudo -E sh go.sh` · Recommencer : `rm logs/login-variant.txt`

### Enveloppe (validée)

- CRLF ; `Content-Length` = taille du corps
- `/distrib/` (V2) → préfixe fil `ack\r\n` **avant** l’HTTP
  (`OnHTTPAck` consomme `strlen("ack\r\n")`)
- keep-alive (pas de `Connection: close`)

Preuve que l’enveloppe est bonne : les POST `Stats` sur `/distrib/static`
reçoivent `RC,200,OK` et ne sont **pas** rejoués.

### Recherche / itinéraire

Répondre `RC,200,OK` seul à une recherche fait planter l’app (le parseur de
résultats n’a rien à lire). On renvoie maintenant des codes que `VerifyStatus`
connaît :

- recherche → `RC,600` → `err_as_could_not_find_matches` (« aucun résultat »)
- itinéraire → `RC,500` → `err_failed` (échec propre)

### Outil de diagnostic — `diag.sh`

Le binaire Waze contient les chaînes `roadmap_log` du parseur, dans l’ordre des
champs lus. `sh diag.sh` les extrait par SSH, avec le journal d’erreurs du
dernier login. C’est la source de vérité pour la 202, à préférer au balayage.

---

## Setup matériel

| Rôle | IP |
|------|-----|
| PC catcher (T480) | `192.168.1.191` |
| iPhone 4S (principal) | `192.168.1.60` |
| iPhone 4 / secondaire | `192.168.1.61` |
| IP RTS morte (DNAT) | `75.101.158.200` |

### Patch iPhone (auto-détecte UUID Waze, 4 ou 4S)

```bash
sh scripts/patch-iphone.sh              # défaut : 192.168.1.60 (4S)
sh scripts/patch-iphone.sh 192.168.1.61 # autre appareil
```

Mot de passe SSH = mot de passe **root** du jailbreak (pas le code de l'écran).
Après restore/rejailbreak : clé SSH changée → `patch-iphone.sh` la régénère seul.

### DNS iPhone

Réglages → Wi-Fi → (i) → DNS → **`192.168.1.191`** seul.  
Le launcher démarre aussi `dnsmasq` (sinkhole S3/tiles).

---

## Succès mesurable

1. Log catcher : **un seul** `POST /distrib/login` (pas de retry ~4 s)
2. UI : plus de « Searching network »
3. Log : `★ GET` vers `/tiles/` ou `lang.conf`

---

## Fichiers clés

| Fichier | Rôle |
|---------|------|
| `scripts/start-all.sh` | One-shot depuis racine repo |
| `scripts/run-ultimate.sh` | DNAT + dnsmasq + tcpdump + catcher |
| `scripts/rts_catcher_min.py` | Mock HTTP/HTTPS RTS |
| `scripts/waze-patch.sh` | Patch prefs (sur le tel, auto UUID) |
| `scripts/patch-iphone.sh` | Envoie le patch via SSH depuis le PC |
| `scripts/sync-github.sh` | Force sync GitHub → T480 |
| `mitm/fake-resources/` | lang.conf, langs, config |
| `logs/rts-catcher.txt` | Log détaillé |

---

## Protocole Login (rappel)

Requête typique :

```
ClientInfo,202,21,3.9.6.1,…
Login,ios6user,ios6pass,,1,0,<unix>,normal
MapDisplayed,…
ProtoBase64,…
```

Réponse mock :

```
RC,200,OK
LoginSuccessful,1,cookie1234567890,1,100,1,1,0,0,0,202,3.9.6.1
UpdateInboxCount,0
ServerConfig,5,Download,Tiles,http://192.168.1.191/tiles/
…
```

V2 : préfixe wire **`ack\r\n`** avant HTTP sur `/distrib/`.

**Piège doc :** champs PAD (`…,ios6user,0,…,F,F`) **sur la même ligne** après `3.9.6.1` → parse fail → retry Login.

---

## Docs GPL

- https://github.com/mkoloberdin/waze — `Realtime/RealtimeNetRec.c`, `websvc_trans/websvc_trans.c`

Le dépôt a **cinq branches** : `android` (défaut), **`iphone`**, `master`,
`symbian`, `wm`. La branche `iphone` est le code iOS et c’est elle qu’il faut
lire ici — on travaillait sur `android` jusqu’ici sans le savoir.

---

## Quelle version correspond au protocole 150

**Waze 2.4.0.0**, dernière version GPL v2 pour iPhone et Android (la v3 est une
réécriture propriétaire). Deux confirmations indépendantes :

- Wikipédia : « The last open-source client version for the iPhone and Android
  is 2.4.0.0, and for Windows Mobile 2.0. »
- `iphone/Xcode/Info.plist` du dépôt : `CFBundleVersion 2.4.0.0`,
  `CFBundleIdentifier com.waze.iphone`.

`Realtime/RealtimeNetDefs.h` (branche `iphone`) confirme
`RTNET_PROTOCOL_VERSION (150)` et
`RTNET_FORMAT_NETPACKET_9Login ("Login,%d,%s,%s,%d,%s,%s,%s,%d,%s")` : le
protocole est le **premier champ de `Login`**, il n’y a pas de `ClientInfo`.
C’est ce qui permet au catcher de distinguer les deux clients sans configuration.

### OnLoginResponse en 150 — les 11 champs, dans l’ordre

Relevé dans `Realtime/RealtimeNetRec.c` (branche `iphone`, l. 296-464) :

| # | Champ | Lecture | Erreur si absent |
|---|-------|---------|------------------|
| 1 | `iServerID` | `ReadIntFromString` | doit être ≠ `RT_INVALID_LOGINID_VALUE` (-1) |
| 2 | `ServerCookie` | `ExtractNetworkString` | 63 caractères max |
| 3 | `iMyRanking` | int | |
| 4 | `iMyTotalPoints` | int | |
| 5 | `iMyRating` | int | |
| 6 | `iMyPreviousRanking` | int | |
| 7 | `iMyAddon` | int | |
| 8 | `iPointsTimeStamp` | int | |
| 9 | `iExclusiveMoods` | int, termine sur `,\r\n` | |
| 10 | `iServerMaxProtocol` | int | |
| 11 | `serverVersion` | `ExtractNetworkString` | `MAX_SERVER_VERSION` = 15 |

Chaque échec pose `err_parser_unexpected_data` et sort de la boucle de réception.
La ligne `RC,200,…` avant le tag est **obligatoire** (`VerifyStatusAndTag`, appelé
avec `http_response_status_load(..., TRUE, ...)`).

À noter, `bIsNewbie` existe dans `RTConnectionInfo` en `iphone` mais pas en
`android` — il n’est **pas** lu par `OnLoginResponse`, donc il ne change pas le
compte de champs. Fausse piste écartée.

Codes de retour utiles (`VerifyStatus`) : `501` → `err_rt_unknown_login_id`,
`600` → `err_as_could_not_find_matches` (recherche sans résultat, pas un crash),
`2002` → `err_failed` non fatal. C’est ce qui justifie `RC,600` pour la recherche.

---

## Tuiles : le calcul est connu

`roadmap_tile.c` (branche `iphone`), porté en Python dans le catcher :

```
SQUARE_SIZE = 10 000 micro-degres, SCALE_STEP = 4, MAX_SQUARE_SIZE = 30 000 000
=> 6 echelles : 10000, 40000, 160000, 640000, 2560000, 10240000
lignes[e]   = 179 999 999 / taille[e] + 1
colonnes[e] = 359 999 999 / taille[e] + 1
base[e]     = somme des lignes*colonnes des echelles precedentes
index_lon   = (longitude + 180 000 000) / taille[e]
index_lat   = (latitude  +  90 000 000) / taille[e]
tuile       = base[e] + index_lon * lignes[e] + index_lat
```

Contrôle sur Lausanne (6.484638, 46.364603), échelle 0 :
`index_lon = 18648`, `index_lat = 13636`, `tuile = 18648 × 18000 + 13636 =`
**335677636**. Le catcher journalise ces identifiants dès le `MapDisplayed`,
avant même que le login passe.

## Cartes hors-ligne `.wzm` — implémenté

`roadmap_map_download.c` : `roadmap_map_download_region()` télécharge
`<Download.Source>/<region_code>/map<fips:05d>.wzm` vers
`roadmap_path_preferred("maps")`, puis `roadmap_tile_reset_session()` recharge
les tuiles. Activé par la préférence `Download.Enabled = yes`.

Un seul fichier, posable aussi directement par SSH sans passer par le réseau.
Le catcher annonce `ServerConfig,6,Download,Source,…` et
`ServerConfig,7,Download,Enabled,yes`, et sert le contenu de `maps/`.

`scripts/wazemap.py` produit ce fichier depuis OpenStreetMap. Tout ce qui suit
est relevé dans la source, pas déduit.

### Emplacement sur l’appareil

`unix/roadmap_path.c`, avec `HOME_PREFIX` vide sous `IPHONE` :

```
prefere : roadmap_path_cache()  + "/maps"     (# dans la table)
repli   : roadmap_path_bundle() + "/maps"     (+ dans la table)
```

`scripts/waze-maps-dir.sh` cherche le dossier réel sur le téléphone plutôt que
de coder ces chemins en dur — ils changent selon la version d’iOS.

### Conteneur `.wzm` (roadmap_data_format.h, roadmap_gzm.c)

```
"WGZM"  endianness=1  version=0x00030000        <- map_general_header
"WZDF"  endianness=1  version=0x00030000        <- tile_general_header, recopie
                                                   dans chaque tuile extraite
int min_lon, min_lat, max_lon, max_lat          <- filtre rapide avant recherche
int num_tiles
puis num_tiles x { int tile_id; uint offset; uint compressed_size; uint raw_size }
puis les blobs zlib bruts, sans en-tete
```

L’index **doit être trié par `tile_id`** : `roadmap_gzm_locate_entry` fait une
recherche dichotomique. Et le rectangle englobant doit contenir les tuiles,
sinon la fonction sort avant même de chercher.

### Tuile `.wdf` (roadmap_dbread.c)

```
"WZDF"  endianness=1  version=0x00030000
uint compressed_data_size    <- doit valoir taille_fichier - 20, sinon rejet
uint raw_data_size           <- doit valoir la taille apres decompression
puis zlib

decompresse :
  uint num_sections = 28   (model__tile)
  uint byte_alignment_bits
  uint end_offset[28]      <- fin de chaque section, non alignee
  donnees                  <- chaque section demarre a aligne(fin precedente)
```

Une section vide (`end_offset` égal au précédent) désactive proprement son
module : `roadmap_db_call_map` n’appelle le handler que si la taille est
non nulle. C’est ce qui permet de ne remplir que le strict nécessaire.

### Sections réellement remplies

| # | Section | Contenu |
|---|---------|---------|
| 9 | `line_data` | `{u16 from, to, first_shape, range}` |
| 10 | `line_bysquare1` | index cumulatif par catégorie, 1 enregistrement |
| 13 | `point_data` | `{u16 dx, dy}` relatifs au coin sud-ouest |
| 26 | `square_data` | `{int tile_id, scale; uint timestamp}` |

Les 24 autres restent vides. En particulier la section `shape` : chaque segment
OSM devient une ligne droite avec `first_shape = ROADMAP_LINE_NO_SHAPES`, ce qui
est visuellement identique à une polyligne et supprime l’indexation shape-par-
ligne, la partie la plus fragile du format.

### Contraintes à ne pas rater

- **Position** : `roadmap_point.h` fait
  `longitude = bord_ouest + dx × facteur_échelle`. Les `dx`/`dy` sont des `u16`,
  donc la géométrie doit être découpée aux frontières de tuiles.
- **Tri par catégorie** : `RoadMapLineBySquare.next[21]` est un cumul par cfcc.
  `roadmap_line_cfcc` cherche le premier `next[cfcc] > line_id`, donc les lignes
  doivent être triées par catégorie croissante et `next[20]` valoir le total.
- **32767 points par tuile au maximum** : une référence de point est masquée par
  `POINT_REAL_MASK 0x7FFF`, le bit haut étant `POINT_FAKE_FLAG` (point de
  bordure). Le générateur pose ce bit sur les extrémités créées par le découpage,
  ce qui permet à `roadmap_screen.c` de savoir que la route continue à côté.
- **Échelles** : pour rester sous la limite, les échelles grossières ne portent
  que les grands axes (échelle 1 sans les chemins piétons, échelle 2 uniquement
  autoroutes/nationales/bretelles).
- **Cohérence déclarée** : `num_roundabout` et `first_broken[8]` doivent valoir
  exactement le nombre d’éléments des sections correspondantes, sinon
  `roadmap_line_map` abandonne (« roundabout count mismatch »).

`python3 scripts/wazemap.py selftest` rejoue tous ces contrôles hors ligne, avec
la même validation que le client.
