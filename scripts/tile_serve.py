#!/usr/bin/env python3
"""Sert les tuiles HTTP /tiles/.../*.wdf depuis map77001.wzm.

Waze 2.4 avec Download.Tiles=http://PC/tiles telecharge chaque carre
individuellement (roadmap_tile_storage.c). Sans reponse → carte vide malgre
le login OK. Ce module extrait les blobs du .wzm genere par wazemap.py.
"""

from __future__ import annotations

import re
import struct
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WZM = ROOT / "maps" / "auto" / "map77001.wzm"
WORLD_FIPS = 77001

DATA_SIGNATURE = b"WZDF"
ENDIAN_CORRECT = 0x00000001
DATA_VERSION = 0x00030000

# 77001_140208c4.wdf  ou chemin .../77001_140208/77001_140208c4.wdf
_TILE_RE = re.compile(r"77001_([0-9a-fA-F]{8})\.wdf")

_lock = threading.Lock()
_cache: dict[int, bytes] = {}
_wzm_mtime: float = 0.0
_served = 0


def _load_wzm() -> dict[int, bytes]:
    global _cache, _wzm_mtime
    if not WZM.is_file():
        return {}
    mtime = WZM.stat().st_mtime
    if _cache and mtime == _wzm_mtime:
        return _cache
    blob = WZM.read_bytes()
    if blob[:4] != b"WGZM":
        return {}
    num_tiles = struct.unpack("<i", blob[40:44])[0]
    out: dict[int, bytes] = {}
    for i in range(num_tiles):
        off = 44 + 16 * i
        tid, data_off, comp, raw_size = struct.unpack("<iIII", blob[off : off + 16])
        header = DATA_SIGNATURE + struct.pack(
            "<IIII", ENDIAN_CORRECT, DATA_VERSION, comp, raw_size
        )
        out[tid] = header + blob[data_off : data_off + comp]
    _cache = out
    _wzm_mtime = mtime
    return out


def tile_id_from_path(path: str) -> int | None:
    name = Path(path).name
    m = _TILE_RE.search(name)
    if not m:
        return None
    return int(m.group(1), 16)


def get_tile(path: str) -> bytes | None:
    """Retourne le .wdf complet ou None."""
    tid = tile_id_from_path(path)
    if tid is None:
        return None
    with _lock:
        tiles = _load_wzm()
        return tiles.get(tid)


def stats() -> tuple[int, int]:
    with _lock:
        return len(_cache), _served


def note_served() -> None:
    global _served
    _served += 1
