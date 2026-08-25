# Waze iOS 6 — serveurs et cartes reconstruits

Les serveurs Waze d’origine sont éteints. Ici un PC Linux sur le réseau local
répond à leur place, et les cartes sont fabriquées depuis OpenStreetMap.

Cible : **Waze 2.4.0.0** (dernière version iPhone / Android encore GPL).
La source est sur [github.com/mkoloberdin/waze](https://github.com/mkoloberdin/waze),
branche `iphone`. Rien n’est deviné : login, tuiles, overlay, reports, wazers,
c’est lu dans `Realtime/` et `roadmap_*.c`.

Waze 3.9.6 peut encore se connecter (protocole 202, format de login balayé).
Ce n’est plus le chemin principal.

---

## Ce qui marche aujourd’hui

- Login protocole 150 du premier coup (`LoginSuccessful`, 11 champs).
- Carte locale `.wzm` (look Waze : fond gris-bleu, rues grises, axes beige).
- Itinéraire OSRM + overlay violet collé aux segments `.wzm` (zoom rue).
- Guidage vocal français (`Prompts.Name=fra`). Pack anglais à part (`eng/`).
- Interface française (`lang.fra`). L’anglais a son propre `lang.eng`.
- Reports conservés ~30 minutes, renvoyés à chaque `At` / `SeeMe`.
- Points (ticker + total au login) et classement (menu Scoreboard).
- Wazers autour de la position (voisins réels s’il y en a, plus quelques
  silhouettes pour que la carte ne soit pas vide).

Le GPS public / VPS / DNS pour tout le monde n’est **pas** dans ce dépôt pour
l’instant : ça reste du LAN (`192.168.1.191`).

La révision du catcher s’affiche au lancement : `CATCHER_REV=proto150-route-20260826h`.
Si le log montre une ancienne rev, le T480 n’a pas le code.

---

## Lancer (T480)

```bash
cd /home/tordjman/Documents/Projets/waze-ios6
sh pull.sh
sh stop.sh
sudo sh go.sh          # laisse tourner
```

Autre terminal, après une nouvelle carte ou de nouvelles voix :

```bash
sh phone.sh            # 4S @ .60
# sh phone.sh 192.168.1.61
```

**iPhone :** Wi-Fi → DNS manuel → `192.168.1.191` → ouvrir Waze.

Le login 2.4 passe tout de suite. Pas besoin d’attendre un balayage de variantes
(ça ne concerne que la 3.9.6).

---

## Cartes

Pas de carte préfaite dans git : chacun génère la sienne autour de son GPS.

```bash
python3 scripts/wazemap.py selftest
python3 scripts/map_auto.py build --lon 6.4847 --lat 46.3646 --force
sh phone.sh
```

Ça produit `maps/auto/map77001.wzm` + `77001_index.wdf`. Les deux vont dans
`Waze.app/maps` (c’est le seul chemin que l’iPhone lit pour l’index).

`--force` est obligatoire si on a changé les catégories de routes (sinon le
cache OSM est réutilisé et les axes restent tous blancs).

Ne pas lancer Overpass depuis `phone.sh` : un rebuild centré sur le pan de
carte (et pas le GPS) a déjà produit un écran vide.

---

## Voix et langues

Les MP3 se lisent dans `Documents/sound/<Prompts.Name>/`.

```bash
python3 scripts/gen_fr_prompts.py            # fra + eng (gTTS)
python3 scripts/gen_fr_prompts.py --langs-only   # uniquement lang.fra / lang.eng
sh phone.sh
```

`phone.sh` copie **fra vers fra** et **eng vers eng**. Plus de français collé
par-dessus l’anglais (ça donnait « En route » dans les deux langues, ou le
silence si le fichier anglais était un faux MP3 de 1 Ko).

Dans Waze : Réglages → langue / voix. Français = `fra`. English = `eng`.

---

## Reports, points, wazers, classement

Les signalements restent ~30 minutes (`logs/alerts.json` survit à un restart
du catcher). Chaque report ajoute 6 points (`UpdateUserPoints`) ; le total
repart au prochain login.

Le menu Classement ouvre le navigateur intégré sur `http://www.waze.com`
(c’est en dur dans `roadmap_scoreboard.m`). `phone.sh` ajoute `www.waze.com`
dans `/etc/hosts` vers le PC, et le catcher sert une petite page HTML.

Les autres téléphones connectés au même catcher apparaissent comme wazers.
Tout seul, quelques voisins simulés tournent autour du GPS.

---

## Fichiers utiles

| Fichier | Rôle |
|---------|------|
| `go.sh` | lance le catcher (ports 80 / 443) |
| `stop.sh` | l’arrête |
| `phone.sh` | prefs, hosts, carte, voix sur le téléphone |
| `pull.sh` | GitHub → T480 |
| `scripts/rts_catcher_min.py` | mock RTS |
| `scripts/waze_route.py` | overlay + manœuvres |
| `scripts/waze_alerts.py` | reports / points |
| `scripts/waze_users.py` | wazers + HTML classement |
| `scripts/map_auto.py` | carte OSM autour du GPS |
| `docs/PROGRESS.md` | notes plus techniques |

Tests sans téléphone : `python3 scripts/test_catcher_offline.py`.

---

## Matériel (labo actuel)

| Rôle | IP |
|------|-----|
| PC (T480) | 192.168.1.191 |
| iPhone 4S | 192.168.1.60 |

---

## 3.9.6

Protocole 202, login non documenté : le catcher balaie des formats et mémorise
celui qui passe dans `logs/login-variant.txt`. `sh diag.sh` lit les messages
d’erreur dans le binaire. La carte `.wzm` a de bonnes chances de marcher aussi,
ce n’est pas le focus.
