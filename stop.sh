#!/bin/sh
# Arrête le catcher Waze (sans toucher nginx/apache).
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

echo "=== stop catcher ==="
MY=$$
for pat in rts_catcher_min.py run-ultimate.py; do
  for pid in $(pgrep -f "$pat" 2>/dev/null); do
    [ "$pid" = "$MY" ] && continue
    kill -9 "$pid" 2>/dev/null && echo "  kill $pid ($pat)"
  done
done
sleep 0.5

if command -v ss >/dev/null 2>&1; then
  if ss -ltnp "sport = :80" 2>/dev/null | grep -q LISTEN; then
    echo "Port :80 encore occupé (nginx ? — pas tué volontairement) :"
    ss -ltnp "sport = :80" 2>/dev/null | grep LISTEN || true
  else
    echo "Port :80 libre"
  fi
fi

echo "OK — relance: sudo sh go.sh"
