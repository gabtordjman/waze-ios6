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
fi
# Ne JAMAIS --force Overpass ici : une carte vide/hors GPS = écran néant.
# La carte déjà dans maps/auto/ (96e7e67 ou dernier build réussi) est celle qu'on envoie.

if [ -f "$INDEX" ]; then
  scp $SSH_OPTS "$INDEX" "root@${PHONE}:/tmp/77001_index.wdf"
else
  echo "AVERTISSEMENT: $INDEX absent"
fi

if [ -f "$WZM" ]; then
  SZ=$(wc -c < "$WZM" | tr -d ' ')
  if [ "${SZ:-0}" -lt 20000 ]; then
    echo "ERREUR: $WZM trop petit (${SZ} o) — carte vide, Waze afficherait un néant."
    echo "Garde maps/auto/ existant, ou: python3 scripts/map_auto.py build --lon LON --lat LAT"
    exit 1
  fi
  echo "Envoi carte $(du -h "$WZM" | cut -f1)…"
  GPS_ARGS=""
  if [ -f "$ROOT/logs/rts-catcher.txt" ]; then
    GPS_ARGS=$(
      cd "$ROOT" && python3 -c "
import sys
sys.path.insert(0, 'scripts')
from map_auto import coords_from_log
p = coords_from_log()
if p:
    print('--lon', p[0], '--lat', p[1])
" 2>/dev/null || true
    )
  fi
  python3 "$ROOT/scripts/wazemap.py" inspect "$WZM" $GPS_ARGS || {
    echo "ERREUR: carte sans rues au zoom rue / GPS hors carte — ne pas l'envoyer."
    echo "Reconstruire autour du GPS :"
    echo "  python3 scripts/map_auto.py build --lon 6.4847 --lat 46.3646 --force"
    exit 1
  }
  scp $SSH_OPTS "$WZM" "root@${PHONE}:/tmp/map77001.wzm"
else
  echo "ERREUR: $WZM absent — ouvre Waze (GPS) puis relance phone.sh"
  exit 1
fi

FRA_SRC="$ROOT/mitm/fake-resources/resources/sounds/1.0/fra"
ENG_SRC="$ROOT/mitm/fake-resources/resources/sounds/1.0/eng"
if [ -d "$FRA_SRC" ]; then
  echo "Envoi voix française…"
  ssh $SSH_OPTS "root@${PHONE}" "rm -rf /tmp/waze-sound-fra; mkdir -p /tmp/waze-sound-fra"
  scp $SSH_OPTS "$FRA_SRC"/* "root@${PHONE}:/tmp/waze-sound-fra/"
fi
if [ -d "$ENG_SRC" ]; then
  echo "Envoi voix anglaise…"
  ssh $SSH_OPTS "root@${PHONE}" "rm -rf /tmp/waze-sound-eng; mkdir -p /tmp/waze-sound-eng"
  scp $SSH_OPTS "$ENG_SRC"/* "root@${PHONE}:/tmp/waze-sound-eng/"
fi

PC_IP="$(cd "$ROOT" && python3 -c "import sys; sys.path.insert(0,'scripts'); from waze_env import server_ip; print(server_ip())" 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
PC_IP="${PC_IP:-192.168.1.191}"

sed 's/\r$//' "$ROOT/scripts/waze-cache-maps.sh" | ssh $SSH_OPTS "root@${PHONE}" "cat > /tmp/waze-cache-maps.sh"
sed 's/\r$//' "$PATCH" | ssh $SSH_OPTS "root@${PHONE}" "cat > /tmp/waze-patch.sh && PC='$PC_IP' sh /tmp/waze-patch.sh"
