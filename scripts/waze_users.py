#!/usr/bin/env python3
"""Wazers sur la carte (AddUser, RealtimeNetRec.c) + classement HTML.

Le client iPhone 2.4 n'a pas de RmUser : il met à jour via AddUser
(UpdateOrAdd) et le last-access. On renvoie les voisins à chaque At/SeeMe.
Max 50 wazers (RL_MAXIMUM_USERS_COUNT).
"""

from __future__ import annotations

import math
import time
from threading import Lock

_lock = Lock()
_peers: dict[str, dict] = {}
PEER_TTL = 90.0
BOT_IDS = (2001, 2002, 2003, 2004)
BOT_NAMES = ("lea", "marc", "nina", "tom")


def _ascii(s: str) -> str:
    return (
        (s or "")
        .replace(",", " ")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()[:63]
    )


def parse_at(body: bytes) -> dict | None:
    for line in body.replace(b"\r\n", b"\n").split(b"\n"):
        if not line.lower().startswith(b"at,"):
            continue
        f = line.decode("latin1", errors="replace").split(",")
        if len(f) < 3:
            return None
        try:
            lon, lat = float(f[1]), float(f[2])
        except ValueError:
            return None
        speed = 0.0
        az = 0
        if len(f) > 4:
            try:
                speed = float(f[4])
            except ValueError:
                speed = 0.0
        if len(f) > 5:
            try:
                az = int(float(f[5])) % 360
            except ValueError:
                az = 0
        return {"lon": lon, "lat": lat, "speed": speed, "azimuth": az}
    return None


def note_presence(peer: str, body: bytes) -> None:
    got = parse_at(body)
    if not got or not peer:
        return
    uid = 3000 + (abs(hash(peer)) % 900)
    with _lock:
        _peers[peer] = {
            "id": uid,
            "name": f"wazer{uid}",
            "lon": got["lon"],
            "lat": got["lat"],
            "speed": got["speed"],
            "azimuth": got["azimuth"],
            "seen": time.time(),
        }


def _expire_peers(now: float) -> None:
    dead = [k for k, v in _peers.items() if now - float(v.get("seen") or 0) > PEER_TTL]
    for k in dead:
        _peers.pop(k, None)


def _bots(lon: float, lat: float, now: float) -> list[dict]:
    """Quelques voisins autour du GPS, pour que la carte ne soit pas vide."""
    out = []
    for i, (uid, name) in enumerate(zip(BOT_IDS, BOT_NAMES)):
        ang = (now / 18.0 + i * 1.7) % (2 * math.pi)
        # ~80–180 m
        dlon = math.cos(ang) * (0.0011 + 0.0003 * i)
        dlat = math.sin(ang) * (0.0008 + 0.0002 * i)
        out.append(
            {
                "id": uid,
                "name": name,
                "lon": lon + dlon,
                "lat": lat + dlat,
                "speed": 28.0 + 6 * i,
                "azimuth": int((ang * 180 / math.pi) + 40 * i) % 360,
                "mood": 1 + (i % 6),
                "stars": 2 + (i % 3),
                "rank": 8 + i * 3,
                "points": 40 + i * 25,
                "title": "Wazer",
            }
        )
    return out


def add_user_line(u: dict) -> str:
    now = int(time.time())
    lon_u = int(round(float(u["lon"]) * 1e6))
    lat_u = int(round(float(u["lat"]) * 1e6))
    spd10 = int(round(float(u.get("speed") or 0) * 10))
    az = int(u.get("azimuth") or 0) % 360
    join = int(u.get("join") or now - 86400 * 400)
    return (
        f"AddUser,{int(u['id'])},{_ascii(u.get('name') or '')},"
        f"{lon_u},{lat_u},{az},{spd10},{now},"
        f"{int(u.get('mood') or 1)},{_ascii(u.get('title') or 'Wazer')},"
        f"0,{int(u.get('stars') or 3)},{int(u.get('rank') or 12)},"
        f"{int(u.get('points') or 40)},{join},"
        f"0,,F,,F,,0,0"
    )


def user_poll_lines(peer: str = "") -> list[str]:
    now = time.time()
    with _lock:
        _expire_peers(now)
        others = [dict(v) for k, v in _peers.items() if k != peer]
        me = _peers.get(peer)
    lon = lat = 0.0
    if me:
        lon, lat = float(me["lon"]), float(me["lat"])
    elif others:
        lon, lat = float(others[0]["lon"]), float(others[0]["lat"])
    else:
        return []
    rows = []
    seen_ids = set()
    for u in others:
        uid = int(u["id"])
        if uid in seen_ids:
            continue
        seen_ids.add(uid)
        rows.append(add_user_line(u))
    for u in _bots(lon, lat, now):
        if int(u["id"]) in seen_ids:
            continue
        seen_ids.add(int(u["id"]))
        rows.append(add_user_line(u))
    return rows[:40]


def scoreboard_rows(my_points: int, my_name: str = "ios6user") -> list[tuple[int, str, int]]:
    now = time.time()
    board = [(1, my_name, int(my_points))]
    for i, (uid, name) in enumerate(zip(BOT_IDS, BOT_NAMES)):
        board.append((8 + i * 3, name, 40 + i * 25 + int(now // 3600) % 7))
    board.sort(key=lambda r: -r[2])
    out = []
    for i, (_, name, pts) in enumerate(board, start=1):
        out.append((i, name, pts))
    return out


def scoreboard_html(my_points: int, my_name: str = "ios6user", lang: str = "fra") -> bytes:
    fr = lang != "eng"
    title = "Classement" if fr else "Scoreboard"
    pts_lbl = "points" if fr else "points"
    you = "Vous" if fr else "You"
    rows = scoreboard_rows(my_points, my_name)
    body_rows = []
    for rank, name, pts in rows:
        mine = " style='background:#E8D5FF'" if name == my_name else ""
        label = f"{name} ({you})" if name == my_name else name
        body_rows.append(
            f"<tr{mine}><td>{rank}</td><td>{label}</td><td>{pts}</td></tr>"
        )
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{ margin:0; background:#C5D0D4; color:#222; font:16px Helvetica,Arial,sans-serif; }}
h1 {{ margin:0; padding:14px 12px; background:#6B2FA0; color:#fff; font-size:18px; }}
table {{ width:100%; border-collapse:collapse; background:#fff; }}
th,td {{ padding:10px 12px; text-align:left; border-bottom:1px solid #ddd; }}
th {{ background:#E6D09A; }}
.sub {{ padding:10px 12px; color:#444; font-size:13px; }}
</style></head>
<body>
<h1>{title}</h1>
<div class="sub">{you}: {int(my_points)} {pts_lbl}</div>
<table>
<tr><th>#</th><th>Wazer</th><th>{pts_lbl}</th></tr>
{''.join(body_rows)}
</table>
</body></html>
"""
    return html.encode("utf-8")
