#!/bin/sh
# Patch iPhone (defaut 4S @ .60) :
#   sh phone.sh
#   sh phone.sh 192.168.1.61
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1
sed -i 's/\r$//' scripts/patch-iphone.sh scripts/waze-patch.sh scripts/map_auto.py 2>/dev/null || true

# Genere maps/auto/ depuis la derniere position vue par le catcher (si dispo)
if [ -f logs/rts-catcher.txt ]; then
  python3 scripts/map_auto.py ensure --from-log 2>/dev/null || true
fi

exec sh scripts/patch-iphone.sh "$@"
