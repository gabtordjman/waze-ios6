#!/bin/sh
# Patch iPhone (defaut 4S @ .60) :
#   sh phone.sh
#   sh phone.sh 192.168.1.61
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1
sed -i 's/\r$//' scripts/patch-iphone.sh scripts/waze-patch.sh scripts/map_auto.py 2>/dev/null || true

# Ne PAS régénérer Overpass ici. --from-log prenait le « centre » MapDisplayed
# (pan) et remplaçait maps/auto/ par des tuiles rue vides = écran néant.
# Carte : python3 scripts/map_auto.py build --lon LON --lat LAT --force
# puis sh phone.sh (envoie le .wzm déjà sur disque).

exec sh scripts/patch-iphone.sh "$@"
