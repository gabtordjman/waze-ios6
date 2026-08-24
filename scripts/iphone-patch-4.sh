#!/bin/sh
# Alias — utilise waze-patch.sh (auto-détecte le UUID Waze).
exec sh "$(dirname "$0")/waze-patch.sh" "$@"
