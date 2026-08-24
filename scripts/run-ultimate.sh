#!/bin/sh
# Wrapper — toujours: sudo python3 scripts/run-ultimate.py
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/run-ultimate.py"
