#!/usr/bin/env bash
# Voir TOUT le trafic TCP de l'iPhone (pas seulement vers le PC).
set -euo pipefail
PHONE="${1:-192.168.1.60}"
echo "Watch TOUT tcp depuis $PHONE (toutes destinations). Ouvre Waze."
echo "Ctrl+C pour stop"
exec tcpdump -n -i any "host $PHONE and tcp" -tttt -c 120
