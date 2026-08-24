#!/bin/bash
# Lance tout depuis la racine du repo (waze-ios6).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== Waze iOS6 — démarrage ($ROOT) ==="

for f in scripts/run-ultimate.sh scripts/rts_catcher_min.py scripts/waze-patch.sh scripts/patch-iphone.sh; do
  [ -f "$f" ] && sed -i 's/\r$//' "$f"
done

echo
echo "Patch iPhone 4S (.60) :  sh scripts/patch-iphone.sh"
echo "Patch autre (.61)     :  sh scripts/patch-iphone.sh 192.168.1.61"
echo "Wi-Fi iPhone → DNS = 192.168.1.191"
echo
exec sudo python3 scripts/run-ultimate.sh
