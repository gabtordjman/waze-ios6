#!/usr/bin/env python3
"""Reports Waze 2.4 / protocole 150.

Client : At + ReportAlert (RealtimeNet.c RTNet_ReportAlertAtPosition).
Carte  : AddAlert (RealtimeNetRec.c AddAlert) — coords en micro-degrés.
Ack    : ReportAlertRes,<points>,<title>,<msg>
         msg vide → pas de popup ; points > 0 → ticker en haut (report_event).
Points : comptés dans ReportAlertRes (pas de UpdateUserPoints en double).
Durée  : ~30 min, puis RmAlert. Fichier logs/alerts.json pour survivre
à un relance du catcher.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parents[1]
STORE_FILE = ROOT / "logs" / "alerts.json"
POINTS_FILE = ROOT / "logs" / "points.json"
ALERT_TTL = 1800
REPORT_POINTS = 6
START_POINTS = 0

_lock = Lock()
_next_id = 1001
_store: dict[int, dict] = {}
_points = START_POINTS
_loaded = False


def _ensure_loaded() -> None:
    global _next_id, _points, _loaded
    if _loaded:
        return
    _loaded = True
    try:
        if STORE_FILE.is_file():
            data = json.loads(STORE_FILE.read_text(encoding="utf-8"))
            for rec in data.get("alerts") or []:
                aid = int(rec["id"])
                _store[aid] = rec
                _next_id = max(_next_id, aid + 1)
    except Exception:
        pass
    try:
        if POINTS_FILE.is_file():
            _points = int(json.loads(POINTS_FILE.read_text(encoding="utf-8")).get("points") or START_POINTS)
    except Exception:
        _points = START_POINTS


def _save_locked() -> None:
    STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        STORE_FILE.write_text(
            json.dumps({"alerts": list(_store.values())}, indent=0),
            encoding="utf-8",
        )
    except Exception:
        pass
    try:
        POINTS_FILE.write_text(
            json.dumps({"points": _points}),
            encoding="utf-8",
        )
    except Exception:
        pass


def reset_store() -> None:
    global _next_id, _points, _loaded
    with _lock:
        _store.clear()
        _next_id = 1001
        _points = START_POINTS
        _loaded = True
        _save_locked()


def total_points() -> int:
    _ensure_loaded()
    with _lock:
        return int(_points)


def add_points(delta: int) -> int:
    global _points
    _ensure_loaded()
    with _lock:
        _points = max(0, int(_points) + int(delta))
        _save_locked()
        return _points


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


def _expire_locked(now: float | None = None) -> list[int]:
    now = time.time() if now is None else now
    gone = [
        aid
        for aid, rec in list(_store.items())
        if now - float(rec.get("when") or 0) > ALERT_TTL
    ]
    for aid in gone:
        _store.pop(aid, None)
    if gone:
        _save_locked()
    return gone


def store_report(parsed: dict) -> dict:
    global _next_id
    _ensure_loaded()
    with _lock:
        _expire_locked()
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
        _save_locked()
        return rec


def remove_alert(aid: int) -> bool:
    _ensure_loaded()
    with _lock:
        ok = _store.pop(aid, None) is not None
        if ok:
            _save_locked()
        return ok


def live_alert_lines() -> list[str]:
    _ensure_loaded()
    with _lock:
        gone = _expire_locked()
        live = [add_alert_line(a) for a in _store.values()]
    return [f"RmAlert,{aid}" for aid in gone] + live


def all_add_alert_lines() -> list[str]:
    return live_alert_lines()


def report_alert_response(parsed: dict, lang: str = "fra") -> list[str]:
    rec = store_report(parsed)
    add_points(REPORT_POINTS)
    # GPL : popup seulement si msg non vide. Points > 0 → ticker
    # (editor_points_display_new_points_timed, report_event).
    # Titre non vide pour que le parseur avale bien les 3 champs.
    _ = lang
    return [
        "RC,200,OK",
        f"ReportAlertRes,{REPORT_POINTS},Road report,",
        add_alert_line(rec),
    ]


def poll_alert_lines() -> list[str]:
    extra = live_alert_lines()
    if not extra:
        return ["RC,200,OK"]
    return ["RC,200,OK", *extra]


def rm_alert_response(aid: int) -> list[str]:
    remove_alert(aid)
    return ["RC,200,OK", f"RmAlert,{aid}"]
