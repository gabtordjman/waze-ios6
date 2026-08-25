# Waze iOS6 — repo Cydia

Ajoute cette source dans Cydia (Sources → Edit → Add):

```
https://raw.githubusercontent.com/VOTRE_USER/waze-ios6/vps/cydia
```

Puis installe **Waze iOS6 Server**.

Le `.deb` est construit avec l'IP du VPS :

```bash
# Sur un PC de build (clone branche vps)
sh tweak/build-deb.sh VOTRE_IP_VPS [version]
sh cydia/make-repo.sh
git add cydia/ && git commit -m "cydia: release" && git push origin vps
```

Compte Waze par défaut après installation : `ios6user` / `ios6pass`.
