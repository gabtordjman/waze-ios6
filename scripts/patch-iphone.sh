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

echo "=== Patch Waze sur $PHONE ==="
ssh-keygen -f "$KH" -R "$PHONE" 2>/dev/null || true

sed 's/\r$//' "$PATCH" | ssh $SSH_OPTS "root@${PHONE}" "cat > /tmp/waze-patch.sh && sh /tmp/waze-patch.sh"
