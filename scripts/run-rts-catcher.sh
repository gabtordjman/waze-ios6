#!/usr/bin/env bash
# Catcher RTS — par défaut délègue à l'essai ultime (tcpdump + gzip no-CL).
# Legacy sans capture: ./scripts/run-rts-catcher.sh --legacy
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ "${1:-}" != "--legacy" ]]; then
  exec "$ROOT/scripts/run-ultimate.sh"
fi

cd "$ROOT"
mkdir -p "$ROOT/logs"

DID_STOP_APACHE=0
cleanup() {
  if [[ "$DID_STOP_APACHE" == "1" ]]; then
    systemctl start apache2 2>/dev/null || service apache2 start 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "=== Legacy catcher (sans tcpdump) ==="
if ss -tln | grep -q ':80 '; then
  if ss -tlnp 2>/dev/null | grep ':80 ' | grep -q apache; then
    systemctl stop apache2 2>/dev/null || service apache2 stop 2>/dev/null || true
    DID_STOP_APACHE=1
    sleep 1
  fi
fi
if ss -tln | grep -q ':443 '; then
  echo "ERREUR: :443 déjà pris"
  exit 1
fi

export CATCHER_HTTP_PORT=80
export CATCHER_HTTPS_PORT=443
export CATCHER_MODE="${CATCHER_MODE:-plain_cl}"
export CATCHER_BODY="${CATCHER_BODY:-geo}"
export CATCHER_CTYPE="${CATCHER_CTYPE:-application/x-www-form-urlencoded; charset=utf-8}"
export OPENSSL_CONF="$ROOT/mitm/certs/tls/openssl-ios6.cnf"

PYTHON=python3
[[ -x "$ROOT/.venv/bin/python" ]] && PYTHON="$ROOT/.venv/bin/python"
exec "$PYTHON" "$ROOT/scripts/rts_catcher_min.py"
