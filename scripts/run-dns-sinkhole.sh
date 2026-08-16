#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONF="$ROOT/scripts/dnsmasq-waze.conf"
PIDFILE="$ROOT/logs/dnsmasq-waze.pid"
LOG="$ROOT/logs/dnsmasq-waze.log"
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
IP="${IP:-192.168.1.191}"
mkdir -p "$ROOT/logs"

# Rewrite conf with current IP
cat > "$CONF" <<CONF
listen-address=${IP}
bind-interfaces
port=53
no-resolv
no-hosts
server=1.1.1.1
server=8.8.8.8
filter-AAAA
address=/rt.waze.com/${IP}
address=/www.waze.com/${IP}
address=/row.waze.com/${IP}
address=/config.waze.com/${IP}
address=/desc.waze.com/${IP}
address=/rtserver.waze.com/${IP}
address=/rt-old-client/${IP}
address=/waze.com/${IP}
address=/waze-client-resources.s3.amazonaws.com/${IP}
log-queries
log-facility=${LOG}
CONF

if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "dnsmasq-waze déjà actif (pid $(cat "$PIDFILE"))"
else
  : > "$LOG"
  dnsmasq --conf-file="$CONF" --pid-file="$PIDFILE"
  echo "dnsmasq-waze démarré sur ${IP}:53"
fi

echo
echo "Sur l'iPhone : Réglages → Wi-Fi → (i) → DNS → ${IP}  (seul)"
echo "Garde aussi /etc/hosts si tu veux, mais le DNS suffit."
echo
echo "Test :"
echo "  dig @${IP} A rt.waze.com"
echo "  dig @${IP} AAAA rt.waze.com   # doit être VIDE"
dig @"${IP}" A rt.waze.com +short
echo -n "AAAA: "; dig @"${IP}" AAAA rt.waze.com +short; echo "(vide = OK)"
