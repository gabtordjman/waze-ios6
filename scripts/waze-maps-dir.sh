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
# c'est-a-dire le dossier Waze.app lui-meme.

APP=""
for d in /var/mobile/Applications/* /var/mobile/Containers/Bundle/Application/* \
         /var/containers/Bundle/Application/*; do
  [ -d "$d/Waze.app" ] || continue
  APP="$d/Waze.app"
  break
done

if [ -z "$APP" ]; then
  echo "ERREUR: Waze.app introuvable" >&2
  exit 1
fi

mkdir -p "$APP/maps" 2>/dev/null

if [ ! -d "$APP/maps" ]; then
  echo "ERREUR: impossible de creer $APP/maps" >&2
  exit 1
fi

echo "$APP/maps"
