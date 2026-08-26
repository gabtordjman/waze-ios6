#!/bin/sh
# Arrête le catcher Waze (sans toucher apache/nginx/node).
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

HTTP_PORT="${CATCHER_HTTP_PORT:-80}"
HTTPS_PORT="${CATCHER_HTTPS_PORT:-443}"

echo "=== stop catcher ==="
MY=$$
for pat in rts_catcher_min.py run-ultimate.py; do
  for pid in $(pgrep -f "$pat" 2>/dev/null); do
    [ "$pid" = "$MY" ] && continue
    kill -9 "$pid" 2>/dev/null && echo "  kill $pid ($pat)"
  done
done
sleep 0.5

_check_port() {
  p="$1"
  [ -n "$p" ] || return 0
  if ! command -v ss >/dev/null 2>&1; then
    return 0
  fi
  if ss -ltnp "sport = :$p" 2>/dev/null | grep -q LISTEN; then
    # Si c'est encore notre catcher, rare ; sinon autre service — on n'y touche pas.
    if ss -ltnp "sport = :$p" 2>/dev/null | grep -qE 'rts_catcher|run-ultimate'; then
      echo "Port :$p encore tenu par le catcher (relance stop)"
      ss -ltnp "sport = :$p" 2>/dev/null | grep LISTEN || true
    else
      echo "Port :$p occupé par un autre service (OK — choisis un autre CATCHER_*_PORT) :"
      ss -ltnp "sport = :$p" 2>/dev/null | grep LISTEN || true
    fi
  else
    echo "Port :$p libre"
  fi
}

_check_port "$HTTP_PORT"
[ "$HTTPS_PORT" != "$HTTP_PORT" ] && _check_port "$HTTPS_PORT"

echo "OK — relance: sudo sh go-vps.sh"
