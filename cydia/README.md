# Waze iOS6 — repo Cydia

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

Plus tard tu pourras simplifier avec GitHub Pages / domaine custom pointant
sur le même contenu.

## Build + publish

```bash
sh tweak/build-deb.sh TON_IP:8080 1.0.0
sh cydia/make-repo.sh
git add -f cydia/debs/*.deb cydia/Packages cydia/Packages.bz2 cydia/Release
git commit -m "cydia: release 1.0.0"
git push origin vps
```

Compte Waze après install : `ios6user` / `ios6pass`.
