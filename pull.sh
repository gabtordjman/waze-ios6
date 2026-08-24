#!/bin/sh
# Sync GitHub -> T480 puis corrige CRLF.
#   sh pull.sh
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

sed -i 's/\r$//' pull.sh go.sh phone.sh scripts/*.sh 2>/dev/null || true

echo "=== git pull (force origin/main) ==="
git fetch origin main || exit 1
git reset --hard origin/main || exit 1

for f in go.sh phone.sh pull.sh scripts/*.sh scripts/*.py; do
  if [ -f "$f" ]; then
    sed -i 's/\r$//' "$f" 2>/dev/null || true
  fi
done

echo "OK $(git rev-parse --short HEAD)"
echo "Lance: sudo sh go.sh"
