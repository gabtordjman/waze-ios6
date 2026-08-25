#!/bin/sh
# Regénère Packages et Release pour Cydia.
#
# Préfère dpkg-scanpackages (paquet Debian: dpkg-dev).
# Sinon fallback via dpkg-deb -I (souvent déjà présent avec dpkg).
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

_write_packages_scan() {
  dpkg-scanpackages . /dev/null > "$CYDIA/Packages"
}

_write_packages_fallback() {
  : > "$CYDIA/Packages"
  for deb in *.deb; do
    [ -f "$deb" ] || continue
    sz=$(wc -c < "$deb" | tr -d ' ')
    md5=$(md5sum "$deb" | awk '{print $1}')
    sha1=$(sha1sum "$deb" | awk '{print $1}')
    sha256=$(sha256sum "$deb" | awk '{print $1}')
    # Contrôle du .deb (sans Signature / etc.)
    dpkg-deb -f "$deb" Package Version Architecture Maintainer Depends Section Description Name 2>/dev/null \
      | awk -v fn="./$deb" -v sz="$sz" -v md5="$md5" -v sha1="$sha1" -v sha256="$sha256" '
        BEGIN { pkg=""; ver=""; arch=""; maint=""; dep=""; sec=""; desc=""; name="" }
        /^Package:/ { pkg=$0; sub(/^Package: */,"",pkg) }
        /^Version:/ { ver=$0; sub(/^Version: */,"",ver) }
        /^Architecture:/ { arch=$0; sub(/^Architecture: */,"",arch) }
        /^Maintainer:/ { maint=$0; sub(/^Maintainer: */,"",maint) }
        /^Depends:/ { dep=$0; sub(/^Depends: */,"",dep) }
        /^Section:/ { sec=$0; sub(/^Section: */,"",sec) }
        /^Description:/ { desc=$0; sub(/^Description: */,"",desc) }
        /^Name:/ { name=$0; sub(/^Name: */,"",name) }
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
        echo "ERREUR: lecture control de $deb (installe dpkg-dev ou dpkg)"
        exit 1
      }
  done
}

if command -v dpkg-scanpackages >/dev/null 2>&1; then
  echo "→ dpkg-scanpackages"
  _write_packages_scan
elif command -v dpkg-deb >/dev/null 2>&1; then
  echo "→ fallback dpkg-deb (installe dpkg-dev pour le mode officiel)"
  echo "   sudo apt-get install -y dpkg-dev"
  _write_packages_fallback
else
  echo "ERREUR: ni dpkg-scanpackages ni dpkg-deb."
  echo "  sudo apt-get install -y dpkg-dev"
  exit 1
fi

if command -v gzip >/dev/null 2>&1; then
  gzip -9c "$CYDIA/Packages" > "$CYDIA/Packages.bz2"
else
  echo "AVERTISSEMENT: gzip absent — Packages.bz2 non généré"
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
