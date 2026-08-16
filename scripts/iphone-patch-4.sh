#!/bin/sh
APP=/var/mobile/Applications/8047C930-9816-413D-8F01-98BEB2775E5A
PC=192.168.1.191
PREF=$APP/Documents/preferences
BUNDLE=$APP/Waze.app/preferences
USERF=$APP/Documents/user
BIN=$APP/Waze.app/Waze

killall -9 Waze 2>/dev/null

[ -f "$BUNDLE" ] || { echo "FAIL: no Waze"; exit 1; }
[ -f "$PREF" ] || cp "$BUNDLE" "$PREF"

grep -q 'rt.waze.com' /etc/hosts || echo "$PC rt.waze.com" >> /etc/hosts

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
cp /tmp/wpref.n "$PREF"
cp /tmp/wpref.n "$BUNDLE"

if [ -f "$USERF" ]; then
  grep -v '^Realtime.Name:' "$USERF" | \
  grep -v '^Realtime.Password:' | \
  grep -v '^Realtime.PasswordEnc:' | \
  grep -v '^Realtime.Nickname:' | \
  grep -v '^Realtime.Random user:' | \
  grep -v '^Welcome Wizard.First time:' > /tmp/wuser.n
else
  cp /dev/null /tmp/wuser.n
fi
echo "Realtime.Name: ios6user" >> /tmp/wuser.n
echo "Realtime.Password: ios6pass" >> /tmp/wuser.n
echo "Realtime.Nickname: ios6user" >> /tmp/wuser.n
echo "Realtime.Random user: 0" >> /tmp/wuser.n
# iPhone Freemap: WELCOME_WIZ_FIRST_TIME_No = "iphone_no" (not "no")
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
echo "=== STRINGS (forensic) ==="
if [ -f "$BIN" ]; then
  grep -a -o 'RegisterSuccessful[^[:cntrl:]]\{0,80\}' "$BIN" 2>/dev/null | head -10
  grep -a -o 'LoginSuccessful[^[:cntrl:]]\{0,80\}' "$BIN" 2>/dev/null | head -10
  grep -a -o 'Failed to create[^[:cntrl:]]\{0,50\}' "$BIN" 2>/dev/null | head -5
  grep -a -o 'PhoneMinimal' "$BIN" 2>/dev/null | head -3
  OFF=$(grep -aob 'RegisterSuccessful' "$BIN" 2>/dev/null | head -1 | cut -d: -f1)
  if [ -n "$OFF" ]; then
    echo "RegisterSuccessful @ byte $OFF — 96 bytes:"
    dd if="$BIN" bs=1 skip="$OFF" count=96 2>/dev/null | od -An -tx1c | head -20
  fi
else
  echo "no binary"
fi
echo "DONE — First time=iphone_no. Catcher reg-proto202."
