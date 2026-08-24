#!/bin/sh
# Arrête proprement le catcher Waze (sans toucher nginx/apache).
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

echo "=== stop catcher ==="
for pat in rts_catcher_min.py run-ultimate.py run-ultimate.sh; do
  pkill -f "$pat" 2>/dev/null && echo "  pkill $pat"
done
sleep 1

if command -v ss >/dev/null 2>&1; then
  busy=$(ss -ltnp "sport = :80" 2>/dev/null | grep -v '^State' | grep -c LISTEN || true)
  if [ "$busy" -gt 0 ]; then
    echo "Port :80 encore occupé (peut-être nginx — pas tué volontairement) :"
    ss -ltnp "sport = :80" 2>/dev/null | grep LISTEN || true
  else
    echo "Port :80 libre"
  fi
fi

echo "OK — relance: sudo sh go.sh"
