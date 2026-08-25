#!/bin/sh
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONF="$ROOT/scripts/dnsmasq-waze.conf"
PIDFILE="$ROOT/logs/dnsmasq-waze.pid"
LOG="$ROOT/logs/dnsmasq-waze.log"
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
IP="${IP:-$(python3 -c 'import sys; sys.path.insert(0,"scripts"); from waze_env import server_ip; print(server_ip())' 2>/dev/null || echo 192.168.1.191)}"
mkdir -p "$ROOT/logs"

cat > "$CONF" <<EOF
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
address=/tiles.waze.com/${IP}
address=/tiles1.waze.com/${IP}
address=/tiles2.waze.com/${IP}
address=/tiles3.waze.com/${IP}
address=/tiles4.waze.com/${IP}
address=/tilesworld1.waze.com/${IP}
log-queries
log-facility=${LOG}
EOF

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "dnsmasq deja actif pid $(cat "$PIDFILE")"
else
  : > "$LOG"
  dnsmasq --conf-file="$CONF" --pid-file="$PIDFILE" 2>/dev/null || echo "dnsmasq skip (deja ou absent)"
fi

echo "DNS iPhone -> ${IP}"
