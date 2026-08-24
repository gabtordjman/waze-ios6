#!/bin/sh
# Force GitHub -> T480.  cd repo && sh scripts/sync-github.sh
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

echo "=== sync GitHub -> local ==="
BK="$ROOT/.backup-before-sync-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BK"
for f in README.md scripts/rts_catcher_min.py scripts/run-ultimate.sh; do
  if [ -f "$f" ]; then
    cp "$f" "$BK/" 2>/dev/null || true
  fi
done
echo "Backup -> $BK"

git fetch origin main || exit 1
git checkout -B main origin/main 2>/dev/null || git reset --hard origin/main || exit 1

# CRLF Windows -> LF apres pull
find scripts -type f \( -name '*.sh' -o -name '*.py' \) -exec sed -i 's/\r$//' {} + 2>/dev/null || true

echo "OK HEAD=$(git rev-parse --short HEAD 2>/dev/null)"
echo "Lance: sudo python3 scripts/run-ultimate.sh"
