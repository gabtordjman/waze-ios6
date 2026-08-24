#!/bin/sh
# Tourne SUR l'iPhone. Affiche (et cree au besoin) le dossier des cartes Waze.
#
# Cote source GPL (unix/roadmap_path.c) la liste "maps" vaut, sur iPhone :
#     roadmap_path_cache()  + "/maps"   <- prefere, c'est la qu'ecrit le
#                                          telechargement de region
#     roadmap_path_bundle() + "/maps"   <- repli, livre avec l'app
# On ne devine pas leur valeur : on cherche les dossiers reels sur l'appareil.

APP=""
for d in /var/mobile/Applications/* /var/mobile/Containers/Bundle/Application/* \
         /var/containers/Bundle/Application/*; do
  [ -d "$d" ] || continue
  if [ -d "$d/Waze.app" ]; then APP="$d"; break; fi
done

if [ -z "$APP" ]; then
  echo "ERREUR: Waze.app introuvable" >&2
  exit 1
fi

# Conteneur de donnees : identique au bundle avant iOS 8, separe ensuite.
DATA="$APP"
if [ ! -d "$APP/Library" ]; then
  for d in /var/mobile/Containers/Data/Application/*; do
    [ -d "$d/Library" ] || continue
    if [ -d "$d/Documents/waze" ] || [ -d "$d/Library/Caches/maps" ]; then
      DATA="$d"; break
    fi
  done
fi

# Un dossier maps deja present fait foi : c'est celui que l'app utilise.
for c in "$DATA/Library/Caches/maps" "$DATA/Documents/maps" \
         "$DATA/Library/Application Support/maps" "$APP/Waze.app/maps"; do
  if [ -d "$c" ]; then echo "$c"; exit 0; fi
done

# Sinon on cree l'emplacement prefere (cache).
mkdir -p "$DATA/Library/Caches/maps" 2>/dev/null
if [ -d "$DATA/Library/Caches/maps" ]; then
  echo "$DATA/Library/Caches/maps"
  exit 0
fi

echo "ERREUR: impossible de creer le dossier maps sous $DATA" >&2
exit 1
