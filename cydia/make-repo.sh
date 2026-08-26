#!/bin/sh
# Regénère Packages / Packages.bz2 / Release pour Cydia.
#
# Layout (compatible Cydia + GitHub / jsDelivr / catcher) :
#   cydia/Packages
#   cydia/Packages.bz2
#   cydia/Release
#   cydia/debs/*.deb
# Filename dans Packages = ./debs/<fichier>.deb
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CYDIA="$ROOT/cydia"
DEBS="$CYDIA/debs"
mkdir -p "$DEBS"

cd "$DEBS"
# shellcheck disable=SC2039
set -- *.deb
if [ ! -f "$1" ]; then
  echo "Aucun .deb dans $DEBS — lance: sh tweak/build-deb.sh IP_VPS[:PORT]"
  exit 1
fi

_write_packages() {
  : > "$CYDIA/Packages"
  for deb in *.deb; do
    [ -f "$deb" ] || continue
    sz=$(wc -c < "$deb" | tr -d ' ')
    md5=$(md5sum "$deb" | awk '{print $1}')
    sha1=$(sha1sum "$deb" | awk '{print $1}')
    sha256=$(sha256sum "$deb" | awk '{print $1}')
    rel="./debs/$deb"
    dpkg-deb -f "$deb" Package Version Architecture Maintainer Depends Section Description Name 2>/dev/null \
      | awk -v fn="$rel" -v sz="$sz" -v md5="$md5" -v sha1="$sha1" -v sha256="$sha256" '
        BEGIN { pkg=""; ver=""; arch=""; maint=""; dep=""; sec=""; desc=""; name="" }
        /^Package:/ { sub(/^Package: */,""); pkg=$0 }
        /^Version:/ { sub(/^Version: */,""); ver=$0 }
        /^Architecture:/ { sub(/^Architecture: */,""); arch=$0 }
        /^Maintainer:/ { sub(/^Maintainer: */,""); maint=$0 }
        /^Depends:/ { sub(/^Depends: */,""); dep=$0 }
        /^Section:/ { sub(/^Section: */,""); sec=$0 }
        /^Description:/ { sub(/^Description: */,""); desc=$0 }
        /^Name:/ { sub(/^Name: */,""); name=$0 }
        END {
          if (pkg == "") exit 1
          print "Package: " pkg
          if (name != "") print "Name: " name
          print "Version: " ver
          print "Architecture: " arch
          if (maint != "") print "Maintainer: " maint
          if (dep != "") print "Depends: " dep
          if (sec != "") print "Section: " sec
          print "Filename: " fn
          print "Size: " sz
          print "MD5sum: " md5
          print "SHA1: " sha1
          print "SHA256: " sha256
          if (desc != "") print "Description: " desc
          print ""
        }
      ' >> "$CYDIA/Packages" || {
        echo "ERREUR: lecture control de $deb"
        echo "  sudo apt-get install -y dpkg"
        exit 1
      }
  done
}

if ! command -v dpkg-deb >/dev/null 2>&1; then
  echo "ERREUR: dpkg-deb introuvable — sudo apt-get install -y dpkg"
  exit 1
fi

echo "→ génération Packages (Filename=./debs/…)"
_write_packages

if command -v bzip2 >/dev/null 2>&1; then
  bzip2 -9c "$CYDIA/Packages" > "$CYDIA/Packages.bz2"
elif command -v gzip >/dev/null 2>&1; then
  echo "AVERTISSEMENT: bzip2 absent — apt install bzip2 recommandé"
  gzip -9c "$CYDIA/Packages" > "$CYDIA/Packages.bz2"
fi

DATE=$(date -Ru 2>/dev/null || date -u)
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
  [ -f "$CYDIA/$f" ] || continue
  sz=$(wc -c < "$CYDIA/$f" | tr -d ' ')
  if command -v sha1sum >/dev/null 2>&1; then
    hash=$(sha1sum "$CYDIA/$f" | awk '{print $1}')
  else
    hash=$(openssl dgst -sha1 "$CYDIA/$f" | awk '{print $NF}')
  fi
  echo " $hash $sz $f" >> "$CYDIA/Release"
done

echo "OK $CYDIA/Packages"
[ -f "$CYDIA/Packages.bz2" ] && echo "OK $CYDIA/Packages.bz2"
echo ""
echo "Sources Cydia (pas de 307) :"
echo "  1) Catcher VPS :  http://TON_IP:8080/cydia"
echo "  2) jsDelivr     :  https://cdn.jsdelivr.net/gh/USER/REPO@vps/cydia"
echo "Éviter raw.githubusercontent.com (redirect 307 → Cydia iOS 6 casse)."
