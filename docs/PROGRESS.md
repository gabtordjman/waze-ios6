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
| Login accepté → plus de « Searching network » | **À valider** (rev `login-gpl11-sc-20260824a`) |
| GET tuiles / lang.conf | **En cours** (ServerConfig + GET stub) |

**Rev catcher :** `login-gpl11-sc-20260824a`

- Login : Freemap **11 champs** exacts, **CRLF**, id **1**, pas de PAD sur la même ligne
- Lignes séparées : `UpdateInboxCount,0` + `ServerConfig` (Tiles, Config, Langs…)
- keep-alive sur Login (pas de `Connection: close`)
- GET : lang.conf, lang.eng, tuiles PNG 1×1

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
