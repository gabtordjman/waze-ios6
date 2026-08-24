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
