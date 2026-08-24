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

Deux étapes distinctes, ne pas les confondre :

1. **Login** — réparable ici, c’est du protocole. En cours via le balayage.
2. **Données de carte** — les tuiles venaient de `tiles*.waze.com`, éteints eux
   aussi. Le catcher journalise maintenant chaque URL de tuile demandée
   (`★★★ TUILE demandée`) et répond `404` plutôt qu’une fausse image, qui
   casserait le décodeur. Une fois le login passé, ces URL diront exactement quel
   format de tuiles il faudrait fournir.

Autrement dit : le login et la navigation temps réel sont un problème de
protocole ; afficher une vraie carte demandera en plus une source de tuiles.

---

## Pourquoi

Waze 3.9.6 sur iOS 6 parlait à des serveurs Waze depuis éteints. On redirige le trafic vers le PC et on répond au protocole legacy.
