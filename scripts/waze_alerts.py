#!/usr/bin/env python3
"""Reports Waze 2.4 / protocole 150.

Client : At + ReportAlert (RealtimeNet.c RTNet_ReportAlertAtPosition).
Carte  : AddAlert (RealtimeNetRec.c AddAlert) — coords en micro-degrés.
Ack    : ReportAlertRes,<points>,<title>,<msg>
"""

from __future__ import annotations

import time
from threading import Lock

_lock = Lock()
_next_id = 1001
_store: dict[int, dict] = {}


def reset_store() -> None:
    global _next_id
    with _lock:
        _store.clear()
        _next_id = 1001


def _ascii(s: str) -> str:
    return (
        (s or "")
        .replace(",", " ")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()[:80]
    )


def parse_at_gps(body: bytes) -> tuple[float, float] | None:
    for line in body.replace(b"\r\n", b"\n").split(b"\n"):
        if not line.lower().startswith(b"at,"):
            continue
        f = line.decode("latin1", errors="replace").split(",")
        if len(f) < 3:
            return None
        try:
            return float(f[1]), float(f[2])
        except ValueError:
            return None
    return None


def parse_report_alert(body: bytes) -> dict | None:
    """ReportAlert,<type>,<desc>,<direction>,<image>,<tw>,<fb>,<group>,<subType>,<voice>"""
    gps = parse_at_gps(body)
    for line in body.replace(b"\r\n", b"\n").split(b"\n"):
        if not line.lower().startswith(b"reportalert,"):
            continue
        f = line.decode("latin1", errors="replace").split(",")
        if len(f) < 2:
            return None
        try:
            typ = int(f[1])
        except ValueError:
            return None
        desc = _ascii(f[2]) if len(f) > 2 else ""
        try:
            direction = int(f[3]) if len(f) > 3 and f[3] not in ("",) else 1
        except ValueError:
            direction = 1
        try:
            subtype = int(f[8]) if len(f) > 8 and f[8] not in ("",) else 0
        except ValueError:
            subtype = 0
        lon = lat = 0.0
        if gps:
            lon, lat = gps
        return {
            "type": typ,
            "desc": desc,
            "direction": direction,
            "subtype": subtype,
            "lon": lon,
            "lat": lat,
        }
    return None


def parse_rm_alert(body: bytes) -> int | None:
    for line in body.replace(b"\r\n", b"\n").split(b"\n"):
        if not line.lower().startswith(b"reportrmalert,"):
            continue
        f = line.decode("latin1", errors="replace").split(",")
        if len(f) < 2:
            return None
        try:
            return int(f[1])
        except ValueError:
            return None
    return None


def add_alert_line(alert: dict) -> str:
    """Tous les champs lus par AddAlert() — description vide = virgule sautée."""
    aid = int(alert["id"])
    typ = int(alert["type"])
    lon = int(round(float(alert["lon"]) * 1e6))
    lat = int(round(float(alert["lat"]) * 1e6))
    direction = int(alert.get("direction") or 1)
    subtype = int(alert.get("subtype") or 0)
    by_me = "T" if alert.get("by_me") else "F"
    when = int(alert.get("when") or time.time())
    return (
        f"AddAlert,{aid},{typ},{lon},{lat},-1,-1,{direction},90,"
        f",{when},ios6user,{by_me},,0,0,,,,F,F,,,,F,,,0,0,F,{subtype},0,F,,0"
    )


def store_report(parsed: dict) -> dict:
    global _next_id
    with _lock:
        aid = _next_id
        _next_id += 1
        rec = {
            "id": aid,
            "type": parsed["type"],
            "desc": parsed.get("desc") or "",
            "direction": parsed.get("direction") or 1,
            "subtype": parsed.get("subtype") or 0,
            "lon": parsed["lon"],
            "lat": parsed["lat"],
            "by_me": True,
            "when": int(time.time()),
        }
        _store[aid] = rec
        return rec


def remove_alert(aid: int) -> bool:
    with _lock:
        return _store.pop(aid, None) is not None


def all_add_alert_lines() -> list[str]:
    with _lock:
        return [add_alert_line(a) for a in _store.values()]


def report_alert_response(parsed: dict) -> list[str]:
    rec = store_report(parsed)
    return [
        "RC,200,OK",
        "ReportAlertRes,6,Thank you,Report received",
        add_alert_line(rec),
    ]


def poll_alert_lines() -> list[str]:
    extra = all_add_alert_lines()
    if not extra:
        return ["RC,200,OK"]
    return ["RC,200,OK", *extra]


def rm_alert_response(aid: int) -> list[str]:
    remove_alert(aid)
    return ["RC,200,OK", f"RmAlert,{aid}"]
