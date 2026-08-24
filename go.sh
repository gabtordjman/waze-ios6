#!/bin/sh
# Lance le catcher. Depuis la racine du repo :
#   sudo sh go.sh
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

for f in go.sh phone.sh pull.sh scripts/run-ultimate.py scripts/rts_catcher_min.py; do
  [ -f "$f" ] && sed -i 's/\r$//' "$f" 2>/dev/null
done

echo "=== Waze iOS6 catcher ==="

if [ "$(id -u)" -eq 0 ]; then
  exec python3 "$ROOT/scripts/run-ultimate.py"
else
  exec sudo python3 "$ROOT/scripts/run-ultimate.py"
fi
