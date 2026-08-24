#!/usr/bin/env python3
"""Génère des cartes Waze 2.4.0.0 (protocole 150) à partir de données OSM.

Tout le format vient de la source GPL (github.com/mkoloberdin/waze, branche
`iphone`) — rien n'est deviné :

  roadmap_data_format.h  en-têtes .wdf (tuile) et .wzm (paquet de région)
  roadmap_dbread.c       validation lue par le client, section par section
  roadmap_tile_model.h   les 28 sections d'une tuile, dans l'ordre
  roadmap_tile.c         calcul de l'identifiant de tuile
  roadmap_db_*.h         structures binaires de chaque section
  roadmap_point.h        position = bord SO du carré + offset16 × facteur
  roadmap_line.c         index cumulatif par catégorie (lignes triées)
  roadmap_county_model.h les quatre sections du fichier d'index
  roadmap_locator.c      l'index s'ouvre avant le paquet, sinon rien ne charge

Usage :
    python3 scripts/wazemap.py selftest
    python3 scripts/wazemap.py build --bbox 6.55,46.50,6.70,46.56 --name lausanne
    python3 scripts/wazemap.py build --osm data/region.osm --name boston

Deux fichiers sortent dans `maps/<name>/` et voyagent ensemble :
`map<fips>.wzm`, le paquet de tuiles, et `<fips>_index.wdf`, l'index que
roadmap_locator_open exige avant même de regarder le paquet.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ── En-têtes de fichier (roadmap_data_format.h) ──────────────────────────────
DATA_SIGNATURE = b"WZDF"
MAP_SIGNATURE = b"WGZM"
ENDIAN_CORRECT = 0x00000001
DATA_VERSION = 0x00030000
MAP_VERSION = 0x00030000
TILE_HEADER_LEN = 20  # sizeof(roadmap_tile_file_header)

# ── Sections d'une tuile (roadmap_tile_model.h) ──────────────────────────────
S_STRING_PREFIX = 0
S_STRING_STREET = 1
S_STRING_T2S = 2
S_STRING_TYPE = 3
S_STRING_SUFFIX = 4
S_STRING_CITY = 5
S_STRING_ATTRIBUTES = 6
S_STRING_LANDMARK = 7
S_SHAPE_DATA = 8
S_LINE_DATA = 9
S_LINE_BYSQUARE1 = 10
S_LINE_BROKEN = 11
S_LINE_ROUNDABOUT = 12
S_POINT_DATA = 13
S_POINT_ID = 14
S_LINE_ROUTE_DATA = 15
S_STREET_NAME = 16
S_STREET_CITY = 17
S_POLYGON_HEAD = 18
S_POLYGON_POINT = 19
S_LINE_SPEED_REF = 20
S_LINE_SPEED_AVG = 21
S_LINE_SPEED_INDEX = 22
S_LINE_SPEED_DATA = 23
S_RANGE_ADDR = 24
S_ALERT_DATA = 25
S_SQUARE_DATA = 26
S_METADATA_ATTRIBUTES = 27
NUM_SECTIONS = 28  # model__tile

# Modèle « comté » (roadmap_county_model.h) : l'index global de la carte.
COUNTY_GLOBAL_DATA = 0
COUNTY_NUM_SECTIONS = 4  # model__county

# Waze appelle sa carte mondiale 77001 (editor_main.c, editor_sync.c). En
# gardant ce numéro, la préférence Map.Static County poussée par le catcher
# suffit à faire ouvrir notre carte, sans annuaire de comtés américains.
WORLD_FIPS = 77001

ALIGN_BITS = 2  # structures alignées sur 4 octets

# ── Catégories (roadmap_types.h) ─────────────────────────────────────────────
ROAD_FREEWAY = 1
ROAD_PRIMARY = 2
ROAD_SECONDARY = 3
ROAD_RAMP = 4
ROAD_STREET = 7
ROAD_PEDESTRIAN = 8
ROAD_4X4 = 9
ROAD_TRAIL = 10
ROAD_WALKWAY = 11
CATEGORY_RANGE = 20
DIRECTION_COUNT = 4

NO_SHAPES = 0xFFFF
NO_RANGE = 0xFFFF

# Une référence de point dans une ligne est masquée par POINT_REAL_MASK et le
# bit haut marque un point de bordure de tuile (roadmap_line.h, roadmap_point.h,
# roadmap_screen.c). D'où 32767 points au maximum par tuile.
# roadmap_square.c : le cache de carrés fait 512 entrées hors J2ME, et l'index
# du prochain emplacement libre est un global qui ne décroît jamais. Au-delà,
# l'app passe par l'éviction, un chemin bien moins éprouvé. On reste en deçà.
SQUARE_CACHE_SIZE = 512

POINT_FAKE_FLAG = 0x8000
POINT_REAL_MASK = 0x7FFF
MAX_POINTS_PER_TILE = POINT_REAL_MASK

# Les échelles grossières ne portent que les axes importants : c'est ce qui
# garde le nombre de points sous la limite, et c'est aussi le comportement
# attendu d'un fond de carte dézoomé.
SCALE_MAX_CATEGORY = {0: ROAD_WALKWAY, 1: ROAD_STREET, 2: ROAD_RAMP}


def max_category(scale: int) -> int:
    return SCALE_MAX_CATEGORY.get(scale, ROAD_PRIMARY)

OSM_CATEGORY = {
    "motorway": ROAD_FREEWAY,
    "trunk": ROAD_FREEWAY,
    "motorway_link": ROAD_RAMP,
    "trunk_link": ROAD_RAMP,
    "primary": ROAD_PRIMARY,
    "primary_link": ROAD_RAMP,
    "secondary": ROAD_SECONDARY,
    "secondary_link": ROAD_SECONDARY,
    "tertiary": ROAD_SECONDARY,
    "tertiary_link": ROAD_SECONDARY,
    "residential": ROAD_STREET,
    "unclassified": ROAD_STREET,
    "living_street": ROAD_STREET,
    "road": ROAD_STREET,
    "service": ROAD_STREET,
    "pedestrian": ROAD_PEDESTRIAN,
    "footway": ROAD_PEDESTRIAN,
    "steps": ROAD_PEDESTRIAN,
    "path": ROAD_TRAIL,
    "track": ROAD_4X4,
    "cycleway": ROAD_WALKWAY,
}


# ── Géométrie des tuiles (roadmap_tile.c) ────────────────────────────────────
def _tile_scales() -> list[tuple[int, int, int]]:
    out: list[tuple[int, int, int]] = []
    size, base = 10_000, 0
    while size <= 30_000_000:
        rows = 179_999_999 // size + 1
        cols = 359_999_999 // size + 1
        out.append((size, base, rows))
        base += rows * cols
        size *= 4
    return out


TILE_SCALES = _tile_scales()
MAX_SCALE = len(TILE_SCALES) - 1


def scale_factor(scale: int) -> int:
    return TILE_SCALES[scale][0] // TILE_SCALES[0][0]


def tile_index(lon_u: int, lat_u: int, scale: int) -> tuple[int, int]:
    size = TILE_SCALES[scale][0]
    return (lon_u + 180_000_000) // size, (lat_u + 90_000_000) // size


def tile_id(lon_u: int, lat_u: int, scale: int) -> int:
    size, base, rows = TILE_SCALES[scale]
    lon_i, lat_i = tile_index(lon_u, lat_u, scale)
    return base + lon_i * rows + lat_i


def tile_edges(tid: int) -> tuple[int, int, int, int, int]:
    """(ouest, est, sud, nord, échelle) en micro-degrés."""
    scale = 0
    for s in range(1, len(TILE_SCALES)):
        if TILE_SCALES[s][1] > tid:
            break
        scale = s
    size, base, rows = TILE_SCALES[scale]
    lon_i = (tid - base) // rows
    lat_i = tid - base - lon_i * rows
    west = lon_i * size - 180_000_000
    south = lat_i * size - 90_000_000
    return west, west + size, south, south + size, scale


# ── Écriture binaire ─────────────────────────────────────────────────────────
def pack_payload(sections: dict[int, bytes], num_sections: int = NUM_SECTIONS) -> bytes:
    """En-tête + index des sections + données, comme roadmap_db_fill_data."""
    add = (1 << ALIGN_BITS) - 1
    data = bytearray()
    ends: list[int] = []
    offset = 0
    for i in range(num_sections):
        blob = sections.get(i, b"")
        data.extend(b"\0" * (offset - len(data)))
        data.extend(blob)
        end = offset + len(blob)
        ends.append(end)
        offset = (end + add) & ~add
    head = struct.pack("<II", num_sections, ALIGN_BITS)
    index = b"".join(struct.pack("<I", e) for e in ends)
    return head + index + bytes(data)


def county_index_tile(timestamp: int | None = None) -> bytes:
    """Le fichier `<fips>_index.wdf`, sans lequel la carte n'est jamais ouverte.

    roadmap_locator_open ouvre d'abord la tuile -1 sous RoadMapCountyModel ; ce
    n'est qu'ensuite qu'il appelle roadmap_gzm_open sur le .wzm. Si l'index
    manque, la boucle `while (!roadmap_db_open (fips, -1, ...))` rend
    ROADMAP_US_NOMAP et le paquet de cartes n'est même pas regardé.

    Le modèle « comté » compte quatre sections (roadmap_county_model.h) et
    roadmap_square_map n'en lit qu'une : global_data, un RoadMapGlobal, soit un
    seul entier non signé. Les trois autres (scale, grid, bitmask) restent vides
    — les carrés sont découverts tuile par tuile via le .wzm.
    """
    global_data = struct.pack("<I", timestamp if timestamp is not None else int(time.time()))
    return pack_tile(pack_payload({COUNTY_GLOBAL_DATA: global_data}, COUNTY_NUM_SECTIONS))


def pack_tile(payload: bytes) -> bytes:
    comp = zlib.compress(payload, 9)
    return (
        DATA_SIGNATURE
        + struct.pack("<II", ENDIAN_CORRECT, DATA_VERSION)
        + struct.pack("<II", len(comp), len(payload))
        + comp
    )


def write_wzm(path: Path, tiles: dict[int, bytes], bbox_u: tuple[int, int, int, int]) -> None:
    """tiles : identifiant → payload décompressé. L'index doit être trié."""
    min_lon, min_lat, max_lon, max_lat = bbox_u
    ids = sorted(tiles)
    header = (
        MAP_SIGNATURE
        + struct.pack("<II", ENDIAN_CORRECT, MAP_VERSION)
        + DATA_SIGNATURE
        + struct.pack("<II", ENDIAN_CORRECT, DATA_VERSION)
        + struct.pack("<iiiii", min_lon, min_lat, max_lon, max_lat, len(ids))
    )
    offset = len(header) + 16 * len(ids)
    index = bytearray()
    blobs = bytearray()
    for tid in ids:
        raw = tiles[tid]
        comp = zlib.compress(raw, 9)
        index += struct.pack("<iIII", tid, offset, len(comp), len(raw))
        blobs += comp
        offset += len(comp)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + bytes(index) + bytes(blobs))


# ── Construction d'une tuile ─────────────────────────────────────────────────
class TileBuilder:
    """Accumule points et segments d'une tuile, puis produit son payload.

    Chaque segment devient une ligne droite (first_shape = ROADMAP_LINE_NO_SHAPES).
    C'est visuellement identique à une polyligne et supprime toute la section
    `shape`, dont l'indexation par ligne est la partie la plus fragile du format.
    """

    def __init__(self, tid: int) -> None:
        self.tid = tid
        self.west, self.east, self.south, self.north, self.scale = tile_edges(tid)
        self.factor = scale_factor(self.scale)
        self._points: dict[tuple[int, int], int] = {}
        self._lines: list[tuple[int, int, int]] = []  # (catégorie, depuis, vers)
        self.overflow = False

    def _point(self, lon_u: int, lat_u: int) -> int:
        size = TILE_SCALES[self.scale][0]
        dx = min(max((lon_u - self.west) // self.factor, 0), size // self.factor - 1)
        dy = min(max((lat_u - self.south) // self.factor, 0), size // self.factor - 1)
        key = (dx, dy)
        idx = self._points.get(key)
        if idx is None:
            idx = len(self._points)
            if idx > MAX_POINTS_PER_TILE:
                self.overflow = True
                return -1
            self._points[key] = idx
        return idx

    def add_segment(
        self,
        category: int,
        a: tuple[int, int],
        b: tuple[int, int],
        a_cut: bool = False,
        b_cut: bool = False,
    ) -> None:
        i, j = self._point(*a), self._point(*b)
        if i < 0 or j < 0 or i == j:
            return
        if a_cut:
            i |= POINT_FAKE_FLAG
        if b_cut:
            j |= POINT_FAKE_FLAG
        self._lines.append((category, i, j))

    def __len__(self) -> int:
        return len(self._lines)

    def payload(self, timestamp: int) -> bytes:
        # Les lignes doivent être triées par catégorie : l'index cumulatif
        # next[] de RoadMapLineBySquare délimite chaque catégorie
        # (cf. roadmap_line_cfcc).
        lines = sorted(self._lines, key=lambda l: l[0])

        pts = sorted(self._points.items(), key=lambda kv: kv[1])
        point_data = b"".join(struct.pack("<HH", dx, dy) for (dx, dy), _ in pts)

        line_data = b"".join(
            struct.pack("<HHHH", i, j, NO_SHAPES, NO_RANGE) for _, i, j in lines
        )

        counts = [0] * (CATEGORY_RANGE + 1)
        for cat, _, _ in lines:
            counts[cat] += 1
        cumulative, total = [], 0
        for c in counts:
            total += c
            cumulative.append(total)
        bysquare = (
            b"".join(struct.pack("<H", n) for n in cumulative)
            + struct.pack("<H", 0)  # num_roundabout
            + b"".join(struct.pack("<H", 0) for _ in range(DIRECTION_COUNT * 2 + 1))
        )

        square = struct.pack("<iiI", self.tid, self.scale, timestamp)

        return pack_payload(
            {
                S_POINT_DATA: point_data,
                S_LINE_DATA: line_data,
                S_LINE_BYSQUARE1: bysquare,
                S_SQUARE_DATA: square,
            }
        )


# ── Découpage des voies aux frontières de tuiles ─────────────────────────────
def split_by_tile(a: tuple[int, int], b: tuple[int, int], scale: int):
    """Découpe un segment en morceaux, chacun contenu dans une seule tuile.

    Produit (tuile, début, fin, début_coupé, fin_coupée). Les extrémités
    « coupées » tombent sur une bordure de tuile et reçoivent POINT_FAKE_FLAG,
    ce qui permet au rendu de savoir que la route continue sur la tuile voisine
    (RoadMapScreenLinePoints.real dans roadmap_screen.c).
    """
    size = TILE_SCALES[scale][0]
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    t = 0.0
    guard = 0
    while t < 1.0 and guard < 64:
        guard += 1
        cx = ax + dx * t
        cy = ay + dy * t
        lon_i = int((cx + 180_000_000) // size)
        lat_i = int((cy + 90_000_000) // size)
        west = lon_i * size - 180_000_000
        south = lat_i * size - 90_000_000

        # Paramètre de sortie de la tuile courante.
        t_exit = 1.0
        for delta, lo, hi, cur in ((dx, west, west + size, cx), (dy, south, south + size, cy)):
            if delta > 0:
                t_exit = min(t_exit, t + (hi - cur) / delta)
            elif delta < 0:
                t_exit = min(t_exit, t + (lo - cur) / delta)
        t_exit = min(1.0, max(t_exit, t + 1e-9))

        ex = ax + dx * t_exit
        ey = ay + dy * t_exit
        tid = TILE_SCALES[scale][1] + lon_i * TILE_SCALES[scale][2] + lat_i
        yield tid, (int(cx), int(cy)), (int(ex), int(ey)), t > 0.0, t_exit < 1.0
        t = t_exit


# ── Chargement OSM ───────────────────────────────────────────────────────────
# L'instance principale d'Overpass est souvent saturée et rend 504 sans avoir
# rien calculé. Les miroirs servent exactement la même API.
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


def fetch_overpass(bbox: tuple[float, float, float, float]) -> list[dict]:
    west, south, east, north = bbox
    query = (
        "[out:json][timeout:180];"
        f'way["highway"]({south},{west},{north},{east});'
        "out geom;"
    )
    payload = query.encode("utf-8")
    last = ""

    for attempt in range(2):
        for url in OVERPASS_MIRRORS:
            host = url.split("/")[2]
            try:
                req = urllib.request.Request(
                    url, data=payload, headers={"User-Agent": "waze-ios6-map/1.0"}
                )
                with urllib.request.urlopen(req, timeout=300) as resp:
                    body = resp.read().decode("utf-8")
                print(f"  {host} : {len(body) / 1024:.0f} Kio reçus")
                return json.loads(body).get("elements", [])
            except Exception as exc:  # 504, coupure, JSON tronqué…
                last = f"{host} : {exc}"
                print(f"  {last}", file=sys.stderr)
        if attempt == 0:
            print("  tous les miroirs ont refusé, nouvelle tentative dans 20 s…",
                  file=sys.stderr)
            time.sleep(20)

    raise RuntimeError(
        f"Overpass indisponible ({last}).\n"
        "Réduis la zone (une bbox de 0,3° est déjà grande), réessaie plus tard,\n"
        "ou télécharge toi-même le JSON et repasse-le avec --osm."
    )


def ways_from_elements(elements: list[dict]):
    for el in elements:
        if el.get("type") != "way" or "geometry" not in el:
            continue
        highway = el.get("tags", {}).get("highway", "")
        category = OSM_CATEGORY.get(highway, ROAD_STREET)
        coords = [
            (int(round(g["lon"] * 1e6)), int(round(g["lat"] * 1e6)))
            for g in el["geometry"]
        ]
        if len(coords) >= 2:
            yield category, coords


# ── Assemblage ───────────────────────────────────────────────────────────────
def build_tiles(ways, scales: list[int]) -> dict[int, TileBuilder]:
    tiles: dict[int, TileBuilder] = {}
    for category, coords in ways:
        for scale in scales:
            if category > max_category(scale):
                continue
            for a, b in zip(coords, coords[1:]):
                for tid, sa, sb, a_cut, b_cut in split_by_tile(a, b, scale):
                    builder = tiles.get(tid)
                    if builder is None:
                        builder = tiles[tid] = TileBuilder(tid)
                    builder.add_segment(category, sa, sb, a_cut, b_cut)

    saturated = [tid for tid, b in tiles.items() if b.overflow]
    if saturated:
        print(
            f"  {len(saturated)} tuile(s) saturée(s) à {MAX_POINTS_PER_TILE} points "
            "— géométrie tronquée. Réduis --max-scale ou la zone.",
            file=sys.stderr,
        )
    return {tid: b for tid, b in tiles.items() if len(b)}


# Taille des structures C de chaque section. roadmap_db_get_data refuse une
# section dont la taille n'est pas un multiple exact, et pour les points comme
# pour le carré l'échec est traité en ROADMAP_FATAL — donc l'app se ferme.
SECTION_ITEM_SIZE = {
    S_POINT_DATA: 4,        # RoadMapPoint   : 2 × unsigned short
    S_POINT_ID: 4,          # int
    S_LINE_DATA: 8,         # RoadMapLine    : 4 × unsigned short
    S_LINE_BYSQUARE1: (CATEGORY_RANGE + 1) * 2 + 2 + (DIRECTION_COUNT * 2 + 1) * 2,
    S_SQUARE_DATA: 12,      # RoadMapSquare  : 2 × int + unsigned int
    S_METADATA_ATTRIBUTES: 8,  # RoadMapAttribute : 4 × RoadMapString
}


def verify_tile(tid: int, payload: bytes) -> list[str]:
    """Rejoue les contrôles que le client fera, et rend la liste des problèmes.

    Mieux vaut échouer ici que sur l'iPhone : une tuile invalide n'y produit pas
    un message d'erreur mais un arrêt brutal, et roadmap_db_open efface au
    passage le fichier fautif.
    """
    problems: list[str] = []
    parsed = read_tile(pack_tile(payload))
    sections = parsed["sections"]

    if parsed["num_sections"] != NUM_SECTIONS:
        problems.append(f"{parsed['num_sections']} sections au lieu de {NUM_SECTIONS}")

    for sid, item in SECTION_ITEM_SIZE.items():
        n = len(sections.get(sid, b""))
        if n % item:
            problems.append(f"section {sid} : {n} octets, pas un multiple de {item}")

    square = sections.get(S_SQUARE_DATA, b"")
    if len(square) != 12:
        problems.append(f"square/data fait {len(square)} octets au lieu de 12")
    else:
        sq_id, sq_scale, _ = struct.unpack("<iiI", square)
        _, _, _, _, scale = tile_edges(tid)
        if sq_id != tid:
            problems.append(f"square_id {sq_id} ≠ tuile {tid}")
        if sq_scale != scale:
            problems.append(f"scale {sq_scale} ≠ {scale} déduit de l'identifiant")

    points = sections.get(S_POINT_DATA, b"")
    lines = sections.get(S_LINE_DATA, b"")
    n_points = len(points) // 4
    n_lines = len(lines) // 8

    # roadmap_point_position indexe sans borne hors DEBUG : un index trop grand
    # lit hors du tampon.
    for k in range(n_lines):
        frm, to, _, _ = struct.unpack("<HHHH", lines[k * 8 : k * 8 + 8])
        for label, raw in (("from", frm), ("to", to)):
            idx = raw & POINT_REAL_MASK
            if idx >= n_points:
                problems.append(
                    f"ligne {k} {label} pointe {idx}, or la tuile a {n_points} points"
                )
                break

    bysquare = sections.get(S_LINE_BYSQUARE1, b"")
    if n_lines and len(bysquare) != SECTION_ITEM_SIZE[S_LINE_BYSQUARE1]:
        problems.append("des lignes sans index bysquare1 : NULL déréférencé au chargement")
    elif bysquare:
        cumulative = struct.unpack(f"<{CATEGORY_RANGE + 1}H", bysquare[: (CATEGORY_RANGE + 1) * 2])
        if cumulative[CATEGORY_RANGE] != n_lines:
            problems.append(
                f"index cumulatif annonce {cumulative[CATEGORY_RANGE]} lignes, "
                f"il y en a {n_lines}"
            )
        if list(cumulative) != sorted(cumulative):
            problems.append("index cumulatif non croissant")

    return problems


# ── Relecture, avec exactement les contrôles du client ───────────────────────
def read_tile(blob: bytes) -> dict:
    if len(blob) < TILE_HEADER_LEN:
        raise ValueError("en-tête trop court")
    sig = blob[:4]
    endian, version, comp_size, raw_size = struct.unpack("<IIII", blob[4:20])
    if sig != DATA_SIGNATURE:
        raise ValueError(f"signature {sig!r}")
    if endian != ENDIAN_CORRECT:
        raise ValueError(f"endianness {endian:#x}")
    if version != DATA_VERSION:
        raise ValueError(f"version {version:#x}")
    if comp_size != len(blob) - TILE_HEADER_LEN:
        raise ValueError(f"taille compressée {comp_size} ≠ {len(blob) - TILE_HEADER_LEN}")
    raw = zlib.decompress(blob[TILE_HEADER_LEN:])
    if len(raw) != raw_size:
        raise ValueError(f"taille décompressée {len(raw)} ≠ {raw_size}")

    num_sections, align_bits = struct.unpack("<II", raw[:8])
    idx_end = 8 + num_sections * 4
    if len(raw) < idx_end:
        raise ValueError("index tronqué")
    ends = list(struct.unpack(f"<{num_sections}I", raw[8:idx_end]))
    if num_sections and len(raw) < idx_end + ends[-1]:
        raise ValueError("données tronquées")

    add = (1 << align_bits) - 1
    data = raw[idx_end:]
    sections = {}
    for i in range(num_sections):
        start = 0 if i == 0 else (ends[i - 1] + add) & ~add
        sections[i] = data[start : ends[i]]
    return {"num_sections": num_sections, "sections": sections, "raw_size": raw_size}


def read_wzm(path: Path) -> dict:
    blob = path.read_bytes()
    if blob[:4] != MAP_SIGNATURE:
        raise ValueError(f"signature {blob[:4]!r}")
    endian, version = struct.unpack("<II", blob[4:12])
    if endian != ENDIAN_CORRECT:
        raise ValueError(f"endianness {endian:#x}")
    if version != MAP_VERSION:
        raise ValueError(f"version {version:#x}")
    min_lon, min_lat, max_lon, max_lat, num_tiles = struct.unpack("<iiiii", blob[24:44])
    entries = []
    for i in range(num_tiles):
        off = 44 + 16 * i
        entries.append(struct.unpack("<iIII", blob[off : off + 16]))
    if [e[0] for e in entries] != sorted(e[0] for e in entries):
        raise ValueError("index non trié (la recherche dichotomique échouerait)")
    for tid, off, comp, raw_size in entries:
        header = (
            DATA_SIGNATURE
            + struct.pack("<IIII", ENDIAN_CORRECT, DATA_VERSION, comp, raw_size)
        )
        read_tile(header + blob[off : off + comp])
    return {
        "bbox": (min_lon, min_lat, max_lon, max_lat),
        "num_tiles": num_tiles,
        "entries": entries,
        "size": len(blob),
    }


# ── Commandes ────────────────────────────────────────────────────────────────
def cmd_selftest() -> int:
    print("Contrôle du calcul de tuile (roadmap_tile.c)")
    got = tile_id(6_484_638, 46_364_603, 0)
    assert got == 335677636, got
    west, east, south, north, scale = tile_edges(got)
    assert scale == 0 and west <= 6_484_638 < east and south <= 46_364_603 < north
    print(f"  Lausanne échelle 0 → {got}, bords {west}..{east} / {south}..{north}  OK")

    print("Construction d'une tuile de test")
    builder = TileBuilder(got)
    base_lon, base_lat = west + 1000, south + 1000
    for k in range(40):
        builder.add_segment(
            ROAD_STREET if k % 2 else ROAD_PRIMARY,
            (base_lon + k * 100, base_lat + k * 60),
            (base_lon + (k + 1) * 100, base_lat + (k + 1) * 60),
        )
    payload = builder.payload(int(time.time()))
    blob = pack_tile(payload)
    parsed = read_tile(blob)
    assert parsed["num_sections"] == NUM_SECTIONS
    lines = parsed["sections"][S_LINE_DATA]
    points = parsed["sections"][S_POINT_DATA]
    assert len(lines) == 40 * 8, len(lines)
    assert len(points) % 4 == 0
    square = struct.unpack("<iiI", parsed["sections"][S_SQUARE_DATA])
    assert square[0] == got and square[1] == 0
    print(f"  {len(lines)//8} lignes, {len(points)//4} points, {len(blob)} octets  OK")

    print("Contrôle de l'index cumulatif par catégorie")
    bysquare = parsed["sections"][S_LINE_BYSQUARE1]
    assert len(bysquare) == (CATEGORY_RANGE + 1) * 2 + 2 + (DIRECTION_COUNT * 2 + 1) * 2
    cumulative = struct.unpack(f"<{CATEGORY_RANGE + 1}H", bysquare[: (CATEGORY_RANGE + 1) * 2])
    assert cumulative[CATEGORY_RANGE] == 40, cumulative
    assert cumulative[ROAD_PRIMARY] == 20, cumulative
    print(f"  cumul {cumulative[:8]}…  total {cumulative[CATEGORY_RANGE]}  OK")

    print("Découpage d'un segment traversant plusieurs tuiles")
    pieces = list(split_by_tile((6_480_000, 46_360_000), (6_530_000, 46_395_000), 0))
    assert len({p[0] for p in pieces}) >= 4, pieces
    print(f"  {len(pieces)} morceaux sur {len({p[0] for p in pieces})} tuiles  OK")

    print("Écriture puis relecture d'un paquet .wzm")
    out = ROOT / "logs" / "selftest.wzm"
    write_wzm(out, {got: payload}, (west, south, east, north))
    info = read_wzm(out)
    assert info["num_tiles"] == 1
    print(f"  {out.name}: {info['num_tiles']} tuile, {info['size']} octets  OK")
    out.unlink()

    print("Contrôle des identifiants entre échelles")
    seen: dict[int, int] = {}
    for scale in range(len(TILE_SCALES)):
        for lon in range(-170_000_000, 170_000_000, 37_000_000):
            for lat in range(-80_000_000, 80_000_000, 29_000_000):
                tid = tile_id(lon, lat, scale)
                if tid in seen and seen[tid] != scale:
                    raise AssertionError(f"tuile {tid} partagée par {seen[tid]} et {scale}")
                seen[tid] = scale
                assert tile_edges(tid)[4] == scale, (tid, scale)
    print(f"  {len(seen)} identifiants, aucune collision entre échelles  OK")

    print("Contrôle de validation d'une tuile (verify_tile)")
    assert verify_tile(got, payload) == [], verify_tile(got, payload)
    corrupt = dict(
        {
            S_POINT_DATA: struct.pack("<HH", 0, 0),
            S_LINE_DATA: struct.pack("<HHHH", 0, 5, NO_SHAPES, NO_RANGE),
            S_SQUARE_DATA: struct.pack("<iiI", got, 0, 0),
        }
    )
    found = verify_tile(got, pack_payload(corrupt))
    assert any("pointe 5" in p for p in found), found
    print(f"  tuile saine acceptée, tuile fautive rejetée ({found[0]})  OK")

    print("Contrôle de l'index de carte (roadmap_square_map)")
    idx = read_tile(county_index_tile(1234567890))
    assert idx["num_sections"] == COUNTY_NUM_SECTIONS, idx["num_sections"]
    global_data = idx["sections"][COUNTY_GLOBAL_DATA]
    # roadmap_db_get_data échoue si la taille n'est pas un multiple exact de
    # sizeof(RoadMapGlobal), et roadmap_square_map traite l'échec en FATAL.
    assert len(global_data) == 4, len(global_data)
    assert struct.unpack("<I", global_data)[0] == 1234567890
    print(f"  {COUNTY_NUM_SECTIONS} sections, global_data {len(global_data)} octets  OK")

    print("\nTous les contrôles passent.")
    return 0


def cmd_build(args) -> int:
    if args.osm:
        elements = json.loads(Path(args.osm).read_text(encoding="utf-8")).get("elements", [])
        print(f"{len(elements)} éléments lus depuis {args.osm}")
    else:
        west, south, east, north = (float(v) for v in args.bbox.split(","))
        print(f"Interrogation d'Overpass pour {west},{south},{east},{north}…")
        try:
            elements = fetch_overpass((west, south, east, north))
        except RuntimeError as exc:
            print(f"\n{exc}", file=sys.stderr)
            return 1
        print(f"{len(elements)} éléments reçus")
        # Un téléchargement réussi ne se reperd pas : si la suite échoue ou si
        # tu veux réessayer avec d'autres options, --osm repart de ce fichier.
        cache = ROOT / "logs" / f"osm-{args.name}.json"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"elements": elements}), encoding="utf-8")
        print(f"  copie gardée dans {cache} (réutilisable avec --osm)")

    ways = list(ways_from_elements(elements))
    if not ways:
        print("Aucune route trouvée — vérifie la zone.", file=sys.stderr)
        return 1
    print(f"{len(ways)} voies")

    scales = list(range(args.max_scale + 1))
    tiles = build_tiles(ways, scales)
    print(f"{len(tiles)} tuiles sur {len(scales)} échelle(s)")

    timestamp = int(time.time())
    payloads = {tid: b.payload(timestamp) for tid, b in tiles.items()}

    bad = 0
    for tid, payload in payloads.items():
        for problem in verify_tile(tid, payload):
            if bad < 10:
                print(f"  tuile {tid} : {problem}", file=sys.stderr)
            bad += 1
    if bad:
        print(
            f"\n{bad} problème(s) : la carte ferait planter Waze, rien n'est écrit.",
            file=sys.stderr,
        )
        return 1
    print(f"  {len(payloads)} tuiles vérifiées, aucune anomalie")

    if len(payloads) > SQUARE_CACHE_SIZE:
        print(
            f"\n  ATTENTION : {len(payloads)} tuiles pour un cache de "
            f"{SQUARE_CACHE_SIZE} (roadmap_square.c).",
            file=sys.stderr,
        )
        print(
            "  Réduis --max-scale ou la zone. Une carte plus grande que le cache\n"
            "  force l'éviction de carrés, ce que cette version gère mal.",
            file=sys.stderr,
        )

    lons = [c[0] for _, coords in ways for c in coords]
    lats = [c[1] for _, coords in ways for c in coords]
    bbox_u = (min(lons), min(lats), max(lons), max(lats))

    out = ROOT / "maps" / args.name / f"map{args.fips:05d}.wzm"
    write_wzm(out, payloads, bbox_u)
    info = read_wzm(out)

    index = out.parent / f"{args.fips:05d}_index.wdf"
    index.write_bytes(county_index_tile(timestamp))

    print(f"\n{out}")
    print(f"  {info['num_tiles']} tuiles, {info['size'] / 1024:.1f} Kio — relecture OK")
    print(f"{index}")
    print(f"  index de carte, {index.stat().st_size} octets")
    print(f"\nLes deux fichiers vont ensemble :  sh maps.sh {args.name}")
    return 0


def main() -> int:
    # Console Windows en cp1252 ou shell sans locale UTF-8 : ne jamais planter
    # sur un accent en plein milieu d'une génération de carte.
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("selftest", help="vérifie le format sans réseau")

    build = sub.add_parser("build", help="construit un paquet .wzm")
    build.add_argument("--bbox", help="ouest,sud,est,nord en degrés")
    build.add_argument("--osm", help="fichier JSON Overpass déjà téléchargé")
    build.add_argument("--name", required=True, help="nom de région (dossier)")
    build.add_argument(
        "--fips",
        type=int,
        default=WORLD_FIPS,
        help=f"identifiant de carte (défaut {WORLD_FIPS}, la carte monde de Waze)",
    )
    build.add_argument("--max-scale", type=int, default=2, help="échelles 0..N")

    args = parser.parse_args()
    if args.cmd == "selftest":
        return cmd_selftest()
    if args.cmd == "build":
        if not args.bbox and not args.osm:
            parser.error("--bbox ou --osm est requis")
        return cmd_build(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
