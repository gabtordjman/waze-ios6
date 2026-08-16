#!/bin/sh
# Run ON the iPhone 4 (.60). Prefer: scp from PC then sh /tmp/waze-patch.sh
# No heredoc. No multi-line pipes. Safe for broken paste terminals.

APP=/var/mobile/Applications/8047C930-9816-413D-8F01-98BEB2775E5A
PC=192.168.1.191
PREF=$APP/Documents/preferences
BUNDLE=$APP/Waze.app/preferences
USERF=$APP/Documents/user

killall -9 Waze 2>/dev/null

if [ ! -f "$BUNDLE" ]; then
  echo "FAIL: no Waze at $BUNDLE"
  exit 1
fi
if [ ! -f "$PREF" ]; then
  cp "$BUNDLE" "$PREF"
fi

grep -q 'rt.waze.com' /etc/hosts || echo "$PC rt.waze.com" >> /etc/hosts

# Strip old keys then append (one file at a time — no for-loop paste issues)
strip_keys() {
  IN=$1
  OUT=$2
  grep -v '^System.ServerId:' "$IN" | grep -v '^GeoConfig.version:' | grep -v '^GeoConfig.Web-Service Address:' | grep -v '^Realtime.Web-Service Address:' | grep -v '^Realtime.Web-Service Secured Address:' | grep -v '^Realtime.Web-Service Secured Address Resolved:' | grep -v '^Realtime.Web-Service Secure Enabled' | grep -v '^Realtime.Web-Service Secured Commands:' | grep -v '^Realtime.Name:' | grep -v '^Realtime.Password:' | grep -v '^Realtime.Nickname:' | grep -v '^Download.Tiles:' | grep -v '^Download.Config:' | grep -v '^Download.Langs:' | grep -v '^Download.Images:' | grep -v '^Download.Sound:' | grep -v '^Download.Langs TTS:' > "$OUT"
}

strip_keys "$PREF" /tmp/wpref.n
echo "System.ServerId: 1" >> /tmp/wpref.n
echo "GeoConfig.version: 1" >> /tmp/wpref.n
echo "GeoConfig.Web-Service Address: http://rt.waze.com/rtserver" >> /tmp/wpref.n
echo "Realtime.Web-Service Address: http://rt.waze.com/rtserver" >> /tmp/wpref.n
echo "Realtime.Web-Service Secured Address: http://rt.waze.com/rtserver" >> /tmp/wpref.n
echo "Realtime.Web-Service Secured Address Resolved: http://rt.waze.com/rtserver" >> /tmp/wpref.n
echo "Realtime.Web-Service Secure Enabled Client_2_3: no" >> /tmp/wpref.n
echo "Realtime.Web-Service Secured Commands:" >> /tmp/wpref.n
echo "Download.Tiles: http://$PC/tiles" >> /tmp/wpref.n
echo "Download.Config: http://$PC/resources/config/" >> /tmp/wpref.n
echo "Download.Langs: http://$PC/resources/langs/" >> /tmp/wpref.n
echo "Download.Images: http://$PC/resources/images/" >> /tmp/wpref.n
echo "Download.Sound: http://$PC/resources/sounds/" >> /tmp/wpref.n
echo "Download.Langs TTS: http://$PC/resources/lang_tts/" >> /tmp/wpref.n
cp /tmp/wpref.n "$PREF"
cp /tmp/wpref.n "$BUNDLE"

# Patch user file IN PLACE (do not wipe it)
if [ -f "$USERF" ]; then
  grep -v '^Realtime.Name:' "$USERF" | grep -v '^Realtime.Password:' | grep -v '^Realtime.Nickname:' | grep -v '^Realtime.Random user:' > /tmp/wuser.n
else
  cp /dev/null /tmp/wuser.n
fi
echo "Realtime.Name: ios6user" >> /tmp/wuser.n
echo "Realtime.Password: ios6pass" >> /tmp/wuser.n
echo "Realtime.Nickname: ios6user" >> /tmp/wuser.n
echo "Realtime.Random user: 1" >> /tmp/wuser.n
cp /tmp/wuser.n "$USERF"

rm -f "$APP"/Documents/session*
killall -9 Waze 2>/dev/null

echo "=== MUST show Secure=no and Name=ios6user ==="
grep 'Secure Enabled' "$PREF"
grep '^Realtime.Name:' "$USERF"
grep '^Realtime.Password:' "$USERF"
grep 'Web-Service Address' "$PREF"
echo "DONE"
