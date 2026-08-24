# Waze 3.9.6 — iOS 6 jailbreak

Mock des serveurs RTS morts depuis un PC Linux. Cible : iPhone 4S @ `192.168.1.60`.

---

## État honnête (août 2026)

| Fonction | Statut |
|----------|--------|
| Catcher HTTP :80 + DNAT | **OK** (si `go.sh` démarre sans erreur) |
| Licence / skip GetGeo (`ServerId: 1`) | **OK** |
| Login POST reçu par le PC | **OK** |
| Login accepté → plus « Searching network » | **PAS ENCORE** |
| Carte / tuiles | **PROCHAINE ÉTAPE** |

Le blocage actuel = format réponse `LoginSuccessful`. Le mock envoie la bonne structure Freemap ; l’app retente encore le login. Les tuiles viennent **après** un login stable.

---

## T480 — 2 commandes

```bash
cd /home/tordjman/Documents/Projets/waze-ios6
sh pull.sh
sudo sh go.sh          # reste ouvert — tu dois voir HTTP :80
```

Autre terminal : `sh phone.sh`

**Si port 80 occupé (nginx/apache)** :
```bash
sh stop.sh
sudo systemctl stop nginx   # si besoin
sudo sh go.sh
```

**Si go.sh dit « déjà en cours »** : `sh stop.sh` puis relance.

**Alternative directe :**
```bash
sudo python3 scripts/run-ultimate.py
```

**iPhone :** Wi-Fi → DNS manuel → `192.168.1.191` → ouvre Waze.

**Succès catcher :** tu vois `HTTP :80` sans `Address already in use`.

**Mot de passe SSH** = root du jailbreak (`passwd root` sur le tel si oubli).

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
- `phone.sh` — patch prefs Waze sur le tel
- `pull.sh` — sync GitHub → T480
- `scripts/rts_catcher_min.py` — mock login/tuiles
- `docs/PROGRESS.md` — notes techniques détaillées

---

## Pourquoi

Waze 3.9.6 sur iOS 6 parlait à des serveurs Waze depuis éteints. On redirige le trafic vers le PC et on répond au protocole legacy.
