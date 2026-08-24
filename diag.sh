#!/bin/sh
# Diagnostic Waze depuis le PC :  sh diag.sh  [IP]
# Envoie waze-diag.sh sur l'iPhone, l'execute, et enregistre la sortie.
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1
PHONE="${1:-192.168.1.60}"
OUT="$ROOT/logs/phone-diag.txt"
mkdir -p "$ROOT/logs"

sed -i 's/\r$//' scripts/waze-diag.sh 2>/dev/null || true

SSH_OPTS="-o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa -o StrictHostKeyChecking=accept-new"
KH="$HOME/.ssh/known_hosts"
[ "$(id -u)" = "0" ] && [ -f /root/.ssh/known_hosts ] && KH=/root/.ssh/known_hosts
ssh-keygen -f "$KH" -R "$PHONE" 2>/dev/null || true

echo "=== Diagnostic Waze sur $PHONE ==="
sed 's/\r$//' scripts/waze-diag.sh \
  | ssh $SSH_OPTS "root@${PHONE}" "cat > /tmp/waze-diag.sh && sh /tmp/waze-diag.sh" \
  | tee "$OUT"

echo
echo "Enregistre dans: $OUT"
