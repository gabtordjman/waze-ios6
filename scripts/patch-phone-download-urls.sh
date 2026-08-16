#!/usr/bin/env bash
# Sur l'iPhone jailbreaké (SSH), redirige Download.* vers le PC catcher.
# Usage: ./scripts/patch-phone-download-urls.sh [user@iphone] [PC_IP]
set -euo pipefail
HOST="${1:-root@192.168.1.60}"
PC_IP="${2:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
PC_IP="${PC_IP:-192.168.1.191}"

echo "SSH $HOST — remplace 75.101.158.200 → http://$PC_IP"
ssh -o StrictHostKeyChecking=no "$HOST" "PC_IP='$PC_IP' bash -s" <<'REMOTE'
set -e
OLD="http://75.101.158.200"
NEW="http://${PC_IP}"
FOUND=$(find /var/mobile /Applications /var/containers -name preferences 2>/dev/null | head -40 || true)
if [[ -z "$FOUND" ]]; then
  echo "Aucun fichier preferences trouvé"
  exit 1
fi
echo "$FOUND" | while read -r f; do
  if grep -q "75.101.158.200" "$f" 2>/dev/null; then
    cp -a "$f" "$f.bak-wazeios6"
    sed -i "s|${OLD}|${NEW}|g" "$f"
    echo "patched: $f"
    grep "^Download\." "$f" || true
  fi
done
if command -v iptables >/dev/null 2>&1; then
  iptables -t nat -C OUTPUT -d 75.101.158.200 -p tcp --dport 80 -j DNAT --to-destination "${PC_IP}:80" 2>/dev/null \
    || iptables -t nat -A OUTPUT -d 75.101.158.200 -p tcp --dport 80 -j DNAT --to-destination "${PC_IP}:80"
  echo "iptables DNAT 75.101.158.200:80 → ${PC_IP}:80"
fi
echo "OK — killall -9 Waze puis relance"
REMOTE
