#!/bin/sh
# Lance le catcher. Depuis la racine du repo :
#   sudo sh go.sh
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

for f in go.sh stop.sh diag.sh maps.sh phone.sh pull.sh scripts/run-ultimate.sh scripts/run-ultimate.py scripts/rts_catcher_min.py scripts/wazemap.py scripts/waze-diag.sh scripts/waze-maps-dir.sh; do
  [ -f "$f" ] && sed -i 's/\r$//' "$f" 2>/dev/null
done

echo "=== Waze iOS6 catcher ==="

LOCK="/tmp/waze-ios6-catcher.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "ERREUR: catcher déjà lancé. Autre terminal: sh stop.sh"
  exit 1
fi

sh "$ROOT/stop.sh" 2>/dev/null || true

echo "Lancement…"
if [ "$(id -u)" -eq 0 ]; then
  exec python3 "$ROOT/scripts/run-ultimate.py"
else
  exec sudo python3 "$ROOT/scripts/run-ultimate.py"
fi
