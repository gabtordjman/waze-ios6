#!/bin/sh
# Depuis la racine du repo sur le T480 :
#   sh scripts/patch-iphone.sh              → 192.168.1.60 (4S)
#   sh scripts/patch-iphone.sh 192.168.1.61 → autre iPhone

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PHONE="${1:-192.168.1.60}"
PATCH="$ROOT/scripts/waze-patch.sh"

[ -f "$PATCH" ] || { echo "missing $PATCH"; exit 1; }

SSH_OPTS="-o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa -o StrictHostKeyChecking=accept-new"
KH="${HOME}/.ssh/known_hosts"
[ -f /root/.ssh/known_hosts ] && [ "$(id -u)" = 0 ] && KH=/root/.ssh/known_hosts

echo "=== Patch Waze sur $PHONE ==="
echo "Retire l'ancienne clé SSH (restore / rejailbreak)…"
ssh-keygen -f "$KH" -R "$PHONE" 2>/dev/null || true

sed 's/\r$//' "$PATCH" | ssh $SSH_OPTS "root@${PHONE}" "cat > /tmp/waze-patch.sh && sh /tmp/waze-patch.sh"
