#!/bin/sh
# Tourne SUR l'iPhone. Affiche le dossier cache "maps" (roadmap_path.c : #/maps).
# L'index reste dans le bundle ; le paquet .wzm va ici en priorité.

CONTAINER="${1:-}"
if [ -z "$CONTAINER" ] || [ ! -d "$CONTAINER" ]; then
  echo "ERREUR: CONTAINER requis" >&2
  exit 1
fi

# Chemin préféré Waze iOS 6 : Library/Caches/maps
for cand in \
  "$CONTAINER/Library/Caches/maps" \
  "$CONTAINER/Library/Caches/.waze/maps" \
  "$CONTAINER/tmp/maps"
do
  base=$(dirname "$cand")
  [ -d "$base" ] || continue
  mkdir -p "$cand" 2>/dev/null || continue
  echo "$cand"
  exit 0
done

mkdir -p "$CONTAINER/Library/Caches/maps" 2>/dev/null
echo "$CONTAINER/Library/Caches/maps"
