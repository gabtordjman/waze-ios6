#!/bin/sh
# Corrige les \r Windows — lancer AVANT tout autre script :
#   sh scripts/fix-crlf.sh
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
find scripts -type f \( -name '*.sh' -o -name '*.py' \) -print0 2>/dev/null | while IFS= read -r -d '' f; do
  sed -i 's/\r$//' "$f" 2>/dev/null || sed -i '' 's/\r$//' "$f"
  echo "fixed: $f"
done
echo "OK — relance: sh scripts/sync-github.sh"
