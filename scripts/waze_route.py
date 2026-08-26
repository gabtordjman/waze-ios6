#!/usr/bin/env python3
"""Itinéraire Waze 2.4 : RoutePoints (dézoom) + segments du .wzm (zoom rue).

GPL navigate_main_screen_repaint() (navigate_main.c) :
- zoom ≥ 100 + RoutePoints → outline OSRM puis return
- zoom < 100 → uniquement les segments is_instrumented

instrument_segments() refuse line_id < 0, et n'instrumente pas une tuile
tant que la précédente ne l'est pas. Un snap trop large accroche des rues
à des kilomètres → morceaux violets partout. Distance = segment .wzm contre
segment OSRM. Une ligne n'est candidate que si ses deux bouts et son
milieu collent au couloir OSRM (~40 m) : sinon une parallèle / ruelle
qui touche le carrefour gagne. Même tuile : nœud .wzm partagé. from_node_id
= vrai nœud .wzm (WITH/AGAINST).
"""

from __future__ import annotations

import json
import math
import struct
import threading
from collections import defaultdict, deque
from pathlib import Path

OSRM = "https://router.project-osrm.org/route/v1/driving"
UA = "Relight/1.0.2 (waze-ios6)"
ROOT = Path(__file__).resolve().parents[1]
WZM = ROOT / "maps" / "auto" / "map77001.wzm"
OSM_CACHES = (
    ROOT / "logs" / "osm-auto.json",
    ROOT / "logs" / "osm-mini.json",
    ROOT / "logs" / "osm-_auto_build.json",
)

ROUTE_ORIGINAL = 1
TURN_LEFT = 0
TURN_RIGHT = 1
KEEP_LEFT = 2
KEEP_RIGHT = 3
CONTINUE = 4
ROUNDABOUT_ENTER = 5
ROUNDABOUT_EXIT = 6
ROUNDABOUT_LEFT = 7
ROUNDABOUT_EXIT_LEFT = 8
ROUNDABOUT_STRAIGHT = 9
ROUNDABOUT_EXIT_STRAIGHT = 10
ROUNDABOUT_RIGHT = 11
ROUNDABOUT_EXIT_RIGHT = 12
ROUNDABOUT_U = 13
ROUNDABOUT_EXIT_U = 14
APPROACHING_DESTINATION = 15
EXIT_LEFT = 16
EXIT_RIGHT = 17


def _wire(instr: int) -> int:
    """Serveur : 0 → CONTINUE, sinon enum+1."""
    return 0 if instr == 4 else instr + 1


def _ascii(s: str) -> str:
    if not s:
        return ""
    repl = str.maketrans(
        "àáâãäåèéêëìíîïòóôõöùúûüýÿñçÀÁÂÃÄÅÈÉÊËÌÍÎÏÒÓÔÕÖÙÚÛÜÝŸÑÇ",
        "aaaaaaeeeeiiiiooooouuuuyyncAAAAAAEEEEIIIIOOOOOUUUUYYNC",
    )
    out = s.translate(repl).encode("ascii", "ignore").decode("ascii")
    return out.replace(",", " ").replace("\r", " ").replace("\n", " ").strip()[:80]


def _osrm_maneuver(man: dict) -> int:
    typ = (man.get("type") or "").lower().replace("_", " ")
    mod = (man.get("modifier") or "").lower().replace("_", " ")
    if typ == "arrive":
        return APPROACHING_DESTINATION
    if "roundabout" in typ or typ in ("rotary", "exit rotary"):
        exiting = typ.startswith("exit")
        if "left" in mod:
            return ROUNDABOUT_EXIT_LEFT if exiting else ROUNDABOUT_LEFT
        if "right" in mod:
            return ROUNDABOUT_EXIT_RIGHT if exiting else ROUNDABOUT_RIGHT
        if "straight" in mod or "through" in mod:
            return ROUNDABOUT_EXIT_STRAIGHT if exiting else ROUNDABOUT_STRAIGHT
        return ROUNDABOUT_EXIT if exiting else ROUNDABOUT_ENTER
    if "uturn" in mod or "u-turn" in mod:
        return ROUNDABOUT_U
    if typ in ("depart", "continue", "new name", "notification"):
        if "slight left" in mod or mod == "left":
            return KEEP_LEFT
        if "slight right" in mod or mod == "right":
            return KEEP_RIGHT
        return CONTINUE
    left = "left" in mod
    right = "right" in mod
    slight = "slight" in mod
    if typ in ("off ramp", "fork") and left:
        return EXIT_LEFT
    if typ in ("off ramp", "fork") and right:
        return EXIT_RIGHT
    if left:
        return KEEP_LEFT if slight else TURN_LEFT
    if right:
        return KEEP_RIGHT if slight else TURN_RIGHT
    return CONTINUE


def _resample_pts(
    pts: list[tuple[int, int]], target: int
) -> list[tuple[int, int]]:
    """Garde début, fin, et les coudes. Un step uniforme lissait trop les courbes."""
    n = len(pts)
    if n <= target:
        return pts
    must = {0, n - 1}
    for i in range(1, n - 1):
        b1 = _bearing(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1])
        b2 = _bearing(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
        d = (b2 - b1 + 540.0) % 360.0 - 180.0
        if abs(d) >= 10:
            must.add(i)
    if len(must) >= target:
        ordered = sorted(must)
        picked = [ordered[0]]
        step = (len(ordered) - 1) / max(target - 1, 1)
        for k in range(1, target - 1):
            picked.append(ordered[min(int(round(k * step)), len(ordered) - 1)])
        picked.append(ordered[-1])
        out: list[tuple[int, int]] = []
        for i in picked:
            if not out or pts[i] != out[-1]:
                out.append(pts[i])
        return out
    chosen = set(must)
    rest = [i for i in range(n) if i not in must]
    extra = target - len(must)
    if rest and extra > 0:
        step = len(rest) / extra
        for k in range(extra):
            chosen.add(rest[min(int(k * step), len(rest) - 1)])
    return [pts[i] for i in sorted(chosen)]


def osrm_route(
    lon1: float, lat1: float, lon2: float, lat2: float
) -> tuple[list[tuple[int, int]], int, int, list[dict]] | None:
    import urllib.request

    path = f"{lon1:.6f},{lat1:.6f};{lon2:.6f},{lat2:.6f}"
    url = f"{OSRM}/{path}?overview=full&geometries=geojson&steps=true"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    routes = data.get("routes") or []
    if not routes:
        return None
    r0 = routes[0]
    coords = (r0.get("geometry") or {}).get("coordinates") or []
    if len(coords) < 2:
        return None

    length_m = float(r0.get("distance") or 0)
    all_pts = [
        (int(round(c[0] * 1e6)), int(round(c[1] * 1e6))) for c in coords
    ]
    origin = (int(round(lon1 * 1e6)), int(round(lat1 * 1e6)))
    dest = (int(round(lon2 * 1e6)), int(round(lat2 * 1e6)))
    if not all_pts or all_pts[0] != origin:
        all_pts.insert(0, origin)
    if all_pts[-1] != dest:
        all_pts.append(dest)
    # Assez dense pour coller aux rues, assez court pour le fil RoutePoints.
    # Un step entier laissait 458 pts (le client retente : réponse trop longue).
    target = max(80, min(140, int(length_m / 12) + 2))
    pts = _resample_pts(all_pts, target)

    steps: list[dict] = []
    for leg in r0.get("legs") or []:
        for st in leg.get("steps") or []:
            man = st.get("maneuver") or {}
            loc = man.get("location") or []
            if len(loc) < 2:
                continue
            steps.append(
                {
                    "lon": int(round(float(loc[0]) * 1e6)),
                    "lat": int(round(float(loc[1]) * 1e6)),
                    "instr": _osrm_maneuver(man),
                    "name": _ascii(st.get("name") or ""),
                    "dist": int(round(float(st.get("distance") or 0))),
                    "time": int(round(float(st.get("duration") or 0))),
                }
            )

    length = int(round(length_m))
    duration = int(round(float(r0.get("duration") or 0)))
    return pts, length, duration, steps


_lines_cache: tuple[tuple, list[tuple]] | None = None
_names_cache: tuple[float, list[tuple[int, int, str]]] | None = None


def _osm_cache_path() -> Path | None:
    for p in OSM_CACHES:
        if p.is_file():
            return p
    return None


def _load_osm_names() -> list[tuple[int, int, str]]:
    global _names_cache
    path = _osm_cache_path()
    if not path:
        return []
    mtime = path.stat().st_mtime
    if _names_cache and _names_cache[0] == mtime:
        return _names_cache[1]
    try:
        elements = json.loads(path.read_text(encoding="utf-8")).get("elements", [])
    except Exception:
        return []
    out: list[tuple[int, int, str]] = []
    for el in elements:
        if el.get("type") != "way":
            continue
        tags = el.get("tags") or {}
        name = _ascii(tags.get("name") or tags.get("name:fr") or "")
        if not name:
            continue
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        mid = geom[len(geom) // 2]
        try:
            lon_u = int(round(float(mid["lon"]) * 1e6))
            lat_u = int(round(float(mid["lat"]) * 1e6))
        except (KeyError, TypeError, ValueError):
            continue
        out.append((lon_u, lat_u, name))
    _names_cache = (mtime, out)
    return out


def _name_near(lon: int, lat: int, names: list[tuple[int, int, str]]) -> str:
    best, best_d = "", 10**18
    for nlon, nlat, name in names:
        d = abs(nlon - lon) + abs(nlat - lat)
        if d < best_d:
            best_d = d
            best = name
    return best if best_d < 120_000 else ""


_wzm_diag_cache: tuple[tuple, str] | None = None


def invalidate_map() -> None:
    """Après fusion Overpass : recharger le .wzm."""
    global _lines_cache, _wzm_diag_cache, _names_cache
    _lines_cache = None
    _wzm_diag_cache = None
    _names_cache = None
    try:
        with _route_lock:
            _route_cache.clear()
    except NameError:
        pass


def wzm_status_line(lon: float | None = None, lat: float | None = None) -> str:
    """Une ligne pour le catcher : taille, rues échelle 0, tuile GPS."""
    global _wzm_diag_cache
    if not WZM.is_file():
        return f"  wzm ABSENT {WZM}"
    mtime = WZM.stat().st_mtime
    key = (mtime, lon, lat)
    if _wzm_diag_cache and _wzm_diag_cache[0] == key:
        return _wzm_diag_cache[1]
    try:
        from wazemap import summarize_wzm  # type: ignore

        s = summarize_wzm(WZM, lon, lat)
    except Exception as e:
        msg = f"  wzm {WZM.name} inspect FAIL {type(e).__name__}: {e}"
        _wzm_diag_cache = (key, msg)
        return msg
    s0 = s["scales"][0]
    msg = (
        f"  wzm {WZM.name} {s['size'] // 1024}K "
        f"s0={s0['lines']} lignes/{s0['with_lines']} tuiles "
        f"vide={s0['empty']}"
    )
    if s["gps_tid"] is not None:
        if not s["gps_inside"]:
            msg += f" GPS hors bbox tuile={s['gps_tid']}"
        else:
            msg += f" GPS tuile {s['gps_tid']}={s['gps_lines']} ligne(s)"
    if s0["lines"] == 0:
        msg += " — ÉCHELLE 0 VIDE (écran néant au zoom rue)"
    _wzm_diag_cache = (key, msg)
    return msg


def _load_line_index(
    *,
    bbox: tuple[int, int, int, int] | None = None,
) -> list[tuple]:
    """(tid, line_i, ts, mid_lon, mid_lat, len_m, elon, elat, blon, blat).

    Si bbox=(w,s,e,n) en µ°, n'indexe que les tuiles qui l'intersectent.
    """
    global _lines_cache
    if not WZM.is_file():
        return []
    mtime = WZM.stat().st_mtime
    cache_key = (mtime, bbox)
    if _lines_cache and _lines_cache[0] == cache_key:
        return _lines_cache[1]

    from wazemap import (  # type: ignore
        DATA_SIGNATURE,
        DATA_VERSION,
        ENDIAN_CORRECT,
        POINT_REAL_MASK,
        S_LINE_DATA,
        S_POINT_DATA,
        S_SQUARE_DATA,
        TILE_SCALES,
        read_tile,
        read_wzm,
        scale_factor,
        tile_edges,
    )

    info = read_wzm(WZM)
    blob = WZM.read_bytes()
    out: list[tuple] = []
    scale0_hi = TILE_SCALES[1][1]
    bw = bs = be = bn = None
    if bbox:
        bw, bs, be, bn = bbox

    for tid, off, csz, rsz in info["entries"]:
        if tid >= scale0_hi:
            continue  # échelle 0 seulement (zoom rue)
        west, east, south, north, _ = tile_edges(tid)
        if bw is not None and (east < bw or west > be or north < bs or south > bn):
            continue
        header = (
            DATA_SIGNATURE
            + struct.pack("<IIII", ENDIAN_CORRECT, DATA_VERSION, csz, rsz)
        )
        try:
            sections = read_tile(header + blob[off : off + csz])["sections"]
        except Exception:
            continue
        square = sections.get(S_SQUARE_DATA, b"")
        lines = sections.get(S_LINE_DATA, b"")
        points = sections.get(S_POINT_DATA, b"")
        if len(square) < 12 or len(lines) < 8 or len(points) < 4:
            continue
        _tid, scale, ts = struct.unpack("<iiI", square[:12])
        factor = scale_factor(scale)
        n_pts = len(points) // 4

        def abs_xy(idx: int, _w=west, _s=south, _f=factor, _pts=points, _n=n_pts) -> tuple[int, int]:
            idx &= POINT_REAL_MASK
            if idx >= _n:
                return _w, _s
            dx, dy = struct.unpack("<HH", _pts[idx * 4 : idx * 4 + 4])
            return _w + dx * _f, _s + dy * _f

        n_lines = len(lines) // 8
        for li in range(n_lines):
            frm, to, _fs, _rg = struct.unpack("<HHHH", lines[li * 8 : li * 8 + 8])
            lon1, lat1 = abs_xy(frm)
            lon2, lat2 = abs_xy(to)
            mid_lon = (lon1 + lon2) // 2
            mid_lat = (lat1 + lat2) // 2
            approx = max(int((abs(lon1 - lon2) + abs(lat1 - lat2)) * 0.11), 1)
            out.append(
                (
                    tid,
                    li,
                    ts,
                    mid_lon,
                    mid_lat,
                    approx,
                    lon2,
                    lat2,
                    lon1,
                    lat1,
                    frm & POINT_REAL_MASK,
                    to & POINT_REAL_MASK,
                )
            )

    _lines_cache = (cache_key, out)
    if not out:
        print(
            f"  matcher index vide (wzm={'oui' if WZM.is_file() else 'non'} "
            f"{WZM.stat().st_size if WZM.is_file() else 0}B, bbox={bbox})",
            flush=True,
        )
    return out


def _bearing(lon1: int, lat1: int, lon2: int, lat2: int) -> float:
    dlon = math.radians((lon2 - lon1) / 1e6)
    la1 = math.radians(lat1 / 1e6)
    la2 = math.radians(lat2 / 1e6)
    y = math.sin(dlon) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _ang_diff(a: float, b: float) -> float:
    return abs((b - a + 540.0) % 360.0 - 180.0)


def _dist_to_seg(
    lon: int, lat: int, a: tuple[int, int], b: tuple[int, int]
) -> int:
    x1, y1 = a
    x2, y2 = b
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return abs(lon - x1) + abs(lat - y1)
    t = max(0.0, min(1.0, ((lon - x1) * dx + (lat - y1) * dy) / (dx * dx + dy * dy)))
    px, py = x1 + t * dx, y1 + t * dy
    return int(abs(lon - px) + abs(lat - py))


def _ends(row: tuple) -> tuple[tuple[int, int], tuple[int, int]]:
    return (row[8], row[9]), (row[6], row[7])


def _min_end_gap(a: tuple, b: tuple) -> int:
    ea, eb = _ends(a), _ends(b)
    return min(abs(p[0] - q[0]) + abs(p[1] - q[1]) for p in ea for q in eb)


SNAP_U = 900  # ~100 m : assez pour l'OSRM qui coupe un coin, pas une parallèle
JOIN_U = 450
HEADING_MAX = 42.0
LOOK_U = 1_400  # ~150 m d'OSRM devant pour décider un vrai virage
SWITCH_MARGIN = 280  # rester sur la rue tant que l'autre n'est pas nettement mieux
CORRIDOR_U = 300  # ~33 m : coller à l'OSRM sans ruelle parallèle


def _seg_seg(
    a1: tuple[int, int],
    a2: tuple[int, int],
    b1: tuple[int, int],
    b2: tuple[int, int],
) -> int:
    return min(
        _dist_to_seg(a1[0], a1[1], b1, b2),
        _dist_to_seg(a2[0], a2[1], b1, b2),
        _dist_to_seg(b1[0], b1[1], a1, a2),
        _dist_to_seg(b2[0], b2[1], a1, a2),
    )


def _line_to_osrm(row: tuple, a: tuple[int, int], b: tuple[int, int]) -> int:
    """Distance entre le segment .wzm (bouts) et le segment OSRM courant."""
    return _seg_seg((row[8], row[9]), (row[6], row[7]), a, b)


def _heading_err(row: tuple, brg: float) -> float:
    line_brg = _bearing(row[8], row[9], row[6], row[7])
    return min(
        _ang_diff(brg, line_brg),
        _ang_diff(brg, (line_brg + 180.0) % 360.0),
    )


def _osrm_window_cost(
    row: tuple, pts: list[tuple[int, int]], i: int, look_u: int = LOOK_U
) -> int:
    """Éloignement moyen de la ligne aux ~look_u µ° d'OSRM devant le point i."""
    if len(pts) < 2:
        return 10**9
    if i >= len(pts) - 1:
        return _line_to_osrm(row, pts[-2], pts[-1])
    acc = 0
    n = 0
    traveled = 0
    j = i
    while j < len(pts) - 1:
        acc += _line_to_osrm(row, pts[j], pts[j + 1])
        n += 1
        traveled += abs(pts[j + 1][0] - pts[j][0]) + abs(pts[j + 1][1] - pts[j][1])
        if traveled >= look_u:
            break
        j += 1
    return acc // max(n, 1)


def _dist_to_poly(lon: int, lat: int, pts: list[tuple[int, int]]) -> int:
    best = 10**18
    for j in range(len(pts) - 1):
        d = _dist_to_seg(lon, lat, pts[j], pts[j + 1])
        if d < best:
            best = d
            if d == 0:
                return 0
    return best


def _nearest_pt_idx(lon: int, lat: int, pts: list[tuple[int, int]]) -> int:
    best, bi = 10**18, 0
    for i, (x, y) in enumerate(pts):
        d = abs(x - lon) + abs(y - lat)
        if d < best:
            best, bi = d, i
    return bi


def _poly_arclen(pts: list[tuple[int, int]], i: int, j: int) -> float:
    if i > j:
        i, j = j, i
    acc = 0.0
    for k in range(i, j):
        acc += math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1])
    return acc


def _on_corridor(
    row: tuple, pts: list[tuple[int, int]], max_d: int = CORRIDOR_U
) -> bool:
    """True si la ligne *suit* l'OSRM, pas seulement si elle le touche.

    Les deux bouts sur le couloir. Le milieu de la *corde* n'est pas exigé :
    une courbe (Chemin de Ronde) a le milieu à l'intérieur, ça faisait des
    trous. Un raccourci à travers un pâté a une corde trop courte vs l'OSRM.
    """
    if len(pts) < 2:
        return False
    x1, y1, x2, y2 = row[8], row[9], row[6], row[7]

    def check(ax: int, ay: int, bx: int, by: int) -> bool:
        if _dist_to_poly(ax, ay, pts) > max_d or _dist_to_poly(bx, by, pts) > max_d:
            return False
        chord = math.hypot(bx - ax, by - ay)
        if chord < 900:
            return True
        i1 = _nearest_pt_idx(ax, ay, pts)
        i2 = _nearest_pt_idx(bx, by, pts)
        arc = _poly_arclen(pts, i1, i2)
        if arc < 1:
            return True
        return chord >= 0.60 * arc

    if check(x1, y1, x2, y2):
        return True
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    west, east = min(lons) - max_d, max(lons) + max_d
    south, north = min(lats) - max_d, max(lats) + max_d
    line_len = abs(x2 - x1) + abs(y2 - y1)
    span = (east - west) + (north - south)
    if line_len < span:
        return False
    cx1, cy1 = max(west, min(east, x1)), max(south, min(north, y1))
    cx2, cy2 = max(west, min(east, x2)), max(south, min(north, y2))
    if (cx1, cy1) == (cx2, cy2):
        return False
    return check(cx1, cy1, cx2, cy2)


def _shares_node(a: tuple, b: tuple) -> bool:
    if a[0] != b[0] or len(a) < 12 or len(b) < 12:
        return False
    return bool({int(a[10]), int(a[11])} & {int(b[10]), int(b[11])})


def _connected(a: tuple, b: tuple) -> bool:
    if a[:2] == b[:2]:
        return True
    if a[0] == b[0]:
        return _shares_node(a, b)
    return _min_end_gap(a, b) < JOIN_U


def _can_join(prev: tuple, nxt: tuple) -> bool:
    """Même tuile : nœud .wzm partagé. Sinon bouts vraiment proches."""
    gap = _min_end_gap(prev, nxt)
    if prev[0] == nxt[0] and len(prev) > 11 and len(nxt) > 11:
        shared = {int(prev[10]), int(prev[11])} & {int(nxt[10]), int(nxt[11])}
        if shared:
            return gap < JOIN_U * 4
        return gap < 120
    return gap < JOIN_U


def _from_node_for(
    row: tuple, prev_xy: tuple[int, int] | None, route_brg: float | None
) -> int:
    frm_id = int(row[10]) if len(row) > 10 else 0
    to_id = int(row[11]) if len(row) > 11 else 0
    blon, blat, elon, elat = row[8], row[9], row[6], row[7]
    if prev_xy is not None:
        d_from = abs(blon - prev_xy[0]) + abs(blat - prev_xy[1])
        d_to = abs(elon - prev_xy[0]) + abs(elat - prev_xy[1])
        return frm_id if d_from <= d_to else to_id
    line_brg = _bearing(blon, blat, elon, elat)
    if route_brg is None:
        return frm_id
    if _ang_diff(route_brg, line_brg) <= _ang_diff(route_brg, (line_brg + 180.0) % 360.0):
        return frm_id
    return to_id


def _exit_xy(row: tuple, from_node: int) -> tuple[int, int]:
    frm_id = int(row[10]) if len(row) > 10 else 0
    if from_node == frm_id:
        return int(row[6]), int(row[7])
    return int(row[8]), int(row[9])


def _geom_join(a: tuple, b: tuple, limit: int = JOIN_U) -> bool:
    """Même graphe visuel : nœud partagé, ou bouts qui se touchent (allée / maison)."""
    if a[:2] == b[:2]:
        return True
    if _shares_node(a, b):
        return True
    return _min_end_gap(a, b) < limit


def _row_dist_xy(row: tuple, xy: tuple[int, int]) -> int:
    return min(
        abs(row[3] - xy[0]) + abs(row[4] - xy[1]),
        abs(row[8] - xy[0]) + abs(row[9] - xy[1]),
        abs(row[6] - xy[0]) + abs(row[7] - xy[1]),
    )


def _bfs_bridge(
    prev: tuple,
    nxt: tuple,
    pool: list[tuple],
    *,
    max_hops: int = 8,
    geom: bool = False,
) -> list[tuple]:
    """Lignes du couloir qui relient prev à nxt (nœuds .wzm / bord de tuile).

    On cherche aussi une 3e tuile du couloir : un trou tile A → tile C sans B
    coupait l'overlay (instrument_segments s'arrête). Les voisins même tuile
    sont visités d'abord pour ne pas glisser sur une copie d'une autre tuile.
    """
    if _connected(prev, nxt):
        return []
    allowed = {prev[0], nxt[0]}
    same = [r for r in pool if r[0] in allowed]
    extra = [r for r in pool if r[0] not in allowed]
    nodes = same + extra
    inc: dict[tuple[int, int], list[tuple]] = defaultdict(list)
    for r in nodes:
        if len(r) > 11:
            inc[(int(r[0]), int(r[10]))].append(r)
            inc[(int(r[0]), int(r[11]))].append(r)
    join_u = JOIN_U
    touch_u = 120

    def neighbors(row: tuple) -> list[tuple]:
        out: list[tuple] = []
        seen: set[tuple] = set()
        if len(row) > 11:
            for nid in (int(row[10]), int(row[11])):
                for o in inc.get((int(row[0]), nid), ()):
                    if o[:2] != row[:2] and o[:2] not in seen:
                        seen.add(o[:2])
                        out.append(o)
        for o in nodes:
            if o[:2] == row[:2] or o[:2] in seen:
                continue
            if o[0] != row[0] and _min_end_gap(row, o) < join_u:
                seen.add(o[:2])
                out.append(o)
            elif geom and o[0] == row[0] and _min_end_gap(row, o) < touch_u:
                seen.add(o[:2])
                out.append(o)
        return out

    start, goal = prev[:2], nxt[:2]
    came: dict[tuple, tuple | None] = {start: None}
    hops: dict[tuple, int] = {start: 0}
    row_of: dict[tuple, tuple] = {start: prev, goal: nxt}
    q: deque[tuple] = deque([prev])
    found = False
    while q:
        cur = q.popleft()
        if hops[cur[:2]] >= max_hops:
            continue
        for o in neighbors(cur):
            k = o[:2]
            if k in came:
                continue
            came[k] = cur[:2]
            hops[k] = hops[cur[:2]] + 1
            row_of[k] = o
            if k == goal:
                found = True
                q.clear()
                break
            q.append(o)
    if not found:
        return []
    keys: list[tuple] = []
    k: tuple | None = goal
    while k is not None and k != start:
        keys.append(k)
        k = came.get(k)
    keys.reverse()
    if not keys or keys[-1] != goal:
        return []
    return [row_of[k] for k in keys[:-1]]


def _fill_along_route(
    raw: list[tuple], index: list[tuple], pts: list[tuple[int, int]]
) -> list[tuple]:
    """Ponts dans les tuiles du trajet, le long de l'OSRM, via le graphe .wzm.

    Même si les bouts sont à < 50 m, s'ils ne partagent pas de nœud il manque
    un morceau (courbe, intersection) → trou violet. Pas de 3e tuile.
    """
    if len(raw) < 2 or len(pts) < 2:
        return raw
    pool = [r for r in index if _on_corridor(r, pts)]
    out = [raw[0]]
    for nxt in raw[1:]:
        out.extend(_bfs_bridge(out[-1], nxt, pool, geom=True))
        out.append(nxt)
    return out


def _closest_row(
    index: list[tuple], lon: int, lat: int, limit: int = SNAP_U * 3
) -> tuple | None:
    best, hit = 10**18, None
    for row in index:
        d = min(
            abs(row[3] - lon) + abs(row[4] - lat),
            abs(row[8] - lon) + abs(row[9] - lat),
            abs(row[6] - lon) + abs(row[7] - lat),
        )
        if d < best:
            best, hit = d, row
    if hit is None or best > limit:
        return None
    return hit


def _walk_to_pin(
    start: tuple,
    target: tuple[int, int],
    index: list[tuple],
    pts: list[tuple[int, int]],
    *,
    max_hops: int = 14,
) -> list[tuple]:
    """Marche le graphe .wzm vers le pin (maison / dest) sans sauter une parallèle.

    Un bout d'allée n'a souvent pas le même nœud que la rue : on accepte les
    bouts qui se touchent, mais seulement si on se rapproche du pin ou si on
    reste dans le couloir OSRM.
    """
    cur = start
    out: list[tuple] = []
    used = {cur[:2]}
    for _ in range(max_hops):
        dcur = _row_dist_xy(cur, target)
        if dcur < JOIN_U:
            break
        best, bd = None, dcur
        for o in index:
            if o[:2] in used or not _geom_join(cur, o, JOIN_U * 2):
                continue
            d = _row_dist_xy(o, target)
            closer = d + 40 < dcur
            on_way = _on_corridor(o, pts, CORRIDOR_U * 2)
            if not closer and not on_way:
                continue
            if d < bd or (d == bd and on_way):
                bd, best = d, o
        if best is None or best[:2] == cur[:2]:
            break
        out.append(best)
        used.add(best[:2])
        cur = best
    return out


def _dedupe_rows(raw: list[tuple]) -> list[tuple]:
    out: list[tuple] = []
    for r in raw:
        if not out or out[-1][:2] != r[:2]:
            out.append(r)
    return out


def _attach_pin(
    raw: list[tuple],
    pin: tuple | None,
    target: tuple[int, int],
    index: list[tuple],
    pts: list[tuple[int, int]],
    *,
    front: bool,
) -> list[tuple]:
    if pin is None or not raw:
        return raw
    edge = raw[0] if front else raw[-1]
    if pin[:2] == edge[:2]:
        extra = _walk_to_pin(edge, target, index, pts)
        return _dedupe_rows((list(reversed(extra)) + raw) if front else (raw + extra))
    pool = [
        r for r in index if _on_corridor(r, pts) or r[:2] in (pin[:2], edge[:2])
    ]
    if front:
        bridge = _bfs_bridge(pin, edge, pool, geom=True, max_hops=12)
    else:
        bridge = _bfs_bridge(edge, pin, pool, geom=True, max_hops=12)
    if bridge or _geom_join(pin, edge):
        return _dedupe_rows(
            ([pin] + bridge + raw) if front else (raw + bridge + [pin])
        )
    extra = _walk_to_pin(edge, target, index, pts)
    if front:
        head = list(reversed(extra))
        if not head or head[0][:2] != pin[:2]:
            head = [pin] + head
        return _dedupe_rows(head + raw)
    tail = extra
    if not tail or tail[-1][:2] != pin[:2]:
        tail = tail + [pin]
    return _dedupe_rows(raw + tail)


def _pin_ends(
    raw: list[tuple], index: list[tuple], pts: list[tuple[int, int]]
) -> list[tuple]:
    """Colle le 1er et le dernier point OSRM (maison / dest), même hors couloir."""
    if not raw or len(pts) < 2:
        return raw
    start = _closest_row(index, pts[0][0], pts[0][1], SNAP_U * 4)
    end = _closest_row(index, pts[-1][0], pts[-1][1], SNAP_U * 4)
    raw = _attach_pin(raw, start, pts[0], index, pts, front=True)
    raw = _attach_pin(raw, end, pts[-1], index, pts, front=False)
    return raw


def _fill_line_gaps(raw: list[tuple], index: list[tuple]) -> list[tuple]:
    """Insère une ligne .wzm seulement si elle relie vraiment prev et next.

    Ne plus appeler depuis le matcher : un pont dans une autre tuile bloque
    instrument_segments() (le précédent doit être instrumenté d'abord).
    """
    connect = 4_000
    if len(raw) < 2:
        return raw
    out = [raw[0]]
    for nxt in raw[1:]:
        hops = 0
        while _min_end_gap(out[-1], nxt) > connect and hops < 8:
            used = {r[:2] for r in out}
            used.add(nxt[:2])
            pe, ne = _ends(out[-1]), _ends(nxt)
            bridge = None
            best = 10**18
            mid_lon = (out[-1][3] + nxt[3]) // 2
            mid_lat = (out[-1][4] + nxt[4]) // 2
            for row in index:
                if row[:2] in used:
                    continue
                if abs(row[3] - mid_lon) + abs(row[4] - mid_lat) > 80_000:
                    continue
                re = _ends(row)
                d1 = min(abs(p[0] - q[0]) + abs(p[1] - q[1]) for p in pe for q in re)
                d2 = min(abs(p[0] - q[0]) + abs(p[1] - q[1]) for p in ne for q in re)
                score = d1 + d2
                if d1 < connect and d2 < connect and score < best:
                    best = score
                    bridge = row
            if bridge is None:
                break
            out.append(bridge)
            hops += 1
        out.append(nxt)
    return out


def _downsample_lines(raw: list[tuple], max_n: int = 120) -> list[tuple]:
    """Garde début + fin. Trop de tuiles distinctes bloque l'overlay GPL."""
    if len(raw) <= max_n:
        return raw
    keep = [raw[0]]
    step = (len(raw) - 1) / (max_n - 1)
    for k in range(1, max_n - 1):
        row = raw[int(round(k * step))]
        if row[:2] != keep[-1][:2]:
            keep.append(row)
    if raw[-1][:2] != keep[-1][:2]:
        keep.append(raw[-1])
    return keep


def _turn_instr(b1: float, b2: float, *, name_change: bool = False) -> int:
    d = (b2 - b1 + 540.0) % 360.0 - 180.0
    ad = abs(d)
    if ad >= 40:
        return TURN_LEFT if d > 0 else TURN_RIGHT
    if ad >= 22:
        return KEEP_LEFT if d >= 0 else KEEP_RIGHT
    if name_change and ad >= 12:
        return KEEP_LEFT if d >= 0 else KEEP_RIGHT
    return CONTINUE


def _match_segments(
    pts: list[tuple[int, int]], total_len: int, total_time: int
) -> list[dict]:
    pad = 40_000  # bbox d'index seulement (~4 km), pas le rayon de snap
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    bbox = (min(lons) - pad, min(lats) - pad, max(lons) + pad, max(lats) + pad)
    index = _load_line_index(bbox=bbox)
    names = _load_osm_names()
    if not index or len(pts) < 2:
        return []

    corridor_ids = {row[:2] for row in index if _on_corridor(row, pts)}
    if not corridor_ids:
        corridor_ids = {
            row[:2] for row in index if _on_corridor(row, pts, CORRIDOR_U * 2)
        }
    for p in (pts[0], pts[-1]):
        hit = _closest_row(index, p[0], p[1])
        if hit:
            corridor_ids.add(hit[:2])

    cell = 2_000
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, row in enumerate(index):
        x1, y1, x2, y2 = row[8], row[9], row[6], row[7]
        steps = max(abs(x2 - x1), abs(y2 - y1), 1) // cell + 1
        stamped: set[tuple[int, int]] = set()
        for t in range(steps + 1):
            x = x1 + (x2 - x1) * t // steps
            y = y1 + (y2 - y1) * t // steps
            stamped.add((x // cell, y // cell))
        stamped.add((row[3] // cell, row[4] // cell))
        for key in stamped:
            grid[key].append(i)

    def candidates(lon: int, lat: int, seg_a: tuple[int, int], seg_b: tuple[int, int]):
        cx, cy = lon // cell, lat // cell
        seen: set[int] = set()
        pool: list[tuple[int, int]] = []
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for ii in grid.get((gx, gy), ()):
                    if ii in seen:
                        continue
                    seen.add(ii)
                    d = _line_to_osrm(index[ii], seg_a, seg_b)
                    pool.append((d, ii))
        pool.sort()
        for _d, ii in pool[:120]:
            yield index[ii]

    raw: list[tuple] = []
    prev: tuple | None = None
    skipped = 0
    for i, (lon, lat) in enumerate(pts):
        if i + 1 < len(pts):
            seg_a, seg_b = pts[i], pts[i + 1]
            brg = _bearing(lon, lat, pts[i + 1][0], pts[i + 1][1])
        elif i > 0:
            seg_a, seg_b = pts[i - 1], pts[i]
            brg = _bearing(pts[i - 1][0], pts[i - 1][1], lon, lat)
        else:
            continue

        at_end = i <= 1 or i >= len(pts) - 2
        snap = SNAP_U * 2 if at_end else SNAP_U
        heading_lim = 90.0 if at_end else HEADING_MAX
        nearby: list[tuple] = []
        for row in candidates(lon, lat, seg_a, seg_b):
            if row[:2] not in corridor_ids:
                continue
            d_path = _line_to_osrm(row, seg_a, seg_b)
            if d_path > snap:
                continue
            if _heading_err(row, brg) > heading_lim:
                continue
            nearby.append(row)

        best = None
        best_cost = 10**18
        for row in nearby:
            joinable = (
                prev is None or row[:2] == prev[:2] or _can_join(prev, row)
            )
            left_prev = (
                prev is not None and _line_to_osrm(prev, seg_a, seg_b) > SNAP_U
            )
            if not joinable and not left_prev:
                continue
            cost = _osrm_window_cost(row, pts, i)
            cost += int(_heading_err(row, brg) * 6)
            if prev is not None and row[:2] == prev[:2]:
                cost = cost // 2
            elif prev is not None and row[0] != prev[0]:
                cost += 80
            if not joinable:
                cost += 400
            if cost < best_cost:
                best_cost = cost
                best = row

        stay_heading_ok = True
        if prev is not None and not at_end:
            stay_heading_ok = _heading_err(prev, brg) <= HEADING_MAX + 12.0

        if prev is not None:
            stay_now = _line_to_osrm(prev, seg_a, seg_b)
            stay_cost = _osrm_window_cost(prev, pts, i)
            if best is None or best[:2] == prev[:2]:
                if stay_now <= SNAP_U * 2 and stay_heading_ok:
                    best = prev
            elif (
                stay_now <= SNAP_U * 2
                and stay_heading_ok
                and stay_cost <= best_cost + SWITCH_MARGIN
            ):
                best = prev

        if best is None and at_end:
            hit = _closest_row(index, lon, lat, SNAP_U * 4)
            if hit is not None:
                best = hit
                best_cost = 0
        if best is None:
            skipped += 1
            continue
        if not raw or raw[-1][:2] != best[:2]:
            raw.append(best)
        prev = best

    i = 1
    while i < len(raw) - 1:
        if raw[i - 1][:2] == raw[i + 1][:2] and raw[i][:2] != raw[i - 1][:2]:
            del raw[i]
            continue
        i += 1

    # Crochet A-B-A déjà enlevé. Un zigzag A-ruelle-C (A et C se touchent)
    # laisse un à-coup gauche/droite : on le retire comme un kink.
    raw = _drop_kinks(raw, pts)

    raw = _fill_along_route(raw, index, pts)
    raw = _pin_ends(raw, index, pts)
    raw = _fill_along_route(raw, index, pts)
    raw = _drop_kinks(raw, pts)

    if not raw:
        return []

    n_tiles = len({r[0] for r in raw})
    print(
        f"  trace wzm lignes={len(raw)} tuiles={n_tiles} "
        f"osrm_pts={len(pts)} ignorés={skipped}",
        flush=True,
    )

    weights = [max(r[5], 1) for r in raw]
    wsum = sum(weights) or 1
    segs: list[dict] = []
    remain_l, remain_t = total_len, total_time
    prev_xy: tuple[int, int] | None = pts[0]
    for i, row in enumerate(raw):
        tid, li, ts, mlon, mlat, alen, elon, elat = row[:8]
        if i + 1 < len(raw):
            brg = _bearing(mlon, mlat, raw[i + 1][3], raw[i + 1][4])
        elif i > 0:
            brg = _bearing(raw[i - 1][3], raw[i - 1][4], mlon, mlat)
        else:
            brg = _bearing(pts[0][0], pts[0][1], pts[-1][0], pts[-1][1])
        from_node = _from_node_for(row, prev_xy, brg)
        prev_xy = _exit_xy(row, from_node)
        if i == len(raw) - 1:
            sl, st = max(remain_l, 1), max(remain_t, 1)
        else:
            sl = max(int(total_len * weights[i] / wsum), 1)
            st = max(int(total_time * weights[i] / wsum), 1)
            remain_l -= sl
            remain_t -= st
        name = _name_near(mlon, mlat, names)
        segs.append(
            {
                "tid": tid,
                "line": li,
                "ts": ts,
                "len": sl,
                "time": st,
                "mlon": mlon,
                "mlat": mlat,
                "elon": elon,
                "elat": elat,
                "name": name,
                "instr": CONTINUE,
                "dest_name": name,
                "from_node": from_node,
            }
        )

    for _ in range(2):
        for i in range(1, len(segs) - 1):
            a, b, c = segs[i - 1]["name"], segs[i]["name"], segs[i + 1]["name"]
            if a and c and a == c and b != a:
                segs[i]["name"] = a
    for i in range(1, len(segs)):
        if not segs[i]["name"] and segs[i - 1]["name"]:
            segs[i]["name"] = segs[i - 1]["name"]

    # Les virages viennent d'OSRM, pas de la géométrie .wzm (morceaux de 30 m
    # et courbes = faux KEEP / ronds-points dans la barre verte).
    for i in range(len(segs) - 1):
        segs[i]["instr"] = CONTINUE
        segs[i]["dest_name"] = segs[i + 1]["name"] or segs[i]["name"]
    segs[-1]["instr"] = APPROACHING_DESTINATION
    segs[-1]["dest_name"] = segs[-1]["name"]
    return segs


def _drop_kinks(
    raw: list[tuple], pts: list[tuple[int, int]]
) -> list[tuple]:
    """Enlève un crochet court (~30 m) si prev et next se rejoignent sans lui.

    Ne touche pas un vrai virage (long, sur l'OSRM) ni un pont nécessaire
    (prev et next ne se touchent pas).
    """
    if len(raw) < 3 or len(pts) < 2:
        return raw
    out = list(raw)
    i = 1
    while i < len(out) - 1:
        prev, cur, nxt = out[i - 1], out[i], out[i + 1]
        if not (_geom_join(prev, nxt) or _shares_node(prev, nxt)):
            i += 1
            continue
        alen = int(cur[5]) if len(cur) > 5 else 0
        short = alen < 55
        hp = _bearing(prev[8], prev[9], prev[6], prev[7])
        hc = _bearing(cur[8], cur[9], cur[6], cur[7])
        hn = _bearing(nxt[8], nxt[9], nxt[6], nxt[7])

        def _hd(a: float, b: float) -> float:
            return min(_ang_diff(a, b), _ang_diff(a, (b + 180.0) % 360.0))

        hook = _hd(hp, hc) >= 35 and _hd(hc, hn) >= 35
        dcur = _dist_to_poly(cur[3], cur[4], pts)
        dnb = min(
            _dist_to_poly(prev[3], prev[4], pts),
            _dist_to_poly(nxt[3], nxt[4], pts),
        )
        off = dcur > dnb + 60 and dcur > CORRIDOR_U
        i_pt = _nearest_pt_idx(cur[3], cur[4], pts)
        j = min(i_pt, len(pts) - 2)
        osrm_h = _bearing(pts[j][0], pts[j][1], pts[j + 1][0], pts[j + 1][1])
        vs_osrm = _hd(hc, osrm_h)
        if (short and (hook or off or vs_osrm >= 35)) or (hook and off):
            del out[i]
            if i > 1:
                i -= 1
            continue
        i += 1
    return out


def _trim_end_hooks(
    raw: list[tuple], pts: list[tuple[int, int]]
) -> list[tuple]:
    """Allée / bout perpendiculaire collé au pin : ça fait un crochet violet."""
    if len(raw) < 3 or len(pts) < 2:
        return raw
    out = list(raw)
    start_h = _bearing(pts[0][0], pts[0][1], pts[1][0], pts[1][1])
    end_h = _bearing(pts[-2][0], pts[-2][1], pts[-1][0], pts[-1][1])

    def _bad(row: tuple, want_h: float) -> bool:
        rh = _bearing(row[8], row[9], row[6], row[7])
        vs = min(_ang_diff(rh, want_h), _ang_diff(rh, (want_h + 180.0) % 360.0))
        alen = int(row[5]) if len(row) > 5 else 0
        return vs >= 40 and alen < 70

    while len(out) > 2 and _bad(out[0], start_h):
        if _dist_to_poly(out[0][3], out[0][4], pts) + 40 >= _dist_to_poly(
            out[1][3], out[1][4], pts
        ):
            del out[0]
            continue
        break
    while len(out) > 2 and _bad(out[-1], end_h):
        if _dist_to_poly(out[-1][3], out[-1][4], pts) + 40 >= _dist_to_poly(
            out[-2][3], out[-2][4], pts
        ):
            del out[-1]
            continue
        break
    return out


def _apply_osrm_steps(segs: list[dict], steps: list[dict]) -> None:
    """Place chaque manœuvre OSRM sur le segment .wzm à la même fraction du trajet.

    Un snap GPS (seuil 80 mµ°) ratait presque tout → un seul groupe CONTINUE
    jusqu'à APPROACHING_DESTINATION (« Continue 4468ft approaching destination »).
    """
    if not segs:
        return
    for s in segs[:-1]:
        s["instr"] = CONTINUE
    segs[-1]["instr"] = APPROACHING_DESTINATION
    if not steps:
        return
    cum: list[int] = []
    total = 0
    for s in segs:
        total += max(int(s.get("len") or 1), 1)
        cum.append(total)
    osrm_total = sum(max(int(st.get("dist") or 0), 1) for st in steps) or 1
    walked = 0
    used: set[int] = set()
    last_i = len(segs) - 1
    for step in steps:
        walked += max(int(step.get("dist") or 0), 1)
        instr = step["instr"]
        if instr in (CONTINUE, APPROACHING_DESTINATION):
            continue
        target = walked / osrm_total * total
        best_i, best_d = None, 10**18
        # Le dernier segment reste APPROACHING_DESTINATION (barre + Arrive).
        for i in range(max(last_i, 1)):
            if i in used or i == last_i:
                continue
            d = abs(cum[i] - target)
            if d < best_d:
                best_d, best_i = d, i
        if best_i is None:
            continue
        used.add(best_i)
        segs[best_i]["instr"] = instr
        if step.get("name"):
            segs[best_i]["dest_name"] = step["name"]
    segs[-1]["instr"] = APPROACHING_DESTINATION


def _segments_from_steps(
    steps: list[dict], total_len: int, total_time: int
) -> list[dict]:
    """Un segment .wzm par étape OSRM (manœuvre + géométrie locale)."""
    if not steps:
        return []
    lons = [s["lon"] for s in steps]
    lats = [s["lat"] for s in steps]
    pad = 40_000
    index = _load_line_index(
        bbox=(min(lons) - pad, min(lats) - pad, max(lons) + pad, max(lats) + pad)
    )
    if not index:
        return []
    segs: list[dict] = []
    remain_l, remain_t = total_len, total_time
    for i, st in enumerate(steps):
        hit = None
        best = 10**18
        for row in index:
            d = abs(row[3] - st["lon"]) + abs(row[4] - st["lat"])
            if d < best:
                best, hit = d, row
        if hit is None or best > SNAP_U * 2:
            continue
        tid, li, ts, mlon, mlat, alen, elon, elat = hit[:8]
        if i == len(steps) - 1:
            sl, stm = max(remain_l, 1), max(remain_t, 1)
        else:
            sl = max(st["dist"] or alen, 1)
            stm = max(st["time"] or 1, 1)
            remain_l -= sl
            remain_t -= stm
        segs.append(
            {
                "tid": tid,
                "line": li,
                "ts": ts,
                "len": sl,
                "time": stm,
                "mlon": mlon,
                "mlat": mlat,
                "elon": elon,
                "elat": elat,
                "name": st["name"],
                "instr": st["instr"],
                "dest_name": st["name"],
            }
        )
    if segs:
        segs[-1]["instr"] = APPROACHING_DESTINATION
    return segs


def _route_segment_rows(route_id: int, alt_id: int, segs: list[dict]) -> list[str]:
    """Une ligne RouteSegments par run consécutif (même tuile + timestamp)."""
    rows: list[str] = []
    i = 0
    while i < len(segs):
        tid, ts = segs[i]["tid"], segs[i]["ts"]
        j = i + 1
        while j < len(segs) and segs[j]["tid"] == tid and segs[j]["ts"] == ts:
            j += 1
        chunk = segs[i:j]
        nums: list[str] = []
        names: list[str] = []
        for s in chunk:
            nums.extend(
                str(v)
                for v in (
                    s["line"],
                    int(s.get("from_node") or 0),
                    s["len"],
                    s["time"],
                    _wire(s["instr"]),
                    0,
                )
            )
            names.append(_ascii(s.get("dest_name") or s.get("name") or ""))
        rows.append(
            f"RouteSegments,{route_id},{alt_id},{tid},{ts},{len(chunk) * 6},"
            + ",".join(nums)
            + ","
            + ",".join(names)
        )
        i = j
    return rows


def dest_label_from_request(body: bytes) -> str:
    """Rue (+ ville) du RoutingRequest — pour le dernier dest_name, pas le Via."""
    for line in body.replace(b"\r\n", b"\n").split(b"\n"):
        if not line.lower().startswith(b"routingrequest,"):
            continue
        f = line.decode("latin1", errors="replace").split(",")
        street = _ascii(f[19]) if len(f) > 19 else ""
        city = ""
        try:
            nopt = int(f[23])
            base = 24 + nopt
            if len(f) > base + 2:
                city = _ascii(f[base + 2])
        except (ValueError, IndexError):
            pass
        if street and city:
            return f"{street} {city}".strip()
        return street or city
    return ""


def via_label_from_steps(steps: list[dict], dest_name: str = "") -> str:
    """Voie principale du trajet (alt_description / Via). Jamais la destination."""
    dest = (dest_name or "").lower()
    best, best_d = "", -1
    for st in steps:
        name = st.get("name") or ""
        if not name:
            continue
        if dest and (name.lower() in dest or dest in name.lower()):
            continue
        d = int(st.get("dist") or 0)
        if d > best_d:
            best, best_d = name, d
    if best:
        return best
    for st in steps:
        if st.get("name"):
            return st["name"]
    return ""


_route_lock = threading.Lock()
_route_cache: dict[tuple, dict] = {}
_route_inflight: dict[tuple, threading.Event] = {}


def _route_key(lon1: float, lat1: float, lon2: float, lat2: float) -> tuple:
    return (round(lon1, 4), round(lat1, 4), round(lon2, 4), round(lat2, 4))


def _format_route(
    route_id: int,
    pts: list[tuple[int, int]],
    length: int,
    duration: int,
    matched: list[dict],
    via: str,
) -> bytes:
    alt_id = 1
    nseg = len(matched)
    rows = [
        "RC,200,OK",
        f"RoutingResponseCode,{route_id},1,200,OK",
        f"RoutingResponse,{route_id},{ROUTE_ORIGINAL},{alt_id},{via},"
        f"{length},{duration},{nseg},0,0,0",
        "RoutePoints,"
        + f"{route_id},{alt_id},{len(pts)},0,{len(pts) * 2},"
        + ",".join(f"{lon},{lat}" for lon, lat in pts),
    ]
    if matched:
        rows.extend(_route_segment_rows(route_id, alt_id, matched))
    return ("\r\n".join(rows) + "\r\n").encode("ascii")


def _compute_route(
    lon1: float, lat1: float, lon2: float, lat2: float, dest_name: str
) -> dict | None:
    got = osrm_route(lon1, lat1, lon2, lat2)
    if not got:
        return None
    pts, length, duration, steps = got
    print(wzm_status_line(lon1, lat1), flush=True)
    try:
        matched = _match_segments(pts, length, duration)
    except Exception as e:
        print(f"  matcher FAIL: {type(e).__name__}: {e}", flush=True)
        matched = []
    if matched:
        _apply_osrm_steps(matched, steps)
    dest = _ascii(dest_name)
    via = via_label_from_steps(steps, dest)
    if matched and dest:
        matched[-1]["dest_name"] = dest
    n_turns = sum(
        1
        for s in matched
        if s.get("instr") not in (CONTINUE, APPROACHING_DESTINATION)
    )
    print(
        f"  route segs={len(matched)} turns={n_turns} via={via!r} dest={dest!r}",
        flush=True,
    )
    if not matched:
        print(
            "  pas de RouteSegments (line_id=-1 interdit : overlay mort + "
            "Continue approaching destination)",
            flush=True,
        )
    return {
        "pts": pts,
        "length": length,
        "duration": duration,
        "matched": matched,
        "via": via,
    }


def routing_body(
    route_id: int,
    lon1: float,
    lat1: float,
    lon2: float,
    lat2: float,
    dest_name: str = "",
) -> bytes:
    key = _route_key(lon1, lat1, lon2, lat2)
    with _route_lock:
        cached = _route_cache.get(key)
        if cached is not None:
            print("  itinéraire (cache)", flush=True)
            return _format_route(
                route_id,
                cached["pts"],
                cached["length"],
                cached["duration"],
                cached["matched"],
                cached["via"],
            )
        ev = _route_inflight.get(key)
        mine = ev is None
        if mine:
            ev = threading.Event()
            _route_inflight[key] = ev
    if not mine:
        ev.wait(timeout=30)
        with _route_lock:
            cached = _route_cache.get(key)
        if cached is None:
            return (
                f"RC,200,OK\r\n"
                f"RoutingResponseCode,{route_id},0,500,No route\r\n"
            ).encode("ascii")
        print("  itinéraire (attente)", flush=True)
        return _format_route(
            route_id,
            cached["pts"],
            cached["length"],
            cached["duration"],
            cached["matched"],
            cached["via"],
        )
    try:
        computed = _compute_route(lon1, lat1, lon2, lat2, dest_name)
        if computed is None:
            return (
                f"RC,200,OK\r\n"
                f"RoutingResponseCode,{route_id},0,500,No route\r\n"
            ).encode("ascii")
        with _route_lock:
            _route_cache[key] = computed
            while len(_route_cache) > 8:
                _route_cache.pop(next(iter(_route_cache)))
        return _format_route(
            route_id,
            computed["pts"],
            computed["length"],
            computed["duration"],
            computed["matched"],
            computed["via"],
        )
    finally:
        with _route_lock:
            _route_inflight.pop(key, None)
        ev.set()


def parse_routing_request(body: bytes) -> tuple[int, float, float, float, float] | None:
    for line in body.replace(b"\r\n", b"\n").split(b"\n"):
        if not line.lower().startswith(b"routingrequest,"):
            continue
        f = line.decode("latin1", errors="replace").split(",")
        if len(f) < 16:
            return None
        try:
            rid = int(f[1])
            lon1 = int(f[7]) / 1e6
            lat1 = int(f[8]) / 1e6
            lon2 = int(f[14]) / 1e6
            lat2 = int(f[15]) / 1e6
        except ValueError:
            return None
        return rid, lon1, lat1, lon2, lat2
    return None
