#!/bin/sh
# Lance le catcher en mode VPS public (sans dnsmasq / DNAT / tcpdump).
#
#   cp .env.example .env   # une fois
#   nano .env              # WAZE_SERVER_IP=…
#   sudo sh go-vps.sh
#
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

export WAZE_MODE="${WAZE_MODE:-vps}"
export SKIP_DNS="${SKIP_DNS:-1}"
export SKIP_DNAT="${SKIP_DNAT:-1}"
export SKIP_TCPDUMP="${SKIP_TCPDUMP:-1}"

if [ -z "$WAZE_SERVER_IP" ] && [ -z "$PC_IP" ]; then
  WAZE_SERVER_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  export WAZE_SERVER_IP
fi
export PC_IP="${PC_IP:-$WAZE_SERVER_IP}"

for f in go-vps.sh stop.sh scripts/*.sh scripts/*.py; do
  [ -f "$f" ] && sed -i 's/\r$//' "$f" 2>/dev/null
done

LOCK="/tmp/waze-ios6-catcher.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "ERREUR: catcher déjà lancé. sh stop.sh"
  exit 1
fi

sh "$ROOT/stop.sh" 2>/dev/null || true
echo "=== Waze iOS6 catcher (mode VPS) ==="
echo "WAZE_SERVER_IP=${WAZE_SERVER_IP:-${PC_IP:-auto}}"

if [ "$(id -u)" -eq 0 ]; then
  exec python3 "$ROOT/scripts/run-ultimate.py"
else
  exec sudo -E python3 "$ROOT/scripts/run-ultimate.py"
fi
