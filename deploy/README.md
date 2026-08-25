# Déploiement VPS (détails)

Voir le [README principal](../README.md) pour le parcours complet.

## Fichiers

| Fichier | Usage |
|---------|--------|
| `../.env.example` | modèle → copier en `../.env` |
| `waze-catcher.service` | `sudo cp` vers `/etc/systemd/system/` |

## Chemins

Par défaut le service attend le dépôt dans `/opt/waze-ios6`.
Si autre chemin, éditer `WorkingDirectory` et `EnvironmentFile` dans l’unit.
