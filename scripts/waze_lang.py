#!/usr/bin/env python3
"""Langue client Waze 2.4 : `fra` ou `eng` (packs déjà servis).

GetGeoServerConfig n'envoie pas la locale iPhone — seulement proto + GPS.
On déduit donc la langue de la position (francophone vs le reste).
"""

from __future__ import annotations


def client_lang(lon: float | None, lat: float | None) -> str:
    """`fra` pour les zones francophones, `eng` partout ailleurs (US, UK, …)."""
    if lon is None or lat is None:
        return "eng"
    try:
        lon_f, lat_f = float(lon), float(lat)
    except (TypeError, ValueError):
        return "eng"
    if not (-180.0 <= lon_f <= 180.0 and -90.0 <= lat_f <= 90.0):
        return "eng"
    # Québec
    if -80.0 <= lon_f <= -57.0 and 44.6 <= lat_f <= 62.6:
        return "fra"
    # Royaume-Uni / Irlande (avant le rectangle France, qui recouvre le sud UK)
    if -10.8 <= lon_f <= 1.85 and 49.85 <= lat_f <= 60.9:
        return "eng"
    # France, Belgique, Luxembourg, Suisse romande
    if -5.35 <= lon_f <= 8.4 and 42.2 <= lat_f <= 51.55:
        return "fra"
    # Maghreb côtier
    if -8.8 <= lon_f <= 11.6 and 30.2 <= lat_f <= 37.5:
        return "fra"
    return "eng"


def normalize_lang(raw: str | None) -> str:
    s = (raw or "").strip().lower()
    if s.startswith("fr") or s == "fra":
        return "fra"
    return "eng"
