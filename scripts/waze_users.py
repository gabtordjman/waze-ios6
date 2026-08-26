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
_names: dict[str, str] = {}
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


def bind_peer(peer: str, name: str) -> None:
    """Associe l'IP du client au nick Login (compte unique par install)."""
    n = _ascii(name)
    if not peer or not n:
        return
    with _lock:
        _names[peer] = n[:16]


def note_presence(peer: str, body: bytes) -> None:
    got = parse_at(body)
    if not got or not peer:
        return
    uid = 3000 + (abs(hash(peer)) % 900)
    with _lock:
        name = _names.get(peer) or f"wazer{uid}"
        _peers[peer] = {
            "id": uid,
            "name": name,
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
                "points": 0,
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
        f"{int(u.get('points') or 0)},{join},"
        f"0,,F,,F,,0,0"
    )


def user_poll_lines(peer: str = "") -> list[str]:
    """Uniquement les vrais clients connectés — pas de silhouettes fictives."""
    now = time.time()
    with _lock:
        _expire_peers(now)
        others = [dict(v) for k, v in _peers.items() if k != peer]
    rows = []
    seen_ids: set[int] = set()
    for u in others:
        uid = int(u["id"])
        if uid in seen_ids:
            continue
        seen_ids.add(uid)
        rows.append(add_user_line(u))
    return rows[:40]


def scoreboard_rows(my_points: int, my_name: str = "ios6user") -> list[tuple[int, str, int, int]]:
    """(rank, name, points, rank_diff) — tout le monde à 0 pt au départ."""
    board: list[tuple[str, int, int]] = [(my_name, int(my_points), 0)]
    for i, (uid, name) in enumerate(zip(BOT_IDS, BOT_NAMES)):
        _ = uid
        board.append((name, 0, 0))
    board.sort(key=lambda r: (-r[1], r[0].lower()))
    out: list[tuple[int, str, int, int]] = []
    for i, (name, pts, diff) in enumerate(board, start=1):
        out.append((i, name, pts, diff))
    return out


def _scoreboard_labels(lang: str, period: str, geography: str) -> dict[str, str]:
    fr = lang != "eng"
    weekly = period != "all"
    local = geography not in ("global", "world")
    if fr:
        return {
            "title": "Classement",
            "weekly": "Semaine",
            "all": "Total",
            "country": "Pays",
            "global": "Monde",
            "everyone": "Tous",
            "wazer": "Wazer",
            "points": "pts",
            "you": "Vous",
            "show_me": "Me localiser",
            "left": "Suisse" if local else "Monde",
            "right": "Cette semaine" if weekly else "Tous les temps",
            "col_rank": "#",
            "col_name": "Wazer",
            "col_pts": "Points",
        }
    return {
        "title": "Scoreboard",
        "weekly": "Weekly",
        "all": "All time",
        "country": "Country",
        "global": "Global",
        "everyone": "Everyone",
        "wazer": "Wazer",
        "points": "pts",
        "you": "You",
        "show_me": "Show me",
        "left": "Country" if local else "Global",
        "right": "This week" if weekly else "All time",
        "col_rank": "#",
        "col_name": "Wazer",
        "col_pts": "Points",
    }


def scoreboard_html(
    my_points: int,
    my_name: str = "ios6user",
    lang: str = "fra",
    *,
    period: str = "weekly",
    geography: str = "country",
    width: int = 320,
    height: int = 400,
) -> bytes:
    lbl = _scoreboard_labels(lang, period, geography)
    rows = scoreboard_rows(my_points, my_name)
    my_row = next((r for r in rows if r[1] == my_name), (1, my_name, my_points, 0))
    my_rank, _, my_pts, my_diff = my_row

    body_rows = []
    for rank, name, pts, diff in rows:
        mine = name == my_name
        diff_html = ""
        if diff > 0:
            diff_html = f'<span class="up">+{diff}</span>'
        elif diff < 0:
            diff_html = f'<span class="down">{diff}</span>'
        cls = "row me" if mine else "row"
        label = f"{name} ({lbl['you']})" if mine else name
        body_rows.append(
            f'<tr class="{cls}">'
            f'<td class="rk">{rank}</td>'
            f'<td class="nm">{label}<span class="attr">{lbl["wazer"]}</span></td>'
            f'<td class="pt">{pts}</td>'
            f'<td class="df">{diff_html}</td>'
            f"</tr>"
        )

    p_weekly = "active" if period != "all" else ""
    p_all = "active" if period == "all" else ""
    g_country = "active" if geography not in ("global", "world") else ""
    g_global = "active" if geography in ("global", "world") else ""

    my_diff_html = ""
    if my_diff > 0:
        my_diff_html = f'<span class="up">+{my_diff}</span>'
    elif my_diff < 0:
        my_diff_html = f'<span class="down">{my_diff}</span>'

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width={width}, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>{lbl['title']}</title>
<style>
* {{ box-sizing:border-box; }}
html,body {{ margin:0; padding:0; height:100%; background:#C5D0D4; color:#222;
  font:14px Helvetica,Arial,sans-serif; }}
.wrap {{ min-height:100%; display:flex; flex-direction:column; max-width:{width}px; margin:0 auto; }}
.hdr {{ background:#6B2FA0; color:#fff; padding:10px 12px 8px; }}
.hdr h1 {{ margin:0; font-size:17px; font-weight:bold; }}
.subhdr {{ display:flex; justify-content:space-between; padding:6px 12px 8px;
  background:#E6D09A; color:#333; font-size:13px; font-weight:bold; border-bottom:1px solid #c8b070; }}
.tabs {{ display:flex; background:#ddd; border-bottom:1px solid #aaa; }}
.tabs a {{ flex:1; text-align:center; padding:8px 4px; text-decoration:none; color:#444;
  font-size:13px; font-weight:bold; border-right:1px solid #bbb; }}
.tabs a:last-child {{ border-right:0; }}
.tabs a.active {{ background:#fff; color:#337593; }}
.list {{ flex:1; overflow:auto; background:#fff; }}
table {{ width:100%; border-collapse:collapse; }}
tr.row td {{ padding:8px 6px; border-bottom:1px solid #e4e4e4; vertical-align:middle; }}
tr.row.me {{ background:#dceef5; }}
td.rk {{ width:28px; text-align:center; color:#666; font-weight:bold; }}
td.nm {{ font-weight:bold; color:#337593; }}
td.nm .attr {{ display:block; font-weight:normal; font-size:11px; color:#888; margin-top:2px; }}
td.pt {{ width:52px; text-align:right; font-weight:bold; }}
td.df {{ width:36px; text-align:center; font-size:12px; font-weight:bold; }}
.up {{ color:#2a8f2a; }}
.down {{ color:#c0392b; }}
.mebar {{ background:#f0f4f5; border-top:2px solid #6B2FA0; padding:8px 10px;
  display:flex; align-items:center; gap:6px; }}
.mebar .you {{ flex:1; font-weight:bold; color:#337593; font-size:14px; }}
.mebar .rk {{ color:#666; font-size:12px; }}
.mebar .pt {{ font-weight:bold; font-size:14px; min-width:48px; text-align:right; }}
.mebar .df {{ min-width:32px; text-align:center; }}
.mebtn {{ display:block; margin:6px 10px 10px; padding:8px; text-align:center;
  background:#337593; color:#fff; text-decoration:none; border-radius:6px;
  font-weight:bold; font-size:14px; }}
</style></head>
<body>
<div class="wrap">
  <div class="hdr"><h1>{lbl['title']}</h1></div>
  <div class="subhdr">
    <span>{lbl['left']}</span>
    <span>{lbl['right']}</span>
  </div>
  <div class="tabs period">
    <a class="{p_weekly}" href="?period=weekly&geography={geography}&lang={lang}">{lbl['weekly']}</a>
    <a class="{p_all}" href="?period=all&geography={geography}&lang={lang}">{lbl['all']}</a>
  </div>
  <div class="tabs geo">
    <a class="{g_country}" href="?period={period}&geography=country&lang={lang}">{lbl['country']}</a>
    <a class="{g_global}" href="?period={period}&geography=global&lang={lang}">{lbl['global']}</a>
  </div>
  <div class="list">
    <table>
      <tr style="background:#f5f5f5;font-size:12px;color:#666;">
        <th class="rk">{lbl['col_rank']}</th>
        <th>{lbl['col_name']}</th>
        <th class="pt">{lbl['col_pts']}</th>
        <th class="df"></th>
      </tr>
      {''.join(body_rows)}
    </table>
  </div>
  <div class="mebar">
    <div class="you">{lbl['you']} <span class="rk">#{my_rank}</span></div>
    <div class="pt">{my_pts} {lbl['points']}</div>
    <div class="df">{my_diff_html}</div>
  </div>
  <a class="mebtn" href="#rank{my_rank}">{lbl['show_me']}</a>
</div>
</body></html>
"""
    return html.encode("utf-8")

