#!/bin/sh
# Depuis la racine :  sh scripts/patch-iphone.sh [IP]
# Defaut IP = 192.168.1.60 (4S)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PHONE="${1:-192.168.1.60}"
PATCH="$ROOT/scripts/waze-patch.sh"

if [ ! -f "$PATCH" ]; then
  echo "missing $PATCH"
  exit 1
fi

sed -i 's/\r$//' "$PATCH" 2>/dev/null || true

SSH_OPTS="-o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa -o StrictHostKeyChecking=accept-new"
KH="$HOME/.ssh/known_hosts"
if [ -f /root/.ssh/known_hosts ] && [ "$(id -u)" = "0" ]; then
  KH=/root/.ssh/known_hosts
fi

MAP_REGION="${WAZE_MAP:-auto}"
INDEX="$ROOT/maps/$MAP_REGION/77001_index.wdf"
[ ! -f "$INDEX" ] && INDEX="$ROOT/packages/maps/77001_index.wdf"
WZM="$ROOT/maps/$MAP_REGION/map77001.wzm"

echo "=== Patch Waze sur $PHONE (carte: $MAP_REGION) ==="
ssh-keygen -f "$KH" -R "$PHONE" 2>/dev/null || true

SSH_OPTS="$SSH_OPTS -o ControlMaster=auto -o ControlPath=/tmp/waze-ssh-%r@%h-%p -o ControlPersist=120"

if [ "$MAP_REGION" = "minimal" ]; then
  python3 "$ROOT/scripts/wazemap.py" build-minimal --lon 6.484687 --lat 46.364578 --name minimal
elif [ -f "$ROOT/logs/rts-catcher.txt" ]; then
  python3 "$ROOT/scripts/map_auto.py" ensure --from-log --force 2>/dev/null || true
fi

if [ -f "$INDEX" ]; then
  scp $SSH_OPTS "$INDEX" "root@${PHONE}:/tmp/77001_index.wdf"
else
  echo "AVERTISSEMENT: $INDEX absent"
fi

if [ -f "$WZM" ]; then
  echo "Envoi carte $(du -h "$WZM" | cut -f1)…"
  scp $SSH_OPTS "$WZM" "root@${PHONE}:/tmp/map77001.wzm"
else
  echo "ERREUR: $WZM absent — ouvre Waze (GPS) puis relance phone.sh"
  exit 1
fi

sed 's/\r$//' "$ROOT/scripts/waze-cache-maps.sh" | ssh $SSH_OPTS "root@${PHONE}" "cat > /tmp/waze-cache-maps.sh"
sed 's/\r$//' "$PATCH" | ssh $SSH_OPTS "root@${PHONE}" "cat > /tmp/waze-patch.sh && sh /tmp/waze-patch.sh"
