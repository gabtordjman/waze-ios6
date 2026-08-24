#!/bin/sh
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1
sed -i 's/\r$//' go.sh stop.sh diag.sh maps.sh phone.sh pull.sh scripts/*.sh scripts/*.py 2>/dev/null
git fetch origin main && git reset --hard origin/main
sed -i 's/\r$//' go.sh stop.sh diag.sh maps.sh phone.sh pull.sh scripts/*.sh scripts/*.py 2>/dev/null
echo "OK $(git rev-parse --short HEAD) — sudo sh go.sh"
