#!/usr/bin/env bash
# Sur l'iPhone jailbreaké, redirige Download.* vers le PC catcher.
# Usage: ./scripts/patch-phone-download-urls.sh [user@iphone] [PC_IP]
#
# Debian/OpenSSH récents ont RETIRÉ ssh-rsa → "Bad key types".
# On tente: ssh legacy → dbclient → docker openssh ancien → consignes MobileTerminal.
set -euo pipefail
HOST="${1:-root@192.168.1.60}"
PC_IP="${2:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
PC_IP="${PC_IP:-192.168.1.191}"
PHONE_IP="${HOST#*@}"
PHONE_USER="${HOST%%@*}"

REMOTE_SCRIPT=$(cat <<REMOTE
set -e
OLD="http://75.101.158.200"
NEW="http://${PC_IP}"
FOUND=\$(find /var/mobile /Applications /var/containers -name preferences 2>/dev/null | head -40 || true)
if [ -z "\$FOUND" ]; then
  echo "Aucun fichier preferences trouvé"
  exit 1
fi
echo "\$FOUND" | while read -r f; do
  if grep -q "75.101.158.200" "\$f" 2>/dev/null; then
    cp -a "\$f" "\$f.bak-wazeios6"
    sed -i "s|\${OLD}|\${NEW}|g" "\$f"
    echo "patched: \$f"
    grep "^Download\." "\$f" || true
  fi
done
echo "OK — killall -9 Waze puis relance"
REMOTE
)

echo "Cible $HOST — remplace 75.101.158.200 → http://$PC_IP"
echo

run_remote() {
  local how="$1"
  shift
  echo "→ tentative: $how"
  if "$@" "sh -s" <<<"$REMOTE_SCRIPT"; then
    echo "OK via $how"
    return 0
  fi
  return 1
}

# 1) OpenSSH si le build accepte encore ssh-rsa (rares)
if ssh -V 2>&1 | grep -qi openssh; then
  if ssh -o BatchMode=yes -o ConnectTimeout=3 \
      -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
      -o HostKeyAlgorithms=ssh-rsa \
      "$HOST" true 2>/dev/null; then
    run_remote "ssh local" ssh \
      -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
      -o HostKeyAlgorithms=ssh-rsa \
      "$HOST" && exit 0
  fi
fi

# 2) Docker + OpenSSH 8.x (Ubuntu 20.04) — marche avec iOS 6 Dropbear
if command -v docker >/dev/null 2>&1; then
  echo "→ tentative: docker ubuntu:20.04 openssh-client"
  if docker run --rm --network host ubuntu:20.04 \
      bash -c "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openssh-client >/dev/null && ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o HostKeyAlgorithms=ssh-rsa,ssh-dss -o PubkeyAcceptedKeyTypes=ssh-rsa,ssh-dss -o KexAlgorithms=diffie-hellman-group1-sha1,diffie-hellman-group14-sha1 -o Ciphers=aes128-cbc,3des-cbc ${HOST} 'sh -s'" <<<"$REMOTE_SCRIPT"
  then
    echo "OK via docker"
    exit 0
  fi
fi

cat <<EOF

Échec SSH depuis ce PC (OpenSSH Trixie n'a plus ssh-rsa).

=== Option A — MobileTerminal SUR le téléphone (le plus simple) ===
En root (su), colle :

find /var/mobile/Applications -name preferences 2>/dev/null
# puis pour CHAQUE chemin affiché qui contient waze / 75.101 :
sed -i 's|http://75.101.158.200|http://${PC_IP}|g' CHEMIN
grep Download.Config CHEMIN
killall -9 Waze

=== Option B — Docker (sur le PC) ===
docker run --rm -it --network host ubuntu:20.04 bash
apt update && apt install -y openssh-client
ssh -o HostKeyAlgorithms=ssh-rsa,ssh-dss \\
    -o PubkeyAcceptedKeyTypes=ssh-rsa,ssh-dss \\
    -o KexAlgorithms=diffie-hellman-group1-sha1,diffie-hellman-group14-sha1 \\
    -o Ciphers=aes128-cbc,3des-cbc \\
    ${PHONE_USER}@${PHONE_IP}

Puis relance: ./patch-phone-download-urls.sh ${HOST} ${PC_IP}

EOF
exit 1
