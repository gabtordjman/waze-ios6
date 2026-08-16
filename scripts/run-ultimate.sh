#!/usr/bin/env bash
# Essai ultime Waze RTS : tcpdump + catcher (gzip sans Content-Length).
# Usage:
#   ./scripts/run-ultimate.sh
#   # tue Waze, rouvre, attends le DNS watch / RES
#   Ctrl+C → résumé pcap
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p "$ROOT/logs"

PHONE="${PHONE:-192.168.1.60}"
PC_IP="${PC_IP:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
PC_IP="${PC_IP:-192.168.1.191}"
IFACE="${IFACE:-}"
if [[ -z "$IFACE" ]]; then
  IFACE=$(ip route get "$PHONE" 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')
  IFACE="${IFACE:-wlp3s0}"
fi

STAMP=$(date +%Y%m%d-%H%M%S)
PCAP="$ROOT/logs/ultimate-${STAMP}.pcap"
SUMMARY="$ROOT/logs/ultimate-${STAMP}-summary.txt"

DID_STOP_APACHE=0
TCPDUMP_PID=""
cleanup() {
  if [[ -n "${TCPDUMP_PID}" ]] && kill -0 "$TCPDUMP_PID" 2>/dev/null; then
    kill -INT "$TCPDUMP_PID" 2>/dev/null || true
    wait "$TCPDUMP_PID" 2>/dev/null || true
  fi
  if [[ "$DID_STOP_APACHE" == "1" ]]; then
    systemctl start apache2 2>/dev/null || service apache2 start 2>/dev/null || true
  fi
  if [[ -f "$PCAP" ]]; then
    {
      echo "=== ultimate capture $STAMP ==="
      echo "pcap: $PCAP"
      echo
      echo "--- conversations TCP 443 ---"
      tcpdump -nn -r "$PCAP" "tcp port 443" 2>/dev/null | awk '
        /Flags/ {
          print
        }' | tail -n 80
      echo
      echo "--- compteurs ---"
      echo -n "frames total: "; tcpdump -nn -r "$PCAP" 2>/dev/null | wc -l
      echo -n "frames $PC_IP -> $PHONE :443 : "
      tcpdump -nn -r "$PCAP" "src host $PC_IP and dst host $PHONE and tcp port 443" 2>/dev/null | wc -l
      echo -n "frames $PHONE -> $PC_IP :443 : "
      tcpdump -nn -r "$PCAP" "src host $PHONE and dst host $PC_IP and tcp port 443" 2>/dev/null | wc -l
      echo -n "RST: "; tcpdump -nn -r "$PCAP" "tcp[tcpflags] & tcp-rst != 0" 2>/dev/null | wc -l
      echo -n "FIN: "; tcpdump -nn -r "$PCAP" "tcp[tcpflags] & tcp-fin != 0" 2>/dev/null | wc -l
      echo
      echo "Interprétation:"
      echo "  Beaucoup de frames PC→phone après le POST = réponse TLS bien envoyée."
      echo "  RST immédiat depuis le phone = refus/abort lecture."
      echo "  Pas de RES/DNS S3 dans rts-catcher.txt = Waze n a pas enchaîné lang.conf."
    } | tee "$SUMMARY"
    echo
    echo "Résumé: $SUMMARY"
  fi
}
trap cleanup EXIT

echo "=== Essai ultime Waze RTS ==="
echo "PC=$PC_IP  phone=$PHONE  iface=$IFACE"
echo "pcap → $PCAP"
echo
echo "Réponse: gzip CL=plain + ServerConfig Download.* → PC (v3)"
echo "Body: RC+Geo+5×ServerConfig | ctype binary/octet-stream"
echo "Pcap: host phone and (port 443 or port 80)"
echo
echo "1) Tue Waze (multitâche)"
echo "2) Rouvre Waze"
echo "3) Attends ~30s — cherche GET lang.conf sur :80"
echo "4) Ctrl+C ici pour le résumé tcpdump"
echo

# Ports
if ss -tln | grep -q ':80 '; then
  if ss -tlnp 2>/dev/null | grep ':80 ' | grep -q apache; then
    systemctl stop apache2 2>/dev/null || service apache2 stop 2>/dev/null || true
    DID_STOP_APACHE=1
    sleep 1
  else
    echo "ATTENTION: :80 déjà pris — arrête l'ancien catcher (Ctrl+C ailleurs)"
    ss -tlnp | grep -E ':80|:443' || true
  fi
fi
if ss -tln | grep -q ':443 '; then
  echo "ERREUR: :443 déjà pris"
  ss -tlnp | grep ':443 ' || true
  exit 1
fi

# Capture HTTPS login + HTTP lang downloads
tcpdump -i "$IFACE" -s 0 -w "$PCAP" \
  "host $PHONE and (port 443 or port 80)" \
  >/dev/null 2>&1 &
TCPDUMP_PID=$!
sleep 0.3
if ! kill -0 "$TCPDUMP_PID" 2>/dev/null; then
  echo "ERREUR tcpdump (essaie: sudo ou IFACE=...)"
  TCPDUMP_PID=""
  exit 1
fi
echo "tcpdump pid=$TCPDUMP_PID"

export CATCHER_HTTP_PORT=80
export CATCHER_HTTPS_PORT=443
export CATCHER_MODE=plain_cl
export CATCHER_BODY=double_rc
export CATCHER_CTYPE="binary/octet-stream"
export CATCHER_DRAIN_SEC=0.3
export PC_IP="$PC_IP"
export OPENSSL_CONF="$ROOT/mitm/certs/tls/openssl-ios6.cnf"

# Prefer project venv python if present
PYTHON=python3
[[ -x "$ROOT/.venv/bin/python" ]] && PYTHON="$ROOT/.venv/bin/python"

echo "catcher mode=ultimate v3 (Geo+ServerConfig → $PC_IP)"
echo
exec "$PYTHON" "$ROOT/scripts/rts_catcher_min.py"
