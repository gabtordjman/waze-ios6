#!/bin/sh
# Envoie une carte sur l'iPhone :  sh maps.sh <region> [IP]
#
#   python3 scripts/wazemap.py build --bbox 6.42,46.33,6.56,46.40 --name leman
#   sh maps.sh leman
#
# Deux fichiers partent ensemble : le paquet map<fips>.wzm et son index
# <fips>_index.wdf. Le dossier cible est decouvert sur l'appareil
# (scripts/waze-maps-dir.sh), pas devine : le chemin du bundle change a chaque
# installation.
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

REGION="$1"
PHONE="${2:-192.168.1.60}"

if [ -z "$REGION" ]; then
  echo "Usage: sh maps.sh <region> [IP]"
  echo
  echo "Regions disponibles dans maps/ :"
  ls -1 maps 2>/dev/null | sed 's/^/  /' || echo "  (aucune)"
  exit 1
fi

SRC="$ROOT/maps/$REGION"
if [ ! -d "$SRC" ]; then
  echo "ERREUR: $SRC introuvable."
  echo "Genere-la d'abord :"
  echo "  python3 scripts/wazemap.py build --bbox O,S,E,N --name $REGION"
  exit 1
fi

WZM="$(ls -1 "$SRC"/*.wzm 2>/dev/null | head -n 1)"
if [ -z "$WZM" ]; then
  echo "ERREUR: aucun .wzm dans $SRC"
  exit 1
fi

# L'index part avec le paquet. roadmap_locator_open ouvre <fips>_index.wdf
# avant de toucher au .wzm : sans lui la carte reste invisible, sans erreur.
IDX="$(ls -1 "$SRC"/*_index.wdf 2>/dev/null | head -n 1)"
if [ -z "$IDX" ]; then
  echo "ERREUR: aucun *_index.wdf dans $SRC"
  echo "Regenere la carte, l'index est produit avec le paquet :"
  echo "  python3 scripts/wazemap.py build --bbox O,S,E,N --name $REGION"
  exit 1
fi

sed -i 's/\r$//' scripts/waze-maps-dir.sh 2>/dev/null || true

# ControlMaster : une seule ouverture de session, donc un seul mot de passe
# pour les trois commandes qui suivent au lieu de trois.
SSH_OPTS="-o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa -o StrictHostKeyChecking=accept-new -o ControlMaster=auto -o ControlPath=/tmp/waze-ssh-%r@%h-%p -o ControlPersist=120"
KH="$HOME/.ssh/known_hosts"
[ "$(id -u)" = "0" ] && [ -f /root/.ssh/known_hosts ] && KH=/root/.ssh/known_hosts
ssh-keygen -f "$KH" -R "$PHONE" 2>/dev/null || true

echo "=== Envoi de $(basename "$WZM") ($(du -h "$WZM" | cut -f1))"
echo "         et $(basename "$IDX") vers $PHONE ==="

DEST="$(sed 's/\r$//' scripts/waze-maps-dir.sh \
  | ssh $SSH_OPTS "root@${PHONE}" "cat > /tmp/waze-maps-dir.sh && sh /tmp/waze-maps-dir.sh")"

if [ -z "$DEST" ]; then
  echo
  echo "ERREUR: pas de bundle Waze sur $PHONE (details ci-dessus)."
  echo "Si Waze est sur l'autre telephone :  sh maps.sh $REGION <IP>"
  exit 1
fi
echo "Dossier cible: $DEST"

scp $SSH_OPTS "$WZM" "$IDX" "root@${PHONE}:${DEST}/" || exit 1

ssh $SSH_OPTS "root@${PHONE}" "ls -l '$DEST'"

echo
echo "OK. Relance Waze sur le telephone."
