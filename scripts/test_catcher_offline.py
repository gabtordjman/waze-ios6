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
    _ascii,
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


def test_ascii_commas() -> None:
    assert "," not in _ascii("A, B")


def main() -> int:
    tests = [
        test_dest_label,
        test_via_not_dest,
        test_fill_gaps,
        test_alerts,
        test_search_city,
        test_prompts,
        test_ascii_commas,
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
