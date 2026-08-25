#!/usr/bin/env python3
"""Carte OSM automatique autour de la position GPS du téléphone.

Le catcher appelle `schedule_build(lon, lat)` sur At / Location
(pas MapDisplayed). La carte sort dans `maps/auto/`.

Détail (~4 km) aux échelles 0–1. Le dézoom réutilise les axes du détail :
une bbox 40 km Overpass 504 presque toujours et bloquait toute la génération.

Usage :
    python3 scripts/map_auto.py build --lon 6.4847 --lat 46.3646 --force
    python3 scripts/map_auto.py build --lon 6.4847 --lat 46.3646 --refresh-osm
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WAZEMAP = ROOT / "scripts" / "wazemap.py"
STATE = ROOT / "logs" / "map-auto-state.json"
LOG = ROOT / "logs" / "rts-catcher.txt"
REGION = "auto"

# ~4 km : détail (échelles 0–1).
HALF_DEG = 0.04
# ~8 km : axes du dézoom. 0,35° (~40 km) faisait 504 Overpass à tous les coups.
HALF_WIDE_DEG = 0.08
# 0..5 : toutes les échelles demandées au dézoom (s2–s5 dans MapDisplayed).
MAX_SCALE = 5
WIDE_MIN_SCALE = 2
# Ne regénère que si le GPS a bougé d'au moins ~5 km.
MIN_MOVE_DEG = 0.05

# Fix GPS iOS 6 avant verrouillage : 0,0 ou proche → ignorer.
def coords_sane(lon: float, lat: float) -> bool:
    if abs(lat) > 85 or abs(lon) > 180:
        return False
    if abs(lat) < 2.0 and abs(lon) < 2.0:
        return False
    return True

_lock = threading.Lock()
_busy = False


def _load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_state(data: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _moved_enough(lon: float, lat: float, state: dict) -> bool:
    prev = state.get("center")
    if not prev:
        return True
    dlon = abs(lon - float(prev[0]))
    dlat = abs(lat - float(prev[1]))
    return dlon >= MIN_MOVE_DEG or dlat >= MIN_MOVE_DEG


def bbox_for(lon: float, lat: float) -> tuple[float, float, float, float]:
    return (
        lon - HALF_DEG,
        lat - HALF_DEG,
        lon + HALF_DEG,
        lat + HALF_DEG,
    )


def wide_bbox_for(lon: float, lat: float) -> tuple[float, float, float, float]:
    return (
        lon - HALF_WIDE_DEG,
        lat - HALF_WIDE_DEG,
        lon + HALF_WIDE_DEG,
        lat + HALF_WIDE_DEG,
    )


def build_sync(
    lon: float, lat: float, *, force: bool = False, refresh_osm: bool = False
) -> int:
    """Construit maps/auto/ si nécessaire. Retourne 0 si OK ou déjà à jour."""
    if not coords_sane(lon, lat):
        print(f"GPS ignoré (fix invalide) : {lon:.6f},{lat:.6f}", file=sys.stderr)
        return 0
    with _lock:
        state = _load_state()
        out_wzm = ROOT / "maps" / REGION / "map77001.wzm"
        if not force and out_wzm.is_file() and not _moved_enough(lon, lat, state):
            print(f"carte auto déjà à jour pour {lon:.5f},{lat:.5f}")
            return 0

    west, south, east, north = bbox_for(lon, lat)
    ww, ws, we, wn = wide_bbox_for(lon, lat)
    bbox = f"{west:.6f},{south:.6f},{east:.6f},{north:.6f}"
    wide = f"{ww:.6f},{ws:.6f},{we:.6f},{wn:.6f}"
    print(f"Génération OSM → maps/{REGION}/  détail {bbox}  large {wide}")

    osm_cache = ROOT / "logs" / f"osm-{REGION}.json"
    cmd = [
        sys.executable,
        str(WAZEMAP),
        "build",
        f"--bbox={bbox}",
        f"--wide-bbox={wide}",
        f"--wide-min-scale={WIDE_MIN_SCALE}",
        "--name",
        REGION,
        "--max-scale",
        str(MAX_SCALE),
    ]
    # --force réécrit le .wzm. Le JSON détail déjà téléchargé se réutilise
    # (évite de re-attendre Overpass). --refresh-osm pour re-télécharger.
    if osm_cache.is_file() and not refresh_osm:
        print(f"détail depuis le cache {osm_cache}")
        cmd.extend(["--osm", str(osm_cache)])

    proc = subprocess.run(cmd, cwd=str(ROOT))
    if proc.returncode != 0:
        return proc.returncode

    with _lock:
        _save_state(
            {
                "center": [lon, lat],
                "bbox": [west, south, east, north],
                "wide_bbox": [ww, ws, we, wn],
                "region": REGION,
            }
        )
    return 0


def schedule_build(lon: float, lat: float, *, force: bool = False) -> None:
    """Lance la génération en arrière-plan (depuis le catcher HTTP)."""
    if not coords_sane(lon, lat):
        return

    def _run() -> None:
        global _busy
        with _lock:
            if _busy:
                return
            state = _load_state()
            out_wzm = ROOT / "maps" / REGION / "map77001.wzm"
            if not force and out_wzm.is_file() and not _moved_enough(lon, lat, state):
                return
            _busy = True
        try:
            build_sync(lon, lat, force=force)
        finally:
            with _lock:
                _busy = False

    threading.Thread(target=_run, daemon=True).start()


def coords_from_log() -> tuple[float, float] | None:
    if not LOG.exists():
        return None
    text = LOG.read_text(encoding="utf-8", errors="replace")
    # Préférer un GPS At/Location, pas le centre MapDisplayed.
    for pat in (
        r"GPS ([-\d.]+),([-\d.]+)",
        r"At,([-\d.]+),([-\d.]+),",
        r"Location,([-\d.]+),([-\d.]+)",
        r"GetGeoServerConfig,\d+,([-\d.]+),([-\d.]+)",
        r"carte OSM auto programmée pour ([-\d.]+),([-\d.]+)",
    ):
        hits = re.findall(pat, text)
        if hits:
            lon, lat = hits[-1]
            return float(lon), float(lat)
    return None


def cmd_build(args) -> int:
    return build_sync(
        args.lon, args.lat, force=args.force, refresh_osm=args.refresh_osm
    )


def cmd_ensure(args) -> int:
    if args.lon is not None and args.lat is not None:
        lon, lat = args.lon, args.lat
    elif args.from_log:
        pair = coords_from_log()
        if not pair:
            print("Aucune coordonnée dans logs/rts-catcher.txt", file=sys.stderr)
            return 1
        lon, lat = pair
        print(f"Position lue dans le log : {lon:.6f},{lat:.6f}")
    else:
        print("Indique --lon/--lat ou --from-log", file=sys.stderr)
        return 1
    return build_sync(
        lon, lat, force=args.force, refresh_osm=args.refresh_osm
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="génère maps/auto/ maintenant")
    b.add_argument("--lon", type=float, required=True)
    b.add_argument("--lat", type=float, required=True)
    b.add_argument("--force", action="store_true")
    b.add_argument(
        "--refresh-osm",
        action="store_true",
        help="retélécharge Overpass même si logs/osm-auto.json existe",
    )
    b.set_defaults(func=cmd_build)

    e = sub.add_parser("ensure", help="génère si absent ou position changée")
    e.add_argument("--lon", type=float)
    e.add_argument("--lat", type=float)
    e.add_argument("--from-log", action="store_true")
    e.add_argument("--force", action="store_true")
    e.add_argument("--refresh-osm", action="store_true")
    e.set_defaults(func=cmd_ensure)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
