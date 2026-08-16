#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
fi

mkdir -p "$ROOT/logs"

echo "Proxy HTTP  : 0.0.0.0:8080"
echo "UI mitmweb  : http://127.0.0.1:8081"
echo "Addon       : mitm/addon_waze.py"
echo "Summary     : logs/summary.txt"
echo "Flows dump  : logs/flows.mitm"
echo
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "Sur l'iPhone :"
echo "  1) Proxy Wi-Fi = ${IP:-IP_DU_PC}:8080"
echo "  2) Safari → http://cert.ios6/  (installe le profil)"
echo "  3) Test https://www.apple.com puis ouvre Waze"
echo

exec mitmweb \
  --listen-host 0.0.0.0 \
  --listen-port 8080 \
  --web-host 127.0.0.1 \
  --web-port 8081 \
  -s "$ROOT/mitm/addon_waze.py" \
  --set console_eventlog_verbosity=info \
  --set connection_strategy=lazy \
  --save-stream-file "$ROOT/logs/flows.mitm"
