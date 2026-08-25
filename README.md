# Waze iOS 6 — serveur VPS

Branche dédiée au déploiement public. Les serveurs Waze d’origine sont éteints :
ce dépôt fait tourner un mock RTS pour **Waze 2.4.0.0** (iPhone jailbreaké),
avec cartes OSM générées autour du GPS de chaque utilisateur.

Cible client : tweak Cydia (voir [`cydia/`](cydia/)) qui redirige Waze vers
l’IP publique de ce serveur.

---

## Contenu de cette branche

| Chemin | Rôle |
|--------|------|
| `go-vps.sh` | démarre le catcher (mode VPS) |
| `stop.sh` | arrête le catcher |
| `.env.example` | modèle de config (à copier en `.env`) |
| `.env` | **local uniquement** — ignoré par git |
| `scripts/` | catcher, cartes OSM, tuiles, routing, alerts |
| `mitm/fake-resources/` | langs, config, images, sons servis en HTTP |
| `mitm/certs/tls/` | certificat HTTPS (SAN = IP, optionnel) |
| `maps/` | cartes générées au runtime (vide au clone) |
| `logs/` | logs catcher / état carte |
| `deploy/` | unit systemd |
| `tweak/` + `cydia/` | build du `.deb` Cydia (PC de build, pas le VPS) |

---

## Prérequis VPS

- Debian / Ubuntu (Python 3.10+)
- Ports **80/tcp** et **443/tcp** ouverts
- IP publique fixe
- Root (ports bas) ou adapter `CATCHER_HTTP_PORT` dans `.env`

---

## Installation (premier coup)

```bash
# Sur le VPS
sudo mkdir -p /opt/waze-ios6
sudo chown "$USER":"$USER" /opt/waze-ios6
cd /opt/waze-ios6

git clone -b vps --single-branch https://github.com/VOTRE_USER/waze-ios6.git .
# ou, si le dépôt existe déjà :
# git remote add origin https://github.com/VOTRE_USER/waze-ios6.git
# git fetch origin vps
# git checkout -B vps origin/vps

cp .env.example .env
nano .env   # WAZE_SERVER_IP=TON_IP_PUBLIQUE
```

Exemple `.env` (Apache déjà sur 80/443 → catcher ailleurs) :

```
WAZE_MODE=vps
WAZE_SERVER_IP=203.0.113.50
SKIP_DNS=1
SKIP_DNAT=1
SKIP_TCPDUMP=1
CATCHER_HTTP_PORT=8080
CATCHER_HTTPS_PORT=8443
```

Le catcher annonce alors `http://IP:8080/...` dans GetGeo. Ouvre le firewall
sur **8080** et **8443** (pas besoin de toucher Apache).

### Lancer à la main

```bash
sudo sh go-vps.sh
```

Laisser le terminal ouvert, ou passer en systemd :

```bash
sudo cp deploy/waze-catcher.service /etc/systemd/system/
# Adapter WorkingDirectory / EnvironmentFile si le chemin n'est pas /opt/waze-ios6
sudo systemctl daemon-reload
sudo systemctl enable --now waze-catcher
sudo journalctl -u waze-catcher -f
```

### Firewall

```bash
sudo ufw allow 8080/tcp
sudo ufw allow 8443/tcp
sudo ufw reload
```

### Tweak / .deb (IP + port)

Le `.deb` **n’est pas** dans git (artefact local). À construire avec la même
IP **et** le port HTTP :

```bash
sh tweak/build-deb.sh 203.0.113.50:8080 1.0.0
sh cydia/make-repo.sh
```

Sans `:8080` dans le `.deb`, l’iPhone parlerait encore au port 80 (Apache).

---

## Mise à jour

```bash
cd /opt/waze-ios6
git pull origin vps
sudo systemctl restart waze-catcher   # ou : sudo sh stop.sh && sudo sh go-vps.sh
```

Le fichier `.env` n’est **pas** écrasé par `git pull` (il est dans `.gitignore`).

---

## Comportement runtime

1. iPhone (tweak Cydia) → HTTP `http://WAZE_SERVER_IP/rtserver`
2. Login protocole 150 + GetGeo → config `Download.*`, tuiles, scoreboard
3. Premier GPS (`At` / `Location`) → build carte OSM dans `maps/auto/` (~30–90 s)
4. Expansion Overpass si pan / destination hors bbox (file d’attente : 1 job à la fois)
5. Tuiles : `GET /tiles/…` depuis le `.wzm` (+ stubs hors zone)
6. Signalements, wazers, classement HTML

Compte client par défaut (tweak) : `ios6user` / `ios6pass`.

---

## Tweak Cydia (sur un PC de build, pas le VPS)

```bash
sh tweak/build-deb.sh TON_IP_PUBLIQUE 1.0.0
sh cydia/make-repo.sh
git add cydia/ && git commit -m "cydia: release 1.0.0" && git push origin vps
```

Sur l’iPhone : Cydia → Sources →

```
https://raw.githubusercontent.com/VOTRE_USER/waze-ios6/vps/cydia
```

Installer **Waze iOS6 Server**, ouvrir Waze 2.4.

Détails : [`cydia/README.md`](cydia/README.md).

---

## Sécurité (repo public)

- Serveur mock **ouvert** : pas d’auth forte, compte partagé
- Ne pas committer `.env`, clés privées hors `mitm/certs` de lab, ni dumps perso
- Overpass : un build à la fois (rate-limit interne)
- Surveiller disque (`maps/`, `logs/`)

---

## Dépannage

| Symptôme | Piste |
|----------|--------|
| Port 80 occupé | `ss -ltnp sport = :80` — arrêter nginx ou changer `CATCHER_HTTP_PORT` |
| Login refuse | vérifier `WAZE_SERVER_IP` = IP vue par l’iPhone ; `journalctl -u waze-catcher` |
| Carte vide | attendre GPS + Overpass ; logs `maps/auto/` ; `★ tuile` dans les logs |
| Pas de GET `/tiles/` | prefs iPhone : `Download.Tiles` / tweak pas à jour |

Tests sans réseau : `python3 scripts/test_catcher_offline.py`.
