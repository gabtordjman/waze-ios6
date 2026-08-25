#!/usr/bin/env python3
"""Recherche d'adresses Waze 2.4 (single_search / mozi_combo).

GPL single_search.c : si provider=waze → on_address_option :
  AddressCandidate,waze,<lon>,<lat>,[state],[county],<city>,<street>,<house>
Le titre d'itinéraire n'affiche street que si city est aussi remplie
(navigate_main_get_dest_str). City n'est jamais laissée vide.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, unquote
from urllib.request import Request, urlopen

UA = "waze-ios6-catcher/1.0 (local lab)"
NOMINATIM = "https://nominatim.openstreetmap.org/search"


def _ascii(s: str) -> str:
    if not s:
        return ""
    repl = str.maketrans(
        "àáâãäåèéêëìíîïòóôõöùúûüýÿñçÀÁÂÃÄÅÈÉÊËÌÍÎÏÒÓÔÕÖÙÚÛÜÝŸÑÇ",
        "aaaaaaeeeeiiiiooooouuuuyyncAAAAAAEEEEIIIIOOOOOUUUUYYNC",
    )
    out = s.translate(repl).encode("ascii", "ignore").decode("ascii")
    return out.replace(",", " ").replace("\r", " ").replace("\n", " ").strip()[:80]


def parse_search_form(body: bytes) -> tuple[str, float | None, float | None]:
    raw = body.decode("utf-8", errors="replace")
    if raw.lower().startswith("post ") or "\r\n\r\n" in raw:
        raw = raw.split("\r\n\r\n", 1)[-1]
    qs = parse_qs(raw, keep_blank_values=True)
    q = unquote((qs.get("q") or [""])[0])
    lon = lat = None
    for key_lon, key_lat in (
        ("longtitude", "latitude"),
        ("longitude", "latitude"),
        ("lon", "lat"),
    ):
        try:
            if qs.get(key_lon) and qs.get(key_lat):
                lon = float(qs[key_lon][0])
                lat = float(qs[key_lat][0])
                break
        except (TypeError, ValueError):
            continue
    return q, lon, lat


def _nominatim(q: str, lon: float | None, lat: float | None) -> list[dict]:
    if not q.strip():
        return []
    params = f"q={q.replace(' ', '+')}&format=json&addressdetails=1&limit=8"
    if lon is not None and lat is not None:
        params += f"&viewbox={lon-0.15},{lat+0.15},{lon+0.15},{lat-0.15}&bounded=0"
    req = Request(f"{NOMINATIM}?{params}", headers={"User-Agent": UA})
    try:
        with urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _city_street(hit: dict, q: str) -> tuple[str, str]:
    addr = hit.get("address") or {}
    street = _ascii(
        addr.get("road")
        or addr.get("pedestrian")
        or addr.get("residential")
        or ""
    )
    city = _ascii(
        addr.get("city")
        or addr.get("town")
        or addr.get("village")
        or addr.get("municipality")
        or addr.get("county")
        or ""
    )
    if not street:
        street = _ascii(q.split(",")[0])
    if not city:
        city = "Thonon-les-Bains"
    return city, street


def search_body(
    q: str,
    lon: float | None = None,
    lat: float | None = None,
    single_search: bool = True,
) -> bytes:
    hits = _nominatim(q, lon, lat)
    rows = ["RC,200,OK"]
    if not hits and q.strip() and lon is not None and lat is not None:
        hits = [
            {
                "lon": lon,
                "lat": lat,
                "address": {"road": q, "city": "Thonon-les-Bains"},
            }
        ]
    for hit in hits[:8]:
        try:
            hlon = float(hit["lon"])
            hlat = float(hit["lat"])
        except (KeyError, TypeError, ValueError):
            continue
        city, street = _city_street(hit, q)
        rows.append(
            f"AddressCandidate,waze,{hlon:.6f},{hlat:.6f},,,{city},{street},"
        )
    if len(rows) == 1:
        return b"RC,600,No matches\r\n"
    return ("\r\n".join(rows) + "\r\n").encode("ascii")
