#!/usr/bin/env python3
"""Génère index + .wzm starter pour le tweak Cydia (bootstrap carte iPhone)."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from wazemap import (  # noqa: E402
    WORLD_FIPS,
    TileBuilder,
    county_index_tile,
    pack_tile,
    tile_edges,
    tile_id,
    write_wzm,
)


def build_starter(
    lon: float = 0.0,
    lat: float = 0.0,
    out_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Index minimal + .wzm une tuile vide (valide WZDF)."""
    out = out_dir or (ROOT / "tweak" / "resources")
    out.mkdir(parents=True, exist_ok=True)
    lon_u = int(round(lon * 1_000_000))
    lat_u = int(round(lat * 1_000_000))
    tid = tile_id(lon_u, lat_u, 0)
    west, east, south, north, _ = tile_edges(tid)
    ts = int(time.time())
    payload = TileBuilder(tid).payload(ts)
    wzm = out / f"map{WORLD_FIPS:05d}.wzm"
    index = out / f"{WORLD_FIPS:05d}_index.wdf"
    write_wzm(wzm, {tid: payload}, (west, south, east, north))
    index.write_bytes(county_index_tile(ts))
    return index, wzm


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lon", type=float, default=0.0)
    ap.add_argument("--lat", type=float, default=0.0)
    ap.add_argument(
        "-o",
        "--out",
        type=Path,
        default=ROOT / "tweak" / "resources",
        help="dossier de sortie",
    )
    args = ap.parse_args()
    index, wzm = build_starter(args.lon, args.lat, args.out)
    print(f"{index}  ({index.stat().st_size} octets)")
    print(f"{wzm}  ({wzm.stat().st_size} octets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
