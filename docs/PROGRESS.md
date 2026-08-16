# Waze iOS 6 — progression (reprise)

**Date:** 2026-08-17 ~00:10  
**Repo:** `waze-ios6-github` (sync aussi `/home/tordjman/Documents/Projets/waze-ios6` sur le T480)  
**But:** faire marcher Waze **3.9.6** sur iPhone jailbreaké iOS 6 en mockant les serveurs RTS morts depuis le PC.

---

## État actuel (où on s’arrête)

| Étape | Statut |
|--------|--------|
| Carte / licence sans GetGeo (`System.ServerId: 1`) | OK |
| DNAT `75.101.158.200:80/443` → PC + hosts `rt.waze.com` | OK |
| Trafic HTTP `:80` `POST /rtserver/distrib/…` (presque jamais `:443`) | OK |
| Prefs `Welcome Wizard.First time: **iphone_no**` + Name/Password | OK |
| **Login POST** (plus de Register PhoneMinimal) | **OK — breakthrough** |
| `LoginSuccessful` accepté → session stable / plus de Searching | **À RETESTER** (fix doc Freemap) |
| GET tuiles (`Download.Tiles`) | pas encore |

### Fix doc (2026-08-17) — rev `login-gpl11-ka-20260817a`

Freemap `OnLoginResponse` lit **exactement 11 champs** après `LoginSuccessful`, puis `bLoggedIn=TRUE`. Le `ver` se termine sur `,\r\n` (TRIM). **Tout CSV en trop** (PAD / IPA17) reste dans le buffer → prochain « tag » (`1`, `ios6user`…) → `err_parser_missing_tag_handler` → transaction failed.

`RealTimeLoginState()` = `bLoggedIn` **et** pas d’erreur réseau/RT **et** `LastNetConnect_Success`. D’où « Searching network » même après un parse partiel.

Réponse Login maintenant :

```
RC,200,OK
LoginSuccessful,4242,2Dyqtmg7r0HCZPFw,1,100,1,1,0,0,0,202,3.9.6.1
UpdateInboxCount,0
```

+ **keep-alive** (plus de `Connection: close` sur Login).

Le burst **Stats** (ClientInfo + Stats, sans UID Freemap) = analytics IPA, **pas** preuve de login OK.

**Succès :** 1 seul Login, Searching disparaît, éventuellement `★ GET` tiles.

---

## Setup matériel / IPs

| Rôle | IP / note |
|------|-----------|
| PC catcher (Debian T480) | `192.168.1.191` |
| iPhone 4 (principal) | `192.168.1.60` UUID app `8047C930-9816-413D-8F01-98BEB2775E5A` |
| iPhone 4S (secondaire) | `192.168.1.61` |
| Ancienne IP RTS morte | `75.101.158.200` (DNAT vers PC) |

SSH iOS 6 (clés anciennes) :

```bash
scp -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa \
  scripts/iphone-patch-4.sh root@192.168.1.60:/tmp/waze-patch.sh
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa \
  root@192.168.1.60 "sed -i 's/\r$//' /tmp/waze-patch.sh; sh /tmp/waze-patch.sh"
```

Catcher :

```bash
sed -i 's/\r$//' scripts/run-ultimate.sh scripts/rts_catcher_min.py
sudo python3 scripts/run-ultimate.sh
```

Dernière rev catcher : **`login-gpl11-ka-20260817a`**  
(Freemap-11 exact + `UpdateInboxCount,0` + keep-alive ; PAD retiré = leftover poison).

---

## Fichiers clés

| Fichier | Rôle |
|---------|------|
| `scripts/run-ultimate.sh` | Lance catcher + DNAT + tcpdump pcap |
| `scripts/rts_catcher_min.py` | Mock HTTP/HTTPS RTS |
| `scripts/iphone-patch-4.sh` | Prefs/user téléphone (ServerId, Realtime, tiles, `iphone_no`) |
| `scripts/iphone-putty-v2off.txt` | Même patch ligne à ligne PuTTY |
| `scripts/rts_catcher.py` | Ancien catcher ; contient déjà `_LOGIN_IPA` / `_LOGIN_PAD` |
| `logs/ultimate-latest.pcap` | Capture complète iPhones |
| `logs/rts-catcher.txt` | Log catcher |

---

## Wire format réel observé (Login)

Requête (extrait) :

```
ClientInfo,202,21,3.9.6.1,eng,<lon>,<lat>,Apple,iPhone3\,1,iPhone,640,960,normal,6.1.3,0,2,signup_type,Unknown,upgrade_type,Unknown,F,en,<UUID>
Login,ios6user,ios6pass,,1,0,<unix>,normal
MapDisplayed,<bbox…>,<scale>
ProtoBase64,yj4s4oMBKAokQjQyMURGRjItRkQxNi00OUJCLUIyMDMtQjA4RThDMzJFRjE1EAA=
```

Notes :

- Protocole client **202** (Freemap GPL ouvert ≈ **150**) → parseurs response **pas identiques**.
- Path toujours **`/rtserver/distrib/login`** → V2 → préfixe obligatoire **`ack\r\n`** puis HTTP (sinon « Connecting »).
- `signup_type,Unknown` (plus `PhoneMinimal`) après `iphone_no` + creds.
- Login wire = `Login,<user>,<pass>,<nick vide>,…` (pas le `Login,%d,%s,…` Freemap).

Réponses déjà testées (toutes → retry Searching) :

1. Freemap 11 champs :  
   `LoginSuccessful,1,cookie123456,1,100,1,1,0,0,0,202,3.9.6.1`
2. IPA17 (+ ServerConfig Tiles/Config/…) :  
   `…3.9.6.1,1,ios6user,0,1360000000,0,ios6user` + lignes `ServerConfig`
3. (en cours) PAD + cookie Jeske + id `4242`, **sans** ServerConfig : rev `login-pad-20260816ac`

GPL Freemap `OnLoginResponse` (`RealtimeNetRec.c`) :  
`id, cookie, rank, points, rating, prev, addon, ts, moods, maxProto, ver` puis `bLoggedIn=TRUE`.  
Champs IPA après `ver` = hypothèse (non dans le GPL public).

---

## Register (historique, contourné)

- PhoneMinimal forçait `Register,` tronqué → `Failed to create account`.
- Freemap Register = `RegisterSuccessful,<user>,<pass>`.
- Contournement qui a marché :  
  `Welcome Wizard.First time: **iphone_no**` (pas `no` — constante iPhone dans `roadmap_welcome_wizard.h`)  
  + `Realtime.Name` / `Password` dans fichier **`user`**.

Dump binaire utile :

```
RegisterSuccessful\0RegisterConnectSuccessful\0GeoServerConfig\0…\0LoginSuccessful
```

À refaire pour Login :

```sh
# dans iphone-patch-4.sh — od 128 bytes @ LoginSuccessful
```

---

## Ce qui marche déjà (ne pas casser)

1. `System.ServerId: 1` → skip GetGeo / license OK / UI map vide.
2. Realtime **Enabled** (Disabled = plus de Connecting mais **plus de tuiles**).
3. V2 : `ack\r\n` sur tout `/distrib/`.
4. Content-Type `binary/octet-stream` (comme `wst_init` Freemap).
5. Keepalive : 2 sockets TCP précoces ; ne pas FIN après timeout court sur socket vide (sinon RST plus tard). Pour Login on utilise `Connection: close` volontairement après la réponse.

---

## Pistes pour le prochain chat (par priorité)

1. **Interpréter Stats post-Login** : est-ce `SendAllMessagesTogether` (login OK puis drop) ou analytics sans session ? Comparer si Searching disparaît 1 s puis revient.
2. **Forensics binaire** : `od` / `strings` autour de `LoginSuccessful` et `ProtoBase64` dans `Waze.app/Waze`.
3. **Decoder ProtoBase64** (UUID device dans le blob) — réponse miroir attendue ?
4. Tester Login **GPL11 seul** + `keep-alive` (sans `Connection: close`) — le FIN immédiat peut couper le WST avant fin de parse.
5. Tags optionnels **après** une ligne LoginSuccessful *entièrement* consommée (`UpdateInboxCount`, etc.).
6. Après login stable : stub `GET …/tiles` (PNG 1×1 déjà dans le catcher).

**Succès mesurable :**

- Plus de retry Login / plus de Searching network.
- `★ GET …/tiles` (ou lang/images).

---

## Docs externes utiles

- GPL : https://github.com/mkoloberdin/waze (branche `android`) — `Realtime/RealtimeNetRec.c` (`OnLoginResponse`, `OnRegisterResponse`), `websvc_trans/websvc_trans.c` (`OnHTTPAck`).
- iPhone first-time : `WELCOME_WIZ_FIRST_TIME_No = "iphone_no"`.
- Jeske BlackHat EU-13 : Floating Car Data / Waze — ID + cookie après auth (pas de pcap Register public trouvé).
- **Pas de documentation officielle Waze** pour `/rtserver/distrib/*`.

---

## Message court pour le nouvel agent

> On mock Waze 3.9.6 iOS6. GetGeo contourné (ServerId=1). Prefs `iphone_no` + user/pass → Login POST `/rtserver/distrib/login` avec ack V2. LoginSuccessful mocké est **refusé** (retry + Searching network). Lire `docs/PROGRESS.md`, logs Login request complets, forensics `LoginSuccessful` dans le binaire, ne pas re-cycler Register.
