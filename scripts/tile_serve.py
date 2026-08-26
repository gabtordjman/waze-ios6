#!/usr/bin/env python3
"""Sert les tuiles HTTP /tiles/.../*.wdf depuis map77001.wzm.

Waze 2.4 avec Download.Tiles=http://PC/tiles telecharge chaque carre
individuellement (roadmap_tile_manager.c). Format d'URL :
  {prefix}/77001_XX/77001_XXXX/77001_XXXXXX/77001_XXXXXXXX.wdf?sessionid=N

Sans reponse valide le rafraichissement carte bloque (~3%) et le .wzm local
supprime laisse la carte vide au redemarrage.

Important VPS : ne pas servir de stub vide pendant le 1er build Overpass —
sinon l'iPhone cache des tuiles vides et l'ecran reste blanc.
"""

from __future__ import annotations

import ctypes
import re
import struct
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WZM = ROOT / "maps" / "auto" / "map77001.wzm"
WORLD_FIPS = 77001

# En dessous = starter tweak / carte vide — on attend Overpass.
_MIN_READY_BYTES = 50_000

DATA_SIGNATURE = b"WZDF"
ENDIAN_CORRECT = 0x00000001
DATA_VERSION = 0x00030000

_TILE_RE = re.compile(r"77001_([0-9a-fA-F]{8})\.wdf")

_lock = threading.Lock()
_cache: dict[int, bytes] = {}
_stub_cache: dict[int, bytes] = {}
_wzm_mtime: float = 0.0
_served = 0


def _wzm_ready() -> bool:
    try:
        return WZM.is_file() and WZM.stat().st_size >= _MIN_READY_BYTES
    except OSError:
        return False


def clear_caches() -> None:
    """Appelé après un build OSM pour forcer le rechargement."""
    global _cache, _stub_cache, _wzm_mtime
    with _lock:
        _cache = {}
        _stub_cache = {}
        _wzm_mtime = 0.0


def _load_wzm() -> dict[int, bytes]:
    global _cache, _wzm_mtime, _stub_cache
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
    # Nouvelle carte → oublier les stubs (sinon tuiles vides resservies).
    _stub_cache = {}
    return out


def _stub_tile(tid: int) -> bytes:
    hit = _stub_cache.get(tid)
    if hit:
        return hit
    from wazemap import TileBuilder, pack_tile

    wdf = pack_tile(
        TileBuilder(ctypes.c_int32(tid).value).payload(int(time.time()))
    )
    _stub_cache[tid] = wdf
    return wdf


def tile_id_from_path(path: str) -> int | None:
    name = Path(path).name.split("?", 1)[0]
    m = _TILE_RE.search(name)
    if not m:
        return None
    return int(m.group(1), 16)


def get_tile(
    path: str,
    *,
    allow_stub: bool = True,
    wait_build_sec: float = 90.0,
) -> tuple[bytes | None, str]:
    """Retourne (blob .wdf, kind) avec kind in ('wzm', 'stub', '').

    Si la carte n'est pas encore prête (1er GPS / Overpass), attend jusqu'à
    wait_build_sec avant de répondre — évite de cacher des stubs vides.
    """
    tid = tile_id_from_path(path)
    if tid is None:
        return None, ""

    deadline = time.time() + max(0.0, wait_build_sec)
    while True:
        with _lock:
            hit = _load_wzm().get(tid)
            if hit:
                return hit, "wzm"
            ready = _wzm_ready()
        if ready:
            # Carte présente mais cette tuile hors zone → stub ou 404.
            break
        if time.time() >= deadline:
            break
        time.sleep(0.4)

    with _lock:
        hit = _load_wzm().get(tid)
        if hit:
            return hit, "wzm"
        # Stub seulement si une vraie carte existe déjà (hors bbox).
        if allow_stub and _wzm_ready():
            return _stub_tile(tid), "stub"
        return None, ""


def stats() -> tuple[int, int]:
    with _lock:
        return len(_cache), _served


def note_served(kind: str = "wzm") -> None:
    global _served
    _ = kind
    _served += 1
