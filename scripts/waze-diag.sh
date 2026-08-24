#!/bin/sh
# Tourne SUR l'iPhone. Sort tout ce qui permet de trouver le format Login exact.
#   - journal roadmap_log de Waze (contient "RTNet::OnLoginResponse() - Failed to read X")
#   - chaines du binaire Waze (liste reelle des champs lus par cette version)

APP=""
for d in /var/mobile/Applications/*/Waze.app; do
  [ -d "$d" ] || continue
  APP="${d%/Waze.app}"
  break
done
[ -n "$APP" ] || APP=$(find /var/mobile/Applications -maxdepth 2 -type d -name Waze.app 2>/dev/null | head -1 | sed 's|/Waze.app$||')

[ -n "$APP" ] && [ -d "$APP/Waze.app" ] || { echo "FAIL: Waze.app introuvable"; exit 1; }

echo "APP=$APP"
echo

echo "=== 1. Fichiers journaux presents ==="
find "$APP" -type f \( -name '*.log' -o -name 'waze_log*' -o -name 'postmortem*' \) 2>/dev/null | while read -r f; do
  echo "  $f  ($(wc -c < "$f" 2>/dev/null) octets, modifie $(date -r "$f" 2>/dev/null))"
done
echo

echo "=== 2. Erreurs Login / parseur (les 80 dernieres) ==="
FOUND=0
find "$APP" -type f \( -name '*.log' -o -name 'waze_log*' -o -name 'postmortem*' \) 2>/dev/null | while read -r f; do
  if grep -a -q -E 'OnLoginResponse|OnCustomResponse|VerifyStatusAndTag|parser|Login' "$f" 2>/dev/null; then
    echo "--- $f"
    grep -a -E 'OnLoginResponse|OnCustomResponse|VerifyStatusAndTag|missing parser|Did not find parser|unexpected|Login' "$f" 2>/dev/null | tail -80
    FOUND=1
  fi
done
[ "$FOUND" = "0" ] && echo "  (aucun journal exploitable — voir section 3)"
echo

echo "=== 3. Champs lus par OnLoginResponse (chaines du binaire) ==="
BIN="$APP/Waze.app/Waze"
if [ -f "$BIN" ]; then
  if command -v strings >/dev/null 2>&1; then
    strings -a "$BIN" 2>/dev/null | grep -a 'OnLoginResponse' | head -40
    echo "  --- ordre des champs = ordre de ces lignes ---"
  else
    # Pas de 'strings' : extraction minimale avec tr
    tr -c '[:print:]' '\n' < "$BIN" 2>/dev/null | grep -a 'OnLoginResponse' | head -40
  fi
else
  echo "  binaire introuvable: $BIN"
fi
echo

echo "=== 4. Autres chaines RTNet utiles ==="
if [ -f "$BIN" ]; then
  { strings -a "$BIN" 2>/dev/null || tr -c '[:print:]' '\n' < "$BIN" 2>/dev/null; } \
    | grep -a -E 'LoginSuccessful|LoginError|RegisterSuccessful|UpdateInboxCount|ServerConfig' \
    | sort -u | head -30
fi
echo

echo "=== 5. Preferences actives ==="
grep -E 'ServerId|Web-Service|Realtime.Status|Realtime.Name|Download\.' "$APP/Documents/preferences" 2>/dev/null
echo
echo "=== FIN ==="
