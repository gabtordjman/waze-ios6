#!/bin/sh
# Construit le .deb Cydia (sans Theos).
# Usage: sh tweak/build-deb.sh 203.0.113.50
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IP="${1:?Usage: sh tweak/build-deb.sh VPS_IP}"
VER="${2:-1.0.0}"

cd "$ROOT"
python3 scripts/gen_map_starter.py

STAGE="$ROOT/tweak/stage"
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" "$STAGE/usr/share/waze-ios6"

cp tweak/resources/77001_index.wdf tweak/resources/map77001.wzm "$STAGE/usr/share/waze-ios6/"
sed "s/@WAZE_SERVER_IP@/$IP/g" tweak/layout/DEBIAN/postinst > "$STAGE/DEBIAN/postinst"
chmod 755 "$STAGE/DEBIAN/postinst"
sed "s/^Version:.*/Version: $VER/" tweak/layout/DEBIAN/control > "$STAGE/DEBIAN/control"

OUT="$ROOT/cydia/debs/com.wazeios6.server_${VER}_iphoneos-arm.deb"
mkdir -p "$ROOT/cydia/debs"
dpkg-deb -Zgzip -b "$STAGE" "$OUT"
rm -rf "$STAGE"
echo "OK $OUT"
