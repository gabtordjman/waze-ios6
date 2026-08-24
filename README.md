# Waze 3.9.6 — iOS 6 jailbreak

Mock des serveurs RTS morts depuis un PC Linux. Cible : iPhone 4S @ `192.168.1.60`.

---

## État honnête (août 2026)

| Fonction | Statut |
|----------|--------|
| Catcher HTTP :80 + DNAT | **OK** |
| Licence / skip GetGeo (`ServerId: 1`) | **OK** |
| Téléchargements (icônes, langues) depuis le PC | **OK** |
| Login POST reçu par le PC | **OK** |
| Login **accepté** → plus « Searching network » | **en recherche auto** |
| Tuiles / carte | bloqué par le login, **puis** par l’absence de données de carte |

### Le vrai blocage

L’app envoie `ClientInfo,**202**` : c’est le protocole 202. La seule source Waze
publique (GPL, `mkoloberdin/waze`) est en protocole **150**, où `OnLoginResponse`
lit **11 champs** après `LoginSuccessful`. La 202 en attend un nombre différent,
et ce format n’est documenté nulle part (Waze a arrêté l’open source avant la 3.9).

Côté client, se tromper échoue toujours :

- trop peu de champs → `err_parser_unexpected_data`
- trop de champs → le reste de la ligne est lu comme un tag inconnu → `err_parser_missing_tag_handler`

Dans les deux cas la transaction échoue et Waze relance `Login`. C’est exactement
ce qu’on observe.

**Donc on arrête de deviner** : le catcher essaie automatiquement 16 formats, un
par tentative de login, et s’arrête sur celui que l’app accepte.

### Quelle version parle le protocole 150 ?

**Waze 2.4.0.0** — la dernière version publiée sous GPL v2, pour iPhone et Android
(la v3 est une réécriture complète, passée en propriétaire). Vérifié à deux
sources : Wikipédia (« The last open-source client version for the iPhone and
Android is 2.4.0.0 ») et le dépôt lui-même, `iphone/Xcode/Info.plist` →
`CFBundleVersion 2.4.0.0`.

Le mirroir a une branche **`iphone`** : c’est bien le code iOS, pas seulement
l’Android. Son `Realtime/RealtimeNetRec.c` donne `OnLoginResponse` mot pour mot,
donc la réponse exacte :

```
RC,200,OK
LoginSuccessful,<id>,<cookie>,<rank>,<points>,<rating>,<prevRank>,<addon>,<pointsTs>,<moods>,<maxProto>,<version>
```

Le catcher **détecte le protocole tout seul** et n’a plus rien à deviner en 150 :

| Requête reçue | Mode |
|---------------|------|
| `Login,150,<user>,…` (protocole en tête) | réponse GPL exacte, login OK du 1er coup |
| `ClientInfo,202,…` puis `Login,<user>,…` | balayage des 16 formats candidats |

Donc si tu installes la 2.4.0.0, il n’y a **aucun patch à faire** : lance le
catcher, il bascule seul.

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
- `pull.sh` — sync GitHub → T480
- `scripts/rts_catcher_min.py` — mock RTS + balayage des formats de login
- `docs/PROGRESS.md` — notes techniques détaillées

---

## Et la carte ?

Deux étapes distinctes, ne pas les confondre. **Passer en 2.4.0.0 règle la 1, pas
la 2** — les serveurs de carte sont morts pour toutes les versions.

1. **Login** — protocole. Résolu en 150, en recherche en 202.
2. **Données de carte** — les tuiles venaient de `tiles*.waze.com`, éteints eux
   aussi. Aucune version d’app n’y change quoi que ce soit.

Ce que la source GPL apporte quand même, et qui change tout pour la suite :

- `roadmap_tile.c` donne le calcul exact des identifiants de tuile. Le catcher
  le refait en Python et journalise, dès le `MapDisplayed`, les tuiles que le
  client va réclamer (`centre 6.484638,46.365392 → tuiles attendues: s0=335677636…`).
  Formule : `base[echelle] + index_lon * lignes + index_lat`, coordonnées en
  micro-degrés, tuile de 0,01° à l’échelle 0, six échelles au total.
- `roadmap_map_download.c` révèle une porte de sortie bien plus simple que
  servir les tuiles une par une : Waze sait télécharger un **paquet de carte
  hors-ligne** `<Download.Source>/<region>/map<fips:05d>.wzm`, l’écrire dans
  `maps/`, puis appeler `roadmap_tile_reset_session()`. Le catcher annonce
  maintenant `Download,Source` et `Download,Enabled,yes`, et sert le contenu de
  `maps/`. Il reste à fabriquer le `.wzm` — c’est le vrai chantier restant.

Dépose les tuiles brutes dans `tiles/` (nommées par identifiant) et les paquets
dans `maps/` : le catcher les sert sans configuration.

---

## Pourquoi

Waze 3.9.6 sur iOS 6 parlait à des serveurs Waze depuis éteints. On redirige le trafic vers le PC et on répond au protocole legacy.
