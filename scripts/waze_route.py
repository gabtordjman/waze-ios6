#!/usr/bin/env python3
"""Itinéraire Waze 2.4 : RoutePoints (dézoom) + segments du .wzm (zoom rue).

GPL navigate_main_screen_repaint() (navigate_main.c) :
- zoom ≥ 100 + RoutePoints → dessine l'outline OSRM puis return
- zoom < 100 → uniquement les segments is_instrumented

instrument_segments() refuse line_id < 0. Les stubs -1 n'affichent donc
rien de près. Il faut les vrais (tile_id, line_id, timestamp) du .wzm
96e7e67 (polylignes + shapes). On ne touche pas au générateur de cartes.
"""

from __future__ import annotations

import json
import math
import struct
import zlib
from collections import defaultdict
from pathlib import Path

OSRM = "https://router.project-osrm.org/route/v1/driving"
UA = "waze-ios6-catcher/1.0 (local lab)"
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
    target = max(40, min(400, int(length_m / 15) + 2))
    step = max(1, len(coords) // target)
    pts = [
        (int(round(c[0] * 1e6)), int(round(c[1] * 1e6)))
        for c in coords[::step]
    ]
    origin = (int(round(lon1 * 1e6)), int(round(lat1 * 1e6)))
    dest = (int(round(lon2 * 1e6)), int(round(lat2 * 1e6)))
    if pts[0] != origin:
        pts.insert(0, origin)
    if pts[-1] != dest:
        pts.append(dest)

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
        POINT_REAL_MASK,
        S_LINE_DATA,
        S_POINT_DATA,
        S_SQUARE_DATA,
        TILE_SCALES,
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

    for tid, off, csz, _rsz in info["entries"]:
        if tid >= scale0_hi:
            continue  # échelle 0 seulement (zoom rue)
        west, east, south, north, _ = tile_edges(tid)
        if bw is not None and (east < bw or west > be or north < bs or south > bn):
            continue
        try:
            raw = zlib.decompress(blob[off : off + csz])
        except Exception:
            continue
        num_sections, _ = struct.unpack("<II", raw[:8])
        idx_end = 8 + num_sections * 4
        ends = list(struct.unpack(f"<{num_sections}I", raw[8:idx_end]))
        starts = [0] + ends[:-1]
        sections = {
            i: raw[idx_end + starts[i] : idx_end + ends[i]] for i in range(num_sections)
        }
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
                (tid, li, ts, mid_lon, mid_lat, approx, lon2, lat2, lon1, lat1)
            )

    _lines_cache = (cache_key, out)
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


def _fill_line_gaps(raw: list[tuple], index: list[tuple]) -> list[tuple]:
    """Insère une ligne .wzm seulement si elle relie vraiment prev et next."""
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
    pad = 40_000  # ~0.04°
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    bbox = (min(lons) - pad, min(lats) - pad, max(lons) + pad, max(lats) + pad)
    index = _load_line_index(bbox=bbox)
    names = _load_osm_names()
    if not index or len(pts) < 2:
        return []

    cell = 5_000
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, row in enumerate(index):
        grid[(row[3] // cell, row[4] // cell)].append(i)

    def candidates(lon: int, lat: int):
        cx, cy = lon // cell, lat // cell
        pool: list[tuple[int, int]] = []
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for ii in grid.get((gx, gy), ()):
                    row = index[ii]
                    d = abs(row[3] - lon) + abs(row[4] - lat)
                    pool.append((d, ii))
        pool.sort()
        for _d, ii in pool[:60]:
            yield index[ii]

    def best_at(lon: int, lat: int, route_brg: float | None, seg_a, seg_b, prev):
        best = None
        best_score = 10**18
        for row in candidates(lon, lat):
            tid, li, ts, mlon, mlat, alen, elon, elat, blon, blat = row
            # Colle au segment OSRM local (pas toute la polyligne).
            if _dist_to_seg(mlon, mlat, seg_a, seg_b) > 45_000:
                continue
            d = abs(mlon - lon) + abs(mlat - lat)
            line_brg = _bearing(blon, blat, elon, elat)
            if route_brg is not None:
                ad = _ang_diff(route_brg, line_brg)
                ad_rev = _ang_diff(route_brg, (line_brg + 180) % 360)
                ad = min(ad, ad_rev)
                if ad > 55:
                    continue
                d += int(ad * 400)
            if prev is not None:
                if tid == prev[0] and li == prev[1]:
                    d = d // 5
                else:
                    gap = min(
                        abs(blon - prev[6]) + abs(blat - prev[7]),
                        abs(blon - prev[3]) + abs(blat - prev[4]),
                        abs(elon - prev[6]) + abs(elat - prev[7]),
                    )
                    if gap < 30_000:
                        d = max(0, d - 25_000)
                    elif gap > 100_000:
                        d += 60_000
            if d < best_score:
                best_score = d
                best = row
        if best is None or best_score > 70_000:
            return None
        return best

    raw: list[tuple] = []
    prev = None
    for i, (lon, lat) in enumerate(pts):
        if i + 1 < len(pts):
            seg_a, seg_b = pts[i], pts[i + 1]
            brg = _bearing(lon, lat, pts[i + 1][0], pts[i + 1][1])
        elif i > 0:
            seg_a, seg_b = pts[i - 1], pts[i]
            brg = _bearing(pts[i - 1][0], pts[i - 1][1], lon, lat)
        else:
            continue
        hit = best_at(lon, lat, brg, seg_a, seg_b, prev)
        if not hit:
            continue
        if not raw or raw[-1][:2] != hit[:2]:
            raw.append(hit)
        prev = hit

    i = 1
    while i < len(raw) - 1:
        if raw[i - 1][:2] == raw[i + 1][:2] and raw[i][:2] != raw[i - 1][:2]:
            del raw[i]
            continue
        i += 1

    if not raw:
        return []

    raw = _fill_line_gaps(raw, index)
    if not raw:
        return []

    weights = [max(r[5], 1) for r in raw]
    wsum = sum(weights) or 1
    segs: list[dict] = []
    remain_l, remain_t = total_len, total_time
    for i, row in enumerate(raw):
        tid, li, ts, mlon, mlat, alen, elon, elat = row[:8]
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

    for i in range(len(segs) - 1):
        a, b = segs[i], segs[i + 1]
        if i > 0:
            p = segs[i - 1]
            b1 = _bearing(p["mlon"], p["mlat"], a["mlon"], a["mlat"])
        else:
            b1 = _bearing(a["mlon"], a["mlat"], b["mlon"], b["mlat"])
        b2 = _bearing(a["mlon"], a["mlat"], b["mlon"], b["mlat"])
        name_change = bool(b["name"] and a["name"] != b["name"])
        a["instr"] = _turn_instr(b1, b2, name_change=name_change)
        a["dest_name"] = b["name"] or a["name"]

    segs[-1]["instr"] = APPROACHING_DESTINATION
    segs[-1]["dest_name"] = segs[-1]["name"]
    return segs


def _apply_osrm_steps(segs: list[dict], steps: list[dict]) -> None:
    """Les manœuvres OSRM priment sur le CONTINUE du matcher .wzm."""
    if not segs or not steps:
        return
    for step in steps:
        instr = step["instr"]
        if instr == CONTINUE:
            continue
        best_i, best_d = None, 10**18
        for i, s in enumerate(segs):
            d = abs(s["mlon"] - step["lon"]) + abs(s["mlat"] - step["lat"])
            if d < best_d:
                best_d, best_i = d, i
        if best_i is None or best_d > 80_000:
            continue
        segs[best_i]["instr"] = instr
        if step["name"]:
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
        if hit is None or best > 80_000:
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
                    0,
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


def routing_body(
    route_id: int,
    lon1: float,
    lat1: float,
    lon2: float,
    lat2: float,
    dest_name: str = "",
) -> bytes:
    got = osrm_route(lon1, lat1, lon2, lat2)
    if not got:
        return (
            f"RC,200,OK\r\n"
            f"RoutingResponseCode,{route_id},0,500,No route\r\n"
        ).encode("ascii")

    pts, length, duration, steps = got
    alt_id = 1
    try:
        matched = _match_segments(pts, length, duration)
    except Exception as e:
        print(f"  matcher FAIL: {type(e).__name__}: {e}", flush=True)
        matched = []
    if matched:
        _apply_osrm_steps(matched, steps)
    else:
        matched = _segments_from_steps(steps, length, duration)

    dest = _ascii(dest_name)
    via = via_label_from_steps(steps, dest)
    if matched and dest:
        matched[-1]["dest_name"] = dest

    nseg = len(matched) if matched else 2
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
    else:
        from wazemap import tile_id  # type: ignore

        tid = tile_id(int(lon1 * 1e6), int(lat1 * 1e6), 0)
        half_len = max(length // 2, 1)
        half_dur = max(duration // 2, 1)
        rows.append(
            f"RouteSegments,{route_id},{alt_id},{tid},1,12,"
            f"0,-1,{half_len},{half_dur},{_wire(CONTINUE)},0,"
            f"0,-1,{half_len},{half_dur},{_wire(APPROACHING_DESTINATION)},0,"
            f","
        )
    return ("\r\n".join(rows) + "\r\n").encode("ascii")


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
