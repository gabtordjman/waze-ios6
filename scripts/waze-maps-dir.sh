#!/bin/sh
# Tourne SUR l'iPhone. Affiche (et cree au besoin) le dossier des cartes Waze.
#
# On vise le dossier "maps" du bundle, et pas un autre, parce que la source GPL
# ne laisse pas le choix :
#
#   roadmap_dbread.c    roadmap_db_map_path() vaut, sous IPHONE,
#                       roadmap_main_bundle_path() + "/maps". C'est la seule
#                       place ou roadmap_locator_open va chercher le fichier
#                       d'index <fips>_index.wdf, et sans cet index la carte
#                       n'est jamais ouverte.
#   unix/roadmap_path.c la liste "maps" vaut ["<cache>/maps", "<bundle>/maps"],
#                       donc le paquet map<fips>.wzm y est trouve aussi.
#
# Un seul dossier suffit donc pour les deux fichiers.
# roadmap_main_bundle_path() renvoie [[NSBundle mainBundle] resourcePath],
# c'est-a-dire le dossier .app lui-meme.
#
# Le nom du bundle n'est pas garanti : selon l'IPA c'est Waze.app, waze.app,
# ou autre chose. On accepte donc toute casse, et a defaut tout .app qui
# contient un binaire waze.

BASES="/var/mobile/Applications
/var/mobile/Containers/Bundle/Application
/var/containers/Bundle/Application
/Applications"

APP=""
FOUND=""

for base in $BASES; do
  [ -d "$base" ] || continue
  for app in "$base"/*.app "$base"/*/*.app; do
    [ -d "$app" ] || continue
    FOUND="$FOUND
  $app"
    [ -n "$APP" ] && continue
    name=$(basename "$app")
    case "$name" in
      [Ww][Aa][Zz][Ee]*) APP="$app" ;;
      *) [ -f "$app/waze" ] || [ -f "$app/Waze" ] && APP="$app" ;;
    esac
  done
done

if [ -z "$APP" ]; then
  echo "ERREUR: aucun bundle Waze trouve." >&2
  if [ -n "$FOUND" ]; then
    echo "Applications reperees :$FOUND" >&2
  else
    echo "Aucun .app sous :" >&2
    for base in $BASES; do echo "  $base" >&2; done
  fi
  exit 1
fi

mkdir -p "$APP/maps" 2>/dev/null

if [ ! -d "$APP/maps" ]; then
  echo "ERREUR: impossible de creer $APP/maps" >&2
  exit 1
fi

echo "$APP/maps"
