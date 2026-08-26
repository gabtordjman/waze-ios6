# Relight — repo Cydia

Tweak public : **Relight** (`com.wazeios6.server`). Version actuelle : **1.0.2**.

`WazeIOS6Fix` (proxy mitm lab) n’est **pas** dans ce repo Cydia.

## Pourquoi pas `raw.githubusercontent.com` ?

Cydia sur iOS 6 casse souvent sur un **HTTP 307** (redirect GitHub).
Utilise une URL **sans redirect**.

## Source recommandée (ton VPS / catcher)

Après `sh go-vps.sh`, ajoute dans Cydia → Sources :

```
http://TON_IP:8080/cydia
```

(même IP/port que `CATCHER_HTTP_PORT` dans `.env`)

Le catcher sert `cydia/Packages`, `Packages.bz2`, `Release` et `debs/*.deb`.

## Alternative GitHub sans 307 : jsDelivr

Si le dépôt public est poussé (branche `vps` + `.deb` inclus) :

```
https://cdn.jsdelivr.net/gh/TON_USER/TON_REPO@vps/cydia
```

## Build + publish

```bash
sh tweak/build-deb.sh TON_IP:8080 1.0.2
sh cydia/make-repo.sh
git add -f cydia/debs/*.deb cydia/Packages cydia/Packages.bz2 cydia/Release
git commit -m "cydia: Relight 1.0.2"
git push origin vps
```

Chaque install Relight crée un nick `wazer…` (pas le compte partagé `ios6user`).
Mots de passe : `relight`. L’UI / la voix suivent le GPS (fra ou eng).
