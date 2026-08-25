#!/bin/sh
# Patch Waze 2.4 / 3.9 — iPhone 4 / 4S (détecte Waze.app ou waze.app).
# Sur le téléphone :  sh /tmp/waze-patch.sh
# Depuis le PC      :  sh phone.sh [IP]

PC="${PC:-192.168.1.191}"

find_bundle() {
  for base in \
    /var/mobile/Applications \
    /var/mobile/Containers/Bundle/Application \
    /var/containers/Bundle/Application \
    /Applications
  do
    [ -d "$base" ] || continue
    for app in "$base"/*.app "$base"/*/*.app; do
      [ -d "$app" ] || continue
      name=$(basename "$app")
      case "$name" in
        [Ww][Aa][Zz][Ee]*)
          echo "$app"
          return 0
          ;;
      esac
      if [ -f "$app/waze" ] || [ -f "$app/Waze" ]; then
        echo "$app"
        return 0
      fi
    done
  done
  return 1
}

if [ -n "$APP" ] && [ -d "$APP/Waze.app" ]; then
  BUNDLE_DIR="$APP/Waze.app"
  CONTAINER="$APP"
elif [ -n "$APP" ] && [ -d "$APP/waze.app" ]; then
  BUNDLE_DIR="$APP/waze.app"
  CONTAINER="$APP"
else
  BUNDLE_DIR=$(find_bundle) || true
  if [ -n "$BUNDLE_DIR" ]; then
    CONTAINER=$(dirname "$BUNDLE_DIR")
  fi
fi

[ -n "$BUNDLE_DIR" ] && [ -d "$BUNDLE_DIR" ] || {
  echo "FAIL: bundle Waze introuvable. Liste:"
  ls /var/mobile/Applications/ 2>/dev/null
  exit 1
}

if [ -f "$BUNDLE_DIR/waze" ]; then
  BIN="$BUNDLE_DIR/waze"
elif [ -f "$BUNDLE_DIR/Waze" ]; then
  BIN="$BUNDLE_DIR/Waze"
else
  BIN=""
fi

echo "=== Waze patch ==="
echo "BUNDLE=$BUNDLE_DIR"
echo "PC=$PC"

PREF="$CONTAINER/Documents/preferences"
BUNDLE="$BUNDLE_DIR/preferences"
USERF="$CONTAINER/Documents/user"
BUNDLE_MAPS="$BUNDLE_DIR/maps"

killall -9 Waze waze 2>/dev/null

[ -f "$BUNDLE" ] || { echo "FAIL: pas de bundle preferences"; exit 1; }
[ -f "$PREF" ] || cp "$BUNDLE" "$PREF"

grep -q 'rt.waze.com' /etc/hosts 2>/dev/null || echo "$PC rt.waze.com" >> /etc/hosts
grep -q 'www.waze.com' /etc/hosts 2>/dev/null || echo "$PC www.waze.com" >> /etc/hosts
grep -q '[[:space:]]waze.com' /etc/hosts 2>/dev/null || echo "$PC waze.com" >> /etc/hosts

grep -v '^System.ServerId:' "$PREF" | \
grep -v '^GeoConfig.version:' | \
grep -v '^GeoConfig.Web-Service Address:' | \
grep -v '^Realtime.Web-Service Address:' | \
grep -v '^Realtime.Web-Service Secured Address:' | \
grep -v '^Realtime.Web-Service Secured Address Resolved:' | \
grep -v '^Realtime.Web-Service Secure Enabled' | \
grep -v '^Realtime.Web-Service Secured Commands:' | \
grep -v '^Realtime.Web-Service V2 Suffix:' | \
grep -v '^Realtime.Web-Service V2 Commands:' | \
grep -v '^Realtime.Status:' | \
grep -v '^Realtime.Auto registration:' | \
grep -v '^Realtime.Name:' | \
grep -v '^Realtime.Password:' | \
grep -v '^Realtime.Nickname:' | \
grep -v '^Download.Tiles:' | \
grep -v '^Download.Config:' | \
grep -v '^Download.Langs:' | \
grep -v '^Download.Images:' | \
grep -v '^Download.Sound:' | \
grep -v '^Download.Langs TTS:' | \
grep -v '^Download.Source:' | \
grep -v '^Download.Enabled:' | \
grep -v '^Download.Map name:' | \
grep -v '^TTS.Feature Enabled:' | \
grep -v '^Navigation.Navigation guidance on:' | \
grep -v '^Navigation.Navigation guidance enabled:' | \
grep -v '^Navigation.Navigation guidance type:' | \
grep -v '^Navigation.Guidance type default:' | \
grep -v '^Prompts.Name:' | \
grep -v '^System.Language:' | \
grep -v '^System.Default Language:' | \
grep -v '^Map.Static County:' | \
grep -v '^Editor.Gray scale:' | \
grep -v '^Display.Auto night mode:' | \
grep -v '^Display.Map sub_skin:' | \
grep -v '^Map.Background:' | \
grep -v '^Map.Labels:' | \
grep -v '^Navigation.RouteColor:' | \
grep -v '^Streets.' | \
grep -v '^Secondary.' | \
grep -v '^Primary.' | \
grep -v '^Freeways.' | \
grep -v '^Highways.' | \
grep -v '^Ramps.' | \
grep -v '^Exit.' | \
grep -v '^Tiles.Last Session:' | \
grep -v '^Tiles.Loading session lifetime:' | \
grep -v '^Scoreboard.Feature enabled:' | \
grep -v '^Scoreboard.Url:' | \
grep -v 'Secho' | \
grep -v 'Webho' > /tmp/wpref.n

echo "System.ServerId: 1" >> /tmp/wpref.n
echo "GeoConfig.version: 1" >> /tmp/wpref.n
echo "GeoConfig.Web-Service Address: http://rt.waze.com/rtserver" >> /tmp/wpref.n
echo "Realtime.Web-Service Address: http://rt.waze.com/rtserver" >> /tmp/wpref.n
echo "Realtime.Web-Service Secured Address: http://rt.waze.com/rtserver" >> /tmp/wpref.n
echo "Realtime.Web-Service Secured Address Resolved: http://rt.waze.com/rtserver" >> /tmp/wpref.n
echo "Realtime.Web-Service Secure Enabled Client_2_3: no" >> /tmp/wpref.n
echo "Realtime.Web-Service Secured Commands:" >> /tmp/wpref.n
echo "Realtime.Web-Service V2 Suffix:" >> /tmp/wpref.n
echo "Realtime.Web-Service V2 Commands: RoutingRequest" >> /tmp/wpref.n
echo "Realtime.Status: Enabled" >> /tmp/wpref.n
echo "Realtime.Auto registration: Disabled" >> /tmp/wpref.n
echo "Realtime.Name: ios6user" >> /tmp/wpref.n
echo "Realtime.Password: ios6pass" >> /tmp/wpref.n
echo "Realtime.Nickname: ios6user" >> /tmp/wpref.n
# Carte 100 % locale — pas de Download.Tiles (URLs /-0002_… si comté non activé).
echo "Download.Config: http://$PC/resources/config/" >> /tmp/wpref.n
echo "Download.Langs: http://$PC/resources/langs/" >> /tmp/wpref.n
echo "Download.Images: http://$PC/resources/images/" >> /tmp/wpref.n
echo "Download.Sound: http://$PC/resources/sounds/" >> /tmp/wpref.n
# Pas de Langs TTS (évite le blocage « Preparing navigation voice »).
echo "TTS.Feature Enabled: no" >> /tmp/wpref.n
echo "Navigation.Navigation guidance on: yes" >> /tmp/wpref.n
echo "Navigation.Navigation guidance enabled: yes" >> /tmp/wpref.n
echo "Navigation.Navigation guidance type: Minimal" >> /tmp/wpref.n
echo "Navigation.Guidance type default: Minimal" >> /tmp/wpref.n
echo "Prompts.Name: fra" >> /tmp/wpref.n
echo "System.Language: fra" >> /tmp/wpref.n
echo "System.Default Language: fra" >> /tmp/wpref.n
echo "Download.Enabled: no" >> /tmp/wpref.n
echo "Map.Static County: 77001" >> /tmp/wpref.n
echo "Editor.Gray scale: no" >> /tmp/wpref.n
echo "Display.Auto night mode: no" >> /tmp/wpref.n
echo "Display.Map sub_skin: day" >> /tmp/wpref.n
echo "Map.Background: #C5D0D4" >> /tmp/wpref.n
echo "Map.Labels: yes" >> /tmp/wpref.n
echo "Navigation.RouteColor: #9933FF" >> /tmp/wpref.n
echo "Streets.Thickness: 1" >> /tmp/wpref.n
echo "Streets.Color: #9A9A9A" >> /tmp/wpref.n
echo "Streets.Delta1: 1" >> /tmp/wpref.n
echo "Streets.Color1: #E6E6E6" >> /tmp/wpref.n
echo "Streets.LabelColor: #222222" >> /tmp/wpref.n
echo "Secondary.Thickness: 2" >> /tmp/wpref.n
echo "Secondary.Color: #C4A86A" >> /tmp/wpref.n
echo "Secondary.Delta1: 2" >> /tmp/wpref.n
echo "Secondary.Color1: #E6D09A" >> /tmp/wpref.n
echo "Primary.Thickness: 3" >> /tmp/wpref.n
echo "Primary.Color: #C4A050" >> /tmp/wpref.n
echo "Primary.Delta1: 2" >> /tmp/wpref.n
echo "Primary.Color1: #E8C86A" >> /tmp/wpref.n
echo "Highways.Thickness: 3" >> /tmp/wpref.n
echo "Highways.Color: #C4A050" >> /tmp/wpref.n
echo "Highways.Delta1: 2" >> /tmp/wpref.n
echo "Highways.Color1: #E8C86A" >> /tmp/wpref.n
echo "Freeways.Thickness: 3" >> /tmp/wpref.n
echo "Freeways.Color: #C4A050" >> /tmp/wpref.n
echo "Freeways.Delta1: 2" >> /tmp/wpref.n
echo "Freeways.Color1: #E8C86A" >> /tmp/wpref.n
echo "Ramps.Thickness: 1" >> /tmp/wpref.n
echo "Ramps.Color: #B0B0B0" >> /tmp/wpref.n
echo "Ramps.Delta1: 1" >> /tmp/wpref.n
echo "Ramps.Color1: #E6E6E6" >> /tmp/wpref.n
echo "Exit.Thickness: 2" >> /tmp/wpref.n
echo "Exit.Color: #C4A86A" >> /tmp/wpref.n
echo "Exit.Delta1: 1" >> /tmp/wpref.n
echo "Exit.Color1: #E6D09A" >> /tmp/wpref.n
echo "Scoreboard.Feature enabled: yes" >> /tmp/wpref.n
echo "Scoreboard.Url: http://$PC/scoreboard" >> /tmp/wpref.n
cp /tmp/wpref.n "$PREF"
cp /tmp/wpref.n "$BUNDLE"

if [ -f "$USERF" ]; then
  grep -v '^Realtime.Name:' "$USERF" | \
  grep -v '^Realtime.Password:' | \
  grep -v '^Realtime.PasswordEnc:' | \
  grep -v '^Realtime.Nickname:' | \
  grep -v '^Realtime.Random user:' | \
  grep -v '^Welcome Wizard.First time:' | \
  grep -v '^Welcome Wizard.Terms of Use accepted:' | \
  grep -v '^Navigation.Navigation guidance type:' | \
grep -v '^Prompts.Name:' | \
grep -v '^System.Language:' | \
grep -v '^System.Default Language:' | \
grep -v '^Display.Auto night mode:' | \
  grep -v '^Display.Map sub_skin:' > /tmp/wuser.n
else
  cp /dev/null /tmp/wuser.n
fi
echo "Realtime.Name: ios6user" >> /tmp/wuser.n
echo "Realtime.Password: ios6pass" >> /tmp/wuser.n
echo "Realtime.Nickname: ios6user" >> /tmp/wuser.n
echo "Realtime.Random user: 0" >> /tmp/wuser.n
echo "Welcome Wizard.First time: iphone_no" >> /tmp/wuser.n
echo "Welcome Wizard.Terms of Use accepted: yes" >> /tmp/wuser.n
echo "Navigation.Navigation guidance type: Minimal" >> /tmp/wuser.n
echo "Prompts.Name: fra" >> /tmp/wuser.n
echo "System.Language: fra" >> /tmp/wuser.n
echo "System.Default Language: fra" >> /tmp/wuser.n
echo "Display.Auto night mode: no" >> /tmp/wuser.n
echo "Display.Map sub_skin: day" >> /tmp/wuser.n
cp /tmp/wuser.n "$USERF"

# Prompts : lecture iOS = Documents/sound/<Prompts.Name>/ (roadmap_sound.m).
# fra et eng sont des packs distincts — ne plus copier le français sur l'anglais.
copy_prompts() {
  src="$1"
  dst="$2"
  mkdir -p "$dst"
  [ -d "$src" ] || return 0
  if [ -d "$src/fra" ]; then
    cp "$src/fra/"* "$dst/" 2>/dev/null || true
  elif [ -d "$src/eng" ]; then
    cp "$src/eng/"* "$dst/" 2>/dev/null || true
  else
    cp "$src/"* "$dst/" 2>/dev/null || true
  fi
  echo "Prompts → $dst ($(ls "$dst" 2>/dev/null | wc -l) fichiers)"
}
copy_prompts /tmp/waze-sound-fra "$CONTAINER/Documents/sound/fra"
copy_prompts /tmp/waze-sound-eng "$CONTAINER/Documents/sound/eng"
if id mobile >/dev/null 2>&1; then
  chown -R mobile:mobile "$CONTAINER/Documents/sound" 2>/dev/null || true
fi

# ── Carte : index + .wzm dans le cache ; bundle/maps → lien vers le cache ───
# roadmap_db_map_path() lit l'index dans bundle/maps (IPHONE).
# roadmap_gzm_open() lit map*.wzm d'abord dans Library/Caches/maps.
CACHE_MAPS=""
if [ -f /tmp/waze-cache-maps.sh ]; then
  CACHE_MAPS=$(sh /tmp/waze-cache-maps.sh "$CONTAINER" 2>/dev/null) || true
fi
if [ -z "$CACHE_MAPS" ]; then
  CACHE_MAPS="$CONTAINER/Library/Caches/maps"
fi
mkdir -p "$CACHE_MAPS"
echo "CACHE_MAPS=$CACHE_MAPS"

# État corrompu : tuiles HTTP partielles, queue, SQLite, edt-0002 (comté -2).
for root in \
  "$CONTAINER/Documents/maps" \
  "$CONTAINER/Library/maps" \
  "$CACHE_MAPS" \
  "$BUNDLE_MAPS"
do
  [ -d "$root/77001" ] && rm -rf "$root/77001" && echo "Tuiles supprimées: $root/77001"
done
rm -rf "$CACHE_MAPS/queue" "$CACHE_MAPS/77001"
rm -f "$CACHE_MAPS/tiles_77001.db" "$CACHE_MAPS/city_index"
rm -f "$CACHE_MAPS"/edt*.dat "$BUNDLE_MAPS"/edt*.dat 2>/dev/null
find "$CONTAINER/Library/Caches" -path "*/77001/*" -name "*.wdf" 2>/dev/null \
  | while read -r f; do rm -f "$f"; done

if [ ! -f /tmp/77001_index.wdf ] || [ ! -f /tmp/map77001.wzm ]; then
  echo "ERREUR: /tmp/77001_index.wdf et /tmp/map77001.wzm requis — relance phone.sh"
  exit 1
fi

cp /tmp/77001_index.wdf "$CACHE_MAPS/77001_index.wdf"
cp /tmp/map77001.wzm "$CACHE_MAPS/map77001.wzm"
echo "Carte → $CACHE_MAPS ($(du -h "$CACHE_MAPS/map77001.wzm" | cut -f1))"

# bundle/maps doit voir les mêmes fichiers (index lu ici par Waze).
if [ -L "$BUNDLE_MAPS" ]; then
  rm -f "$BUNDLE_MAPS"
elif [ -d "$BUNDLE_MAPS" ]; then
  rm -rf "$BUNDLE_MAPS"
fi
ln -sf "$CACHE_MAPS" "$BUNDLE_MAPS" 2>/dev/null || {
  mkdir -p "$BUNDLE_MAPS"
  cp "$CACHE_MAPS/77001_index.wdf" "$BUNDLE_MAPS/77001_index.wdf"
  cp "$CACHE_MAPS/map77001.wzm" "$BUNDLE_MAPS/map77001.wzm"
  echo "AVERTISSEMENT: lien symbolique impossible — copie directe dans bundle/maps"
}

# Propriétaire mobile (sinon l'app peut ignorer les fichiers injectés en root).
if id mobile >/dev/null 2>&1; then
  chown -R mobile:mobile "$CACHE_MAPS"
  chown -h mobile:mobile "$BUNDLE_MAPS" 2>/dev/null || chown -R mobile:mobile "$BUNDLE_MAPS"
fi
chmod -R u+rwX,go+rX "$CACHE_MAPS" 2>/dev/null || true

rm -f "$CONTAINER"/Documents/session*
killall -9 Waze waze 2>/dev/null

echo "=== VERIF ==="
grep 'Status:' "$PREF"
grep 'Download.Enabled' "$PREF"
grep 'Map.Static' "$PREF"
grep '^Download.Tiles:' "$PREF" && echo "ERREUR: Download.Tiles encore actif" >&2 || echo "Download.Tiles: absent (OK)"
grep '^Realtime.Name:' "$USERF"
echo "--- bundle/maps ---"
ls -la "$BUNDLE_MAPS" 2>/dev/null || true
echo "--- cache/maps ---"
ls -la "$CACHE_MAPS" 2>/dev/null || true
if id mobile >/dev/null 2>&1; then
  su mobile -c "test -r '$CACHE_MAPS/77001_index.wdf' && test -r '$CACHE_MAPS/map77001.wzm'" \
    && echo "Lecture mobile: OK" || echo "ERREUR: mobile ne peut pas lire la carte" >&2
fi
if [ -n "$BIN" ] && [ -f "$BIN" ]; then
  model=$(grep -a -o 'iPhone[0-9,]*' "$BIN" 2>/dev/null | head -1)
  echo "binary model hint: ${model:-unknown}"
fi
echo "DONE — relance Waze."
