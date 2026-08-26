#!/usr/bin/env python3
"""Tests hors téléphone : parseurs GPL 150, Via≠dest, reports, prompts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from waze_alerts import (  # noqa: E402
    add_alert_line,
    parse_report_alert,
    report_alert_response,
    reset_store,
    rm_alert_response,
)
from waze_route import (  # noqa: E402
    APPROACHING_DESTINATION,
    CONTINUE,
    TURN_LEFT,
    TURN_RIGHT,
    _ascii,
    _apply_osrm_steps,
    _downsample_lines,
    _fill_line_gaps,
    dest_label_from_request,
    via_label_from_steps,
)
from waze_search import search_body  # noqa: E402

REQ = (
    b"UID,1,wazeios6usercookie01\r\n"
    b"RoutingRequest,2,3,-1,1,-1,1000,6484696,46364581,-1,-1,-1,,T,"
    b"6482260,46373134,-1,-1,-1,Avenue Saint-Francois de Sales,T,T,T,24,"
    b"1,F,2,T,3,F,4,F,5,F,6,T,7,T,8,T,10,F,12,F,13,F,16,T,0,,"
    b"Thonon-les-Bains,Auvergne-Rhone-Alpes,53609,0,F\r\n"
)


def test_dest_label() -> None:
    dest = dest_label_from_request(REQ)
    assert "Saint-Francois" in dest, dest
    assert "Thonon" in dest, dest
    assert "," not in dest, dest


def test_via_not_dest() -> None:
    dest = dest_label_from_request(REQ)
    steps = [
        {"name": "Route de Thonon", "dist": 900},
        {"name": "Avenue Saint-Francois de Sales", "dist": 80},
        {"name": "", "dist": 10},
    ]
    via = via_label_from_steps(steps, dest)
    assert via == "Route de Thonon", via
    assert via != dest


def test_fill_gaps() -> None:
    a = (1, 0, 1, 0, 0, 10, 100, 0, 0, 0)
    b = (1, 2, 1, 20_000, 0, 10, 20_100, 0, 20_000, 0)
    mid = (1, 1, 1, 10_000, 0, 10, 20_000, 0, 100, 0)
    out = _fill_line_gaps([a, b], [a, mid, b])
    assert [r[1] for r in out] == [0, 1, 2], [r[1] for r in out]


def test_fill_along_same_tiles() -> None:
    from waze_route import _fill_along_route

    a = (1, 0, 1, 0, 0, 10, 400, 0, 0, 0, 0, 1)
    mid = (1, 1, 1, 2_000, 0, 10, 3_600, 0, 400, 0, 1, 2)
    b = (1, 2, 1, 5_000, 0, 10, 6_000, 0, 3_600, 0, 2, 3)
    other_tile = (9, 9, 1, 2_000, 0, 10, 3_600, 0, 400, 0, 1, 2)
    pts = [(x, 0) for x in range(0, 6_001, 400)]
    out = _fill_along_route([a, b], [a, mid, b, other_tile], pts)
    assert [r[1] for r in out] == [0, 1, 2], [r[1] for r in out]
    assert all(r[0] == 1 for r in out)


def test_fill_inserts_close_gap() -> None:
    """Bouts à < 50 m sans nœud commun : il manque le morceau du milieu."""
    from waze_route import _fill_along_route

    a = _line(1, 0, 0, 0, 3_000, 0, 0, 1)
    mid = _line(1, 1, 3_000, 0, 3_400, 0, 1, 2)
    b = _line(1, 2, 3_400, 0, 8_000, 0, 2, 3)
    pts = [(x, 0) for x in range(0, 8_001, 200)]
    out = _fill_along_route([a, b], [a, mid, b], pts)
    assert [r[1] for r in out] == [0, 1, 2], [r[1] for r in out]


def test_fill_across_tiles() -> None:
    """Trou A→C : insérer la tuile B du couloir (sinon overlay coupé)."""
    from waze_route import _fill_along_route

    a = _line(1, 0, 0, 0, 3_000, 0, 0, 1)
    mid = _line(2, 1, 3_000, 0, 5_000, 0, 10, 11)
    b = _line(3, 2, 5_000, 0, 8_000, 0, 20, 21)
    pts = [(x, 0) for x in range(0, 8_001, 200)]
    out = _fill_along_route([a, b], [a, mid, b], pts)
    assert [r[1] for r in out] == [0, 1, 2], [r[1] for r in out]
    assert [r[0] for r in out] == [1, 2, 3], [r[0] for r in out]


def _run_match(index, pts, length=1_200, duration=120):
    import waze_route as wr

    old_idx = wr._load_line_index
    old_names = wr._load_osm_names
    wr._load_line_index = lambda **_k: index
    wr._load_osm_names = lambda: {}
    try:
        return wr._match_segments(pts, length, duration)
    finally:
        wr._load_line_index = old_idx
        wr._load_osm_names = old_names


def _line(tid, li, x1, y1, x2, y2, n1, n2):
    return (
        tid,
        li,
        1,
        (x1 + x2) // 2,
        (y1 + y2) // 2,
        max(abs(x2 - x1) + abs(y2 - y1), 1) // 10,
        x2,
        y2,
        x1,
        y1,
        n1,
        n2,
    )


def test_match_records_turn() -> None:
    """Sans skip collant : les 3 rues d'un L sont toutes sur le tracé."""
    a = _line(1, 0, 0, 0, 4_000, 0, 0, 1)
    b = _line(1, 1, 4_000, 0, 4_000, 4_000, 1, 2)
    c = _line(1, 2, 4_000, 4_000, 0, 4_000, 2, 3)
    pts = (
        [(x, 0) for x in range(0, 4_001, 400)]
        + [(4_000, y) for y in range(400, 4_001, 400)]
        + [(x, 4_000) for x in range(3_600, -1, -400)]
    )
    ids = [s["line"] for s in _run_match([a, b, c], pts)]
    assert ids == [0, 1, 2], ids


def test_match_stays_on_main() -> None:
    """Tout droit : ni ruelle perpendiculaire ni parallèle à 80 m."""
    main = _line(1, 0, 0, 0, 8_000, 0, 0, 1)
    side = _line(1, 1, 4_000, 0, 4_000, 4_000, 1, 2)
    para = _line(1, 2, 0, 700, 8_000, 700, 3, 4)
    pts = [(x, 0) for x in range(0, 8_001, 200)]
    ids = [s["line"] for s in _run_match([main, side, para], pts, 800, 80)]
    assert ids == [0], ids


def test_match_ignores_spur_when_osrm_cuts_corner() -> None:
    """OSRM coupe le carrefour (~45°) : la ruelle touche le trajet (dist 0)
    et passe HEADING_MAX, mais son autre bout n'est pas sur l'itinéraire."""
    chunks = [
        _line(1, i, x, 0, x + 1_000, 0, i, i + 1)
        for i, x in enumerate(range(0, 8_000, 1_000))
    ]
    spurs = [
        _line(1, 100 + i, x, 0, x, 2_500, i, 50 + i)
        for i, x in enumerate(range(1_000, 8_000, 1_000))
    ]
    pts = []
    for x in range(0, 8_001, 200):
        y = 180 if x % 1_000 == 0 and 0 < x < 8_000 else 0
        pts.append((x, y))
    ids = [s["line"] for s in _run_match(chunks + spurs, pts, 800, 80)]
    assert ids == [0, 1, 2, 3, 4, 5, 6, 7], ids


def test_match_ignores_diagonal_fork() -> None:
    """Fourche à 11° : même cap, un bout sur l'OSRM, l'autre s'éloigne."""
    main = [
        _line(1, 0, 0, 0, 4_000, 0, 0, 1),
        _line(1, 1, 4_000, 0, 8_000, 0, 1, 2),
    ]
    fork = _line(1, 9, 4_000, 0, 8_000, 800, 1, 3)
    pts = [(x, 0) for x in range(0, 8_001, 200)]
    ids = [s["line"] for s in _run_match(main + [fork], pts, 800, 80)]
    assert ids == [0, 1], ids


def test_match_does_not_detour_on_parallel() -> None:
    """Trou sur la rue principale : ne pas glisser sur la parallèle à 45 m
    (join flou + left_prev + fill)."""
    south = [
        _line(1, 0, 0, 0, 3_000, 0, 0, 1),
        _line(1, 1, 5_000, 0, 8_000, 0, 2, 3),
    ]
    north = [
        _line(1, 9, 0, 400, 4_000, 400, 10, 11),
        _line(1, 10, 4_000, 400, 8_000, 400, 11, 12),
    ]
    pts = [(x, 0) for x in range(0, 8_001, 200)]
    ids = [s["line"] for s in _run_match(south + north, pts, 800, 80)]
    assert 9 not in ids and 10 not in ids, ids
    assert ids[0] == 0 and ids[-1] == 1, ids


def test_long_line_matches_at_start() -> None:
    """Le milieu d'une longue rue ne doit pas la faire rater au départ."""
    import waze_route as wr

    long = (1, 0, 1, 10_000, 0, 200, 20_000, 0, 0, 0, 0, 1)
    alley = (1, 1, 1, 200, 500, 10, 400, 500, 0, 500, 2, 3)
    index = [long, alley]
    pts = [(x, 0) for x in range(0, 2_001, 200)]
    old_idx = wr._load_line_index
    old_names = wr._load_osm_names
    wr._load_osm_names = lambda: {}
    wr._load_line_index = lambda **_k: index
    try:
        segs = wr._match_segments(pts, 200, 20)
    finally:
        wr._load_line_index = old_idx
        wr._load_osm_names = old_names
    ids = [s["line"] for s in segs]
    assert ids == [0], ids


def test_pin_reaches_driveway() -> None:
    """Le bout hors couloir (allée / maison) doit quand même être sur le tracé."""
    mains = [
        _line(1, 0, 0, 0, 4_000, 0, 0, 1),
        _line(1, 1, 4_000, 0, 8_000, 0, 1, 2),
    ]
    drive = _line(1, 9, 8_000, 0, 8_200, 800, 2, 3)
    pts = [(x, 0) for x in range(0, 8_001, 400)]
    pts.append((8_100, 400))
    ids = [s["line"] for s in _run_match(mains + [drive], pts, 900, 90)]
    assert ids[-1] == 9, ids


def test_pin_reaches_driveway_without_shared_node() -> None:
    """Allée qui touche la rue sans le même nœud .wzm (trou à la maison)."""
    mains = [
        _line(1, 0, 0, 0, 4_000, 0, 0, 1),
        _line(1, 1, 4_000, 0, 8_000, 0, 1, 2),
    ]
    drive = _line(1, 9, 8_000, 0, 8_200, 800, 99, 100)
    pts = [(x, 0) for x in range(0, 8_001, 400)]
    pts.append((8_100, 400))
    ids = [s["line"] for s in _run_match(mains + [drive], pts, 900, 90)]
    assert ids[-1] == 9, ids


def test_pin_reaches_house_at_start() -> None:
    """Le GPS est dans l'allée au départ : l'overlay doit commencer là."""
    mains = [
        _line(1, 0, 0, 0, 4_000, 0, 0, 1),
        _line(1, 1, 4_000, 0, 8_000, 0, 1, 2),
    ]
    drive = _line(1, 9, 0, 800, 0, 0, 99, 100)
    pts = [(0, 400), (0, 0)] + [(x, 0) for x in range(400, 8_001, 400)]
    ids = [s["line"] for s in _run_match(mains + [drive], pts, 900, 90)]
    assert ids[0] == 9, ids


def test_resample_caps_points() -> None:
    from waze_route import _resample_pts

    pts = [(i, 0) for i in range(500)]
    out = _resample_pts(pts, 80)
    assert 2 <= len(out) <= 80
    assert out[0] == pts[0] and out[-1] == pts[-1]


def test_alerts() -> None:
    reset_store()
    body = (
        b"At,6.48470,46.36458,0.0,339,0,-1,-1\n"
        b"ReportAlert,1,test desc,1,,,F,F,,0,\n"
    )
    parsed = parse_report_alert(body)
    assert parsed is not None
    assert parsed["type"] == 1
    assert abs(parsed["lon"] - 6.48470) < 1e-4
    rows = report_alert_response(parsed)
    assert rows[0] == "RC,200,OK"
    assert rows[1] == "ReportAlertRes,6,Road report,"
    assert not any(r.startswith("UpdateUserPoints") for r in rows)
    assert rows[-1].startswith("AddAlert,")
    line = add_alert_line(
        {
            "id": 1001,
            "type": 1,
            "lon": 6.4847,
            "lat": 46.36458,
            "direction": 1,
            "subtype": 0,
            "by_me": True,
            "when": 1700000000,
        }
    )
    parts = line.split(",")
    assert parts[0] == "AddAlert"
    assert parts[1] == "1001"
    assert parts[2] == "1"
    assert parts[3] == "6484700"
    assert parts[4] == "46364580"
    rm = rm_alert_response(1001)
    assert rm[1] == "RmAlert,1001"


def test_search_city() -> None:
    body = search_body(
        "Avenue Saint-Francois de Sales",
        lon=6.48,
        lat=46.36,
        single_search=True,
    )
    text = body.decode("ascii")
    assert "AddressCandidate,waze," in text, text[:200]
    line = [ln for ln in text.replace("\n", "\r\n").split("\r\n") if ln.startswith("AddressCandidate")][0]
    f = line.split(",")
    assert f[1] == "waze"
    city, street = f[6], f[7]
    assert city, line
    assert street, line
    assert "," not in city + street


def test_geo_french_and_thin_streets() -> None:
    import rts_catcher_min as rc

    text = rc.BODY_GEO.decode("ascii")
    assert "GeoServerConfig,1,world,fra," in text, text[:200]
    assert ",Prompts,Name,fra" in text
    assert ",Streets,Thickness,1" in text
    assert ",Streets,Color,#9A9A9A" in text
    assert ",Map,Background,#C5D0D4" in text
    assert ",System,Language,fra" in text
    assert ",Scoreboard,Feature enabled,no" in text
    assert ",Editor,Gray scale,yes" in text
    assert ",User,Show points ticker,yes" in text
    # VPS : pas de phone.sh — UpdateConfig écrit aussi le fichier `user`.
    assert "UpdateConfig,preferences,Editor,Gray scale,yes" in text
    assert "UpdateConfig,user,User,Show points ticker,yes" in text
    assert "UpdateConfig,preferences,Scoreboard,Feature enabled,no" in text
    assert "UpdateConfig,preferences,System,Language,fra" in text
    assert "UpdateConfig,preferences,Prompts,Name,fra" in text


def test_geo_english_us() -> None:
    import rts_catcher_min as rc

    text = rc._body_geo("eng").decode("ascii")
    assert "GeoServerConfig,1,world,eng," in text
    assert ",Prompts,Name,eng" in text
    assert ",System,Language,eng" in text
    assert "UpdateConfig,preferences,Prompts,Name,eng" in text


def test_lang_from_gps() -> None:
    from waze_lang import client_lang

    assert client_lang(6.4847, 46.3646) == "fra"
    assert client_lang(2.35, 48.85) == "fra"
    assert client_lang(-73.98, 40.75) == "eng"
    assert client_lang(-0.12, 51.50) == "eng"
    assert client_lang(-71.21, 46.81) == "fra"
    assert client_lang(None, None) == "eng"


def test_update_config_on_first_at() -> None:
    """Un client public ne refait jamais GetGeo : les prefs partent au 1er At."""
    import rts_catcher_min as rc

    rc._prefs_pushed.clear()
    at = b"At,6.48470,46.36458,0.0,339,0,-1,-1\n"
    first = rc._once_update_config("203.0.113.9", at)
    assert first == rc._update_config_lines("fra")
    assert not rc._once_update_config("203.0.113.9", at)
    text = "\r\n".join(rc._realtime_tail(at, first))
    assert "UpdateConfig,preferences,Editor,Gray scale,yes" in text
    assert "UpdateConfig,user,User,Show points ticker,yes" in text
    assert "UpdateConfig,preferences,Scoreboard,Feature enabled,no" in text
    assert "UpdateConfig,preferences,System,Language,fra" in text


def test_prompts() -> None:
    conf = (
        ROOT
        / "mitm"
        / "fake-resources"
        / "resources"
        / "config"
        / "1.0"
        / "1"
        / "prompts.conf"
    )
    assert conf.is_file(), conf
    ptext = conf.read_text(encoding="utf-8")
    assert "eng,English" in ptext
    assert "fra,French" in ptext or "fra,Français" in ptext
    click = (
        ROOT
        / "mitm"
        / "fake-resources"
        / "resources"
        / "sounds"
        / "1.0"
        / "eng"
        / "click.mp3"
    )
    assert click.is_file() and click.stat().st_size > 0, click
    lang_conf = (
        ROOT
        / "mitm"
        / "fake-resources"
        / "resources"
        / "config"
        / "1.0"
        / "1"
        / "lang.conf"
    )
    langs = lang_conf.read_text(encoding="utf-8")
    assert "fra," in langs, langs
    fra = ROOT / "mitm" / "fake-resources" / "resources" / "langs" / "lang.fra"
    assert fra.is_file() and "Route found=" in fra.read_text(encoding="utf-8")
    eng = ROOT / "mitm" / "fake-resources" / "resources" / "langs" / "lang.eng"
    assert eng.is_file() and "lang=English" in eng.read_text(encoding="utf-8")
    voice = (
        ROOT
        / "mitm"
        / "fake-resources"
        / "resources"
        / "sounds"
        / "1.0"
        / "fra"
        / "TurnLeft.mp3"
    )
    assert voice.is_file() and voice.stat().st_size > 400, voice


def test_osrm_steps_by_distance() -> None:
    segs = [
        {"len": 100, "instr": CONTINUE, "dest_name": "A"},
        {"len": 100, "instr": CONTINUE, "dest_name": "B"},
        {"len": 100, "instr": CONTINUE, "dest_name": "C"},
        {"len": 100, "instr": CONTINUE, "dest_name": "D"},
    ]
    steps = [
        {"instr": CONTINUE, "dist": 100, "name": "A"},
        {"instr": TURN_LEFT, "dist": 100, "name": "Main St"},
        {"instr": CONTINUE, "dist": 100, "name": "C"},
        {"instr": APPROACHING_DESTINATION, "dist": 100, "name": "D"},
    ]
    _apply_osrm_steps(segs, steps)
    assert segs[1]["instr"] == TURN_LEFT, [s["instr"] for s in segs]
    assert segs[1]["dest_name"] == "Main St"
    assert segs[-1]["instr"] == APPROACHING_DESTINATION


def test_osrm_steps_clear_geometry_turns() -> None:
    segs = [
        {"len": 100, "instr": TURN_LEFT, "dest_name": "A"},
        {"len": 100, "instr": TURN_RIGHT, "dest_name": "B"},
        {"len": 100, "instr": CONTINUE, "dest_name": "C"},
    ]
    _apply_osrm_steps(segs, [{"instr": CONTINUE, "dist": 100, "name": "A"}])
    assert segs[0]["instr"] == CONTINUE
    assert segs[1]["instr"] == CONTINUE
    assert segs[2]["instr"] == APPROACHING_DESTINATION


def test_drop_kinks_skips_short_hook() -> None:
    from waze_route import _drop_kinks

    a = _line(1, 0, 0, 0, 4_000, 0, 0, 1)
    hook = _line(1, 1, 4_000, 0, 4_000, 280, 1, 2)
    b = _line(1, 2, 4_000, 0, 8_000, 0, 1, 3)
    pts = [(x, 0) for x in range(0, 8_001, 200)]
    out = _drop_kinks([a, hook, b], pts)
    assert [r[1] for r in out] == [0, 2], [r[1] for r in out]


def test_resample_keeps_corner() -> None:
    from waze_route import _resample_pts

    pts = [(x, 0) for x in range(0, 4_001, 200)] + [(4_000, y) for y in range(200, 4_001, 200)]
    out = _resample_pts(pts, 20)
    assert out[0] == pts[0] and out[-1] == pts[-1]
    assert any(p[0] == 4_000 and p[1] == 0 for p in out) or any(
        abs(p[0] - 4_000) < 400 and abs(p[1]) < 400 for p in out
    )


def test_wazers_adduser() -> None:
    from waze_users import add_user_line, user_poll_lines, note_presence, bind_peer

    line = add_user_line(
        {
            "id": 2001,
            "name": "lea",
            "lon": 6.4847,
            "lat": 46.36458,
            "speed": 4.5,
            "azimuth": 90,
            "mood": 1,
        }
    )
    parts = line.split(",")
    assert parts[0] == "AddUser"
    assert parts[1] == "2001"
    assert parts[2] == "lea"
    assert parts[3] == "6484700"
    note_presence("192.168.1.60", b"At,6.48470,46.36458,0.0,12,90,-1,-1\n")
    assert user_poll_lines("192.168.1.60") == []
    rows = user_poll_lines("192.168.1.99")
    assert any(r.startswith("AddUser,") for r in rows)
    bind_peer("10.0.0.8", "alice")
    note_presence("10.0.0.8", b"At,6.48470,46.36458,0.0,12,90,-1,-1\n")
    named = user_poll_lines("10.0.0.9")
    assert any(",alice," in r for r in named), named


def test_downsample() -> None:
    rows = [(1, i, 1, 0, 0, 10, 0, 0, 0, 0) for i in range(200)]
    out = _downsample_lines(rows, 20)
    assert len(out) <= 20
    assert out[0][1] == 0
    assert out[-1][1] == 199


def test_trace_joins_only_connected() -> None:
    from waze_route import _can_join

    a = (1, 0, 1, 0, 0, 10, 100, 0, 0, 0, 0, 1)
    near = (1, 1, 1, 80, 0, 10, 180, 0, 100, 0, 1, 2)
    far = (1, 2, 1, 40_000, 40_000, 10, 40_100, 40_000, 40_000, 40_000, 0, 1)
    assert _can_join(a, near)
    assert not _can_join(a, far)


def test_from_node_on_wire() -> None:
    from waze_route import CONTINUE, _route_segment_rows

    segs = [
        {
            "tid": 9,
            "line": 3,
            "ts": 1,
            "len": 10,
            "time": 2,
            "instr": CONTINUE,
            "dest_name": "",
            "from_node": 7,
        }
    ]
    row = _route_segment_rows(1, 1, segs)[0]
    assert ",3,7,10," in row, row


def test_ascii_commas() -> None:
    assert "," not in _ascii("A, B")


def test_major_ways() -> None:
    from wazemap import ROAD_FREEWAY, ROAD_STREET, major_ways

    ways = [
        (ROAD_STREET, [(0, 0), (1, 1)], "Rue"),
        (ROAD_FREEWAY, [(0, 0), (2, 2)], "A40"),
    ]
    out = major_ways(ways)
    assert len(out) == 1 and out[0][2] == "A40"


def test_street_zoom_not_yellow() -> None:
    from wazemap import ROAD_PRIMARY, ROAD_SECONDARY, ROAD_STREET, display_category

    assert display_category(ROAD_PRIMARY, 0) == ROAD_PRIMARY
    assert display_category(ROAD_SECONDARY, 0) == ROAD_SECONDARY
    assert display_category(ROAD_PRIMARY, 2) == ROAD_PRIMARY
    from wazemap import OSM_CATEGORY, ROAD_STREET

    assert OSM_CATEGORY["tertiary"] == ROAD_STREET
    assert OSM_CATEGORY["residential"] == ROAD_STREET


def test_no_negative_line_stubs() -> None:
    import waze_route as wr

    old_osrm = wr.osrm_route
    old_wzm = wr.WZM
    wr.WZM = ROOT / "maps" / "_missing_" / "map77001.wzm"
    wr._lines_cache = None
    wr._wzm_diag_cache = None
    wr.osrm_route = lambda *_a, **_k: (
        [(6_484_680, 46_364_580), (6_482_260, 46_373_134)],
        1000,
        120,
        [
            {
                "lon": 6_484_680,
                "lat": 46_364_580,
                "instr": CONTINUE,
                "name": "A",
                "dist": 500,
                "time": 60,
            }
        ],
    )
    try:
        body = wr.routing_body(
            1, 6.48468, 46.36458, 6.48226, 46.37313, dest_name="Test"
        )
    finally:
        wr.osrm_route = old_osrm
        wr.WZM = old_wzm
        wr._lines_cache = None
        wr._wzm_diag_cache = None
    text = body.decode("ascii")
    assert ",-1," not in text, text[:500]
    assert "RoutePoints," in text
    assert "RouteSegments," not in text


def test_inspect_selftest() -> None:
    from wazemap import TileBuilder, write_wzm, tile_id, tile_edges, ROAD_STREET
    import time

    tid = tile_id(6_484_638, 46_364_603, 0)
    west, east, south, north, _ = tile_edges(tid)
    b = TileBuilder(tid)
    b.add_polyline(
        ROAD_STREET,
        [(west + 2000, south + 2000), (west + 4000, south + 4000)],
        name="Test St",
    )
    out = ROOT / "logs" / "inspect-test.wzm"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_wzm(out, {tid: b.payload(int(time.time()))}, (west, south, east, north))
    from wazemap import summarize_wzm

    s = summarize_wzm(out, 6.484638, 46.364603)
    assert s["scales"][0]["lines"] >= 1, s
    assert s["gps_inside"] is True
    assert s["gps_lines"] >= 1
    out.unlink(missing_ok=True)


def main() -> int:
    tests = [
        test_dest_label,
        test_via_not_dest,
        test_fill_gaps,
        test_fill_along_same_tiles,
        test_fill_inserts_close_gap,
        test_fill_across_tiles,
        test_match_records_turn,
        test_match_stays_on_main,
        test_match_ignores_spur_when_osrm_cuts_corner,
        test_match_ignores_diagonal_fork,
        test_match_does_not_detour_on_parallel,
        test_long_line_matches_at_start,
        test_pin_reaches_driveway,
        test_pin_reaches_driveway_without_shared_node,
        test_pin_reaches_house_at_start,
        test_resample_caps_points,
        test_osrm_steps_by_distance,
        test_osrm_steps_clear_geometry_turns,
        test_drop_kinks_skips_short_hook,
        test_resample_keeps_corner,
        test_wazers_adduser,
        test_downsample,
        test_trace_joins_only_connected,
        test_from_node_on_wire,
        test_alerts,
        test_search_city,
        test_prompts,
        test_geo_french_and_thin_streets,
        test_geo_english_us,
        test_lang_from_gps,
        test_update_config_on_first_at,
        test_ascii_commas,
        test_major_ways,
        test_street_zoom_not_yellow,
        test_no_negative_line_stubs,
        test_inspect_selftest,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"OK {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
