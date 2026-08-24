#!/bin/sh
# Patch Waze 3.9.6 — fonctionne sur iPhone 4 / 4S (auto-détecte le UUID).
# Sur le téléphone :  sh /tmp/waze-patch.sh
# Depuis le PC      :  scripts/patch-iphone.sh 192.168.1.60

PC="${PC:-192.168.1.191}"

if [ -n "$APP" ] && [ -d "$APP/Waze.app" ]; then
  :
else
  APP=""
  for d in /var/mobile/Applications/*/Waze.app; do
    [ -d "$d" ] || continue
    APP="${d%/Waze.app}"
    break
  done
  if [ -z "$APP" ]; then
    APP=$(find /var/mobile/Applications -maxdepth 2 -type d -name Waze.app 2>/dev/null | head -1)
    APP="${APP%/Waze.app}"
  fi
fi

[ -n "$APP" ] && [ -d "$APP/Waze.app" ] || {
  echo "FAIL: Waze.app introuvable. Liste:"
  ls /var/mobile/Applications/ 2>/dev/null
  exit 1
}

echo "=== Waze patch ==="
echo "APP=$APP"
echo "PC=$PC"

PREF=$APP/Documents/preferences
BUNDLE=$APP/Waze.app/preferences
USERF=$APP/Documents/user
BIN=$APP/Waze.app/Waze

killall -9 Waze 2>/dev/null

[ -f "$BUNDLE" ] || { echo "FAIL: pas de bundle preferences"; exit 1; }
[ -f "$PREF" ] || cp "$BUNDLE" "$PREF"

grep -q 'rt.waze.com' /etc/hosts 2>/dev/null || echo "$PC rt.waze.com" >> /etc/hosts

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
grep -v '^Map.Static County:' | \
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
echo "Download.Tiles: http://$PC/tiles" >> /tmp/wpref.n
echo "Download.Config: http://$PC/resources/config/" >> /tmp/wpref.n
echo "Download.Langs: http://$PC/resources/langs/" >> /tmp/wpref.n
echo "Download.Images: http://$PC/resources/images/" >> /tmp/wpref.n
echo "Download.Sound: http://$PC/resources/sounds/" >> /tmp/wpref.n
echo "Download.Langs TTS: http://$PC/resources/lang_tts/" >> /tmp/wpref.n
# 77001 = la carte monde de Waze (editor_main.c). Fixer le comte evite tout
# l'annuaire des comtes americains : roadmap_county_by_position renvoie
# directement ce numero, donc l'app ouvre notre carte des le premier ecran,
# sans attendre la reponse GetGeoServerConfig.
echo "Map.Static County: 77001" >> /tmp/wpref.n
cp /tmp/wpref.n "$PREF"
cp /tmp/wpref.n "$BUNDLE"

if [ -f "$USERF" ]; then
  grep -v '^Realtime.Name:' "$USERF" | \
  grep -v '^Realtime.Password:' | \
  grep -v '^Realtime.PasswordEnc:' | \
  grep -v '^Realtime.Nickname:' | \
  grep -v '^Realtime.Random user:' | \
  grep -v '^Welcome Wizard.First time:' | \
  grep -v '^Welcome Wizard.Terms of Use accepted:' > /tmp/wuser.n
else
  cp /dev/null /tmp/wuser.n
fi
echo "Realtime.Name: ios6user" >> /tmp/wuser.n
echo "Realtime.Password: ios6pass" >> /tmp/wuser.n
echo "Realtime.Nickname: ios6user" >> /tmp/wuser.n
echo "Realtime.Random user: 0" >> /tmp/wuser.n
echo "Welcome Wizard.First time: iphone_no" >> /tmp/wuser.n
echo "Welcome Wizard.Terms of Use accepted: yes" >> /tmp/wuser.n
cp /tmp/wuser.n "$USERF"

rm -f "$APP"/Documents/session*
killall -9 Waze 2>/dev/null

echo "=== VERIF ==="
grep 'Status:' "$PREF"
grep 'Auto registration' "$PREF"
grep 'V2 ' "$PREF"
grep '^Realtime.Name:' "$USERF"
grep 'Wizard' "$USERF"
grep 'Tiles' "$PREF"
if [ -f "$BIN" ]; then
  model=$(grep -a -o 'iPhone[0-9,]*' "$BIN" 2>/dev/null | head -1)
  echo "binary model hint: ${model:-unknown}"
fi
echo "DONE — iphone_no + ios6user/ios6pass. Relance Waze."
