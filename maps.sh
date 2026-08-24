#!/bin/sh
# Cartes Waze sur l'iPhone.
#
#   sh maps.sh <region> [IP]   envoie map<fips>.wzm + <fips>_index.wdf
#   sh maps.sh --clean [IP]    retire les cartes (Waze redemarre sans carte)
#   sh maps.sh --log [IP]      recupere le journal Waze et les rapports de crash
#
# Les deux fichiers d'une carte partent toujours ensemble : roadmap_locator_open
# ouvre l'index avant le paquet. Le dossier cible est decouvert sur l'appareil
# (scripts/waze-maps-dir.sh), pas devine : le chemin du bundle change a chaque
# installation.
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

REGION="$1"
PHONE="${2:-192.168.1.60}"

if [ -z "$REGION" ]; then
  echo "Usage: sh maps.sh <region> [IP]"
  echo "       sh maps.sh --clean [IP]    retire les cartes du telephone"
  echo "       sh maps.sh --log [IP]      recupere journal et rapports de crash"
  echo
  echo "Regions disponibles dans maps/ :"
  ls -1 maps 2>/dev/null | sed 's/^/  /' || echo "  (aucune)"
  exit 1
fi

sed -i 's/\r$//' scripts/waze-maps-dir.sh 2>/dev/null || true

# ControlMaster : une seule ouverture de session, donc un seul mot de passe
# pour toutes les commandes qui suivent.
SSH_OPTS="-o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa -o StrictHostKeyChecking=accept-new -o ControlMaster=auto -o ControlPath=/tmp/waze-ssh-%r@%h-%p -o ControlPersist=120"
KH="$HOME/.ssh/known_hosts"
[ "$(id -u)" = "0" ] && [ -f /root/.ssh/known_hosts ] && KH=/root/.ssh/known_hosts
ssh-keygen -f "$KH" -R "$PHONE" 2>/dev/null || true

find_dest() {
  sed 's/\r$//' scripts/waze-maps-dir.sh \
    | ssh $SSH_OPTS "root@${PHONE}" "cat > /tmp/waze-maps-dir.sh && sh /tmp/waze-maps-dir.sh"
}

# ── Retirer les cartes ───────────────────────────────────────────────────────
# Sans index, roadmap_locator_open rend ROADMAP_US_NOMAP et l'app se comporte
# comme avant la copie. C'est le moyen de la faire redemarrer si la carte la
# fait planter.
if [ "$REGION" = "--clean" ]; then
  DEST="$(find_dest)"
  [ -z "$DEST" ] && { echo "ERREUR: bundle Waze introuvable sur $PHONE."; exit 1; }
  echo "Nettoyage de $DEST"
  ssh $SSH_OPTS "root@${PHONE}" \
    "killall -9 Waze waze 2>/dev/null; rm -f '$DEST'/*.wzm '$DEST'/*_index.wdf '$DEST'/city_index; ls -l '$DEST'"
  echo
  echo "OK. Waze devrait se relancer normalement, sans carte."
  exit 0
fi

# ── Journal et rapports de crash ─────────────────────────────────────────────
# roadmap_log.c ecrit dans roadmap_path_user()/postmortem ; iOS depose ses
# rapports dans Library/Logs/CrashReporter.
if [ "$REGION" = "--log" ]; then
  mkdir -p logs/phone
  # roadmap_log.c ecrit dans roadmap_path_user(), dont la valeur reelle depend
  # de HOME au lancement. On cherche le fichier au lieu de deviner le dossier.
  echo "=== Journal Waze (postmortem) ==="
  ssh $SSH_OPTS "root@${PHONE}" \
    'find /var/mobile /var/root /private/var/mobile -maxdepth 4 \
          \( -name postmortem -o -name "waze_log.txt" \) 2>/dev/null \
     | while read f; do echo "--- $f"; tail -n 120 "$f"; done' \
    | tee logs/phone/postmortem.txt

  echo
  echo "=== Rapports de crash iOS ==="
  ssh $SSH_OPTS "root@${PHONE}" \
    'ls -1t /var/mobile/Library/Logs/CrashReporter/*aze* \
            /var/logs/CrashReporter/*aze* 2>/dev/null | head -n 2 \
     | while read f; do echo "--- $f"; head -n 60 "$f"; done' \
    | tee logs/phone/crash.txt

  # roadmap_db_open supprime lui-meme un fichier qu'il juge mal forme
  # (roadmap_tile_remove). Un index disparu accuse le format ; un index encore
  # la innocente le format et accuse la suite.
  echo
  echo "=== Etat du dossier des cartes ==="
  DEST="$(find_dest)"
  [ -n "$DEST" ] && ssh $SSH_OPTS "root@${PHONE}" "ls -l '$DEST'"

  echo
  echo "Copies dans logs/phone/. Colle-les moi."
  exit 0
fi

# ── Envoi d'une carte ────────────────────────────────────────────────────────
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

IDX="$(ls -1 "$SRC"/*_index.wdf 2>/dev/null | head -n 1)"
if [ -z "$IDX" ]; then
  echo "ERREUR: aucun *_index.wdf dans $SRC"
  echo "Regenere la carte, l'index est produit avec le paquet :"
  echo "  python3 scripts/wazemap.py build --bbox O,S,E,N --name $REGION"
  exit 1
fi

echo "=== Envoi de $(basename "$WZM") ($(du -h "$WZM" | cut -f1))"
echo "         et $(basename "$IDX") vers $PHONE ==="

DEST="$(find_dest)"

if [ -z "$DEST" ]; then
  echo
  echo "ERREUR: pas de bundle Waze sur $PHONE (details ci-dessus)."
  echo "Si Waze est sur l'autre telephone :  sh maps.sh $REGION <IP>"
  exit 1
fi
echo "Dossier cible: $DEST"

# city_index est un cache construit par l'app a partir de l'ancienne carte.
# Le laisser en place apres avoir change de carte n'a pas de sens.
ssh $SSH_OPTS "root@${PHONE}" "killall -9 Waze waze 2>/dev/null; rm -f '$DEST/city_index'"

scp $SSH_OPTS "$WZM" "$IDX" "root@${PHONE}:${DEST}/" || exit 1

ssh $SSH_OPTS "root@${PHONE}" "ls -l '$DEST'"

echo
echo "OK. Relance Waze sur le telephone."
echo "Si Waze plante :  sh maps.sh --log $PHONE   puis   sh maps.sh --clean $PHONE"
