#!/bin/sh
# Regénère Packages et Release pour Cydia.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CYDIA="$ROOT/cydia"
DEBS="$CYDIA/debs"
mkdir -p "$DEBS"

cd "$DEBS"
if ! ls *.deb >/dev/null 2>&1; then
  echo "Aucun .deb dans $DEBS — lance: sh tweak/build-deb.sh IP_VPS"
  exit 1
fi

dpkg-scanpackages . /dev/null > "$CYDIA/Packages"
gzip -9c "$CYDIA/Packages" > "$CYDIA/Packages.bz2"
DATE=$(date -Ru)
cat > "$CYDIA/Release" << EOF
Origin: waze-ios6
Label: waze-ios6
Suite: stable
Version: 1.0
Codename: ios6
Architectures: iphoneos-arm
Components: main
Description: Waze 2.4 community server
Date: $DATE
EOF
echo "SHA1:" >> "$CYDIA/Release"
for f in Packages Packages.bz2; do
  sz=$(wc -c < "$CYDIA/$f" | tr -d ' ')
  hash=$(sha1sum "$CYDIA/$f" | awk '{print $1}')
  echo " $hash $sz $f" >> "$CYDIA/Release"
done
echo "OK $CYDIA/Packages.bz2"
