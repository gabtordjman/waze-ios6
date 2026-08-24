#!/bin/sh
# Force la copie GitHub → T480 (écrase les modifs locales des scripts).
# Usage : cd /home/tordjman/Documents/Projets/waze-ios6 && sh scripts/sync-github.sh

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== sync GitHub → local ==="
BK="$ROOT/.backup-before-sync-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BK"
for f in README.md scripts/rts_catcher_min.py scripts/run-ultimate.sh scripts/dnsmasq-waze.conf; do
  [ -f "$f" ] && cp "$f" "$BK/" 2>/dev/null || true
done
echo "Backup local → $BK"

git fetch origin main
git checkout -B main origin/main 2>/dev/null || git reset --hard origin/main

echo "OK — HEAD=$(git rev-parse --short HEAD)"
echo "Lance : sudo python3 scripts/run-ultimate.sh"
