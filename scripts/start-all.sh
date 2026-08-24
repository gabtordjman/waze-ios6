#!/bin/sh
# Depuis la racine :  sudo sh scripts/start-all.sh
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

echo "=== Waze iOS6 demarrage ==="

for f in scripts/run-ultimate.sh scripts/rts_catcher_min.py scripts/waze-patch.sh scripts/patch-iphone.sh; do
  if [ -f "$f" ]; then
    sed -i 's/\r$//' "$f" 2>/dev/null || true
  fi
done

echo ""
echo "Patch 4S: sh scripts/patch-iphone.sh"
echo "DNS iPhone: 192.168.1.191"
echo ""
exec sudo python3 scripts/run-ultimate.sh
