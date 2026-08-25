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
    assert rows[1].startswith("ReportAlertRes,6,")
    assert rows[2].startswith("AddAlert,")
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
    assert "eng,English" in conf.read_text(encoding="ascii")
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


def test_downsample() -> None:
    rows = [(1, i, 1, 0, 0, 10, 0, 0, 0, 0) for i in range(200)]
    out = _downsample_lines(rows, 20)
    assert len(out) <= 20
    assert out[0][1] == 0
    assert out[-1][1] == 199


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
        test_osrm_steps_by_distance,
        test_downsample,
        test_alerts,
        test_search_city,
        test_prompts,
        test_ascii_commas,
        test_major_ways,
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
