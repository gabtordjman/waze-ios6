#!/bin/sh
# Patch iPhone (defaut 4S @ .60) :
#   sh phone.sh
#   sh phone.sh 192.168.1.61
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1
sed -i 's/\r$//' scripts/patch-iphone.sh scripts/waze-patch.sh 2>/dev/null || true
exec sh scripts/patch-iphone.sh "$@"
