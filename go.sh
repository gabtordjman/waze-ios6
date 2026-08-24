#!/bin/sh
# Depuis la racine du repo sur le T480 :
#   sudo sh go.sh
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

for f in go.sh phone.sh scripts/*.sh scripts/*.py; do
  if [ -f "$f" ]; then
    sed -i 's/\r$//' "$f" 2>/dev/null || true
  fi
done

echo "=== Waze iOS6 catcher ==="
echo "Repo: $ROOT"
exec sudo python3 scripts/run-ultimate.sh
