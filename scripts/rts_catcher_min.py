#!/usr/bin/env python3
"""CATCHER_REV=proto150-route-20260826i

Deux protocoles, deux stratégies — le catcher détecte lequel parle le client.

1. Protocole 150 (Waze 2.4.0.0, dernière version publiée sous GPL v2).
   Source complète : github.com/mkoloberdin/waze, branche `iphone`.
   `Realtime/RealtimeNetRec.c` → OnLoginResponse lit exactement 11 champs :
     id, cookie, rank, points, rating, prevRank, addon, pointsTs,
     exclusiveMoods, serverMaxProtocol, serverVersion
   On connaît donc la réponse exacte : pas de devinette, login OK du 1er coup.
   Requête reconnaissable à `Login,<entier>,...` (le protocole est en tête).

2. Protocole 202 (Waze 3.9.6.1, propriétaire — réécriture complète en v3).
   Le protocole est déporté dans `ClientInfo,202,...` et LoginSuccessful a
   gagné des champs non documentés. Trop peu → err_parser_unexpected_data ;
   trop → le reste de la ligne devient un faux tag
   (err_parser_missing_tag_handler). Les deux font échouer la transaction et
   le client relance Login. D'où le balayage des candidats (voir _variants).
   La réponse certaine s'obtient avec `sh diag.sh` (strings du binaire).

Enveloppe : CRLF, et pour /distrib/ (V2) préfixe fil `ack\\r\\n` avant l'HTTP
(cf. OnHTTPAck qui consomme strlen("ack\\r\\n")).

Le routage se fait sur la commande, jamais sur l'URL : `RTNet_GetGeoConfig`
ouvre sa transaction avec l'action "login", donc GetGeoServerConfig et Login
arrivent tous deux sur /rtserver/login et seul le corps les distingue.
"""

from __future__ import annotations

import base64
import datetime as dt
import os
import socket
import ssl
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from map_auto import (
        schedule_build as _schedule_map_build,
        schedule_expand as _schedule_map_expand,
        coords_sane,
    )
except ImportError:
    def _schedule_map_build(lon: float, lat: float, *, force: bool = False) -> None:
        pass

    def _schedule_map_expand(lon: float, lat: float) -> None:
        pass

    def coords_sane(lon: float, lat: float) -> bool:
        return True

try:
    from tile_serve import (
        get_tile as _get_wzm_tile,
        note_served as _note_tile_served,
    )
except ImportError:
    def _get_wzm_tile(path: str, *, allow_stub: bool = True, wait_build_sec: float = 0.0):
        return None, ""

    def _note_tile_served(kind: str = "wzm") -> None:
        pass

CATCHER_REV = "proto150-route-20260826i"

os.environ.setdefault("CATCHER_CTYPE", "binary/octet-stream")
os.environ.setdefault("CATCHER_HTTP_VER", "1.1")
os.environ.setdefault("CATCHER_IDLE_SEC", "180")

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "logs" / "rts-catcher.txt"
TLS_DIR = ROOT / "mitm" / "certs" / "tls"
RES = ROOT / "mitm" / "fake-resources"
TILES = ROOT / "tiles"   # tuiles brutes, nommées par identifiant roadmap_tile
MAPS = ROOT / "maps"     # paquets hors-ligne <region>/map<fips>.wzm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from waze_env import apply_to_environ, base_url, server_ip  # noqa: E402

apply_to_environ()
PC_IP = server_ip()
BASE = base_url()
BIN_CT = "binary/octet-stream"

try:
    from waze_search import parse_search_form, search_body
except ImportError:
    def parse_search_form(body: bytes):
        return "", None, None

    def search_body(*_a, **_k) -> bytes:
        return b"RC,600,No matches\r\n"

try:
    from waze_alerts import (
        parse_report_alert,
        parse_rm_alert,
        live_alert_lines,
        poll_alert_lines,
        report_alert_response,
        rm_alert_response,
        total_points,
    )
except ImportError:
    def parse_report_alert(_body: bytes):
        return None

    def parse_rm_alert(_body: bytes):
        return None

    def live_alert_lines() -> list[str]:
        return []

    def poll_alert_lines() -> list[str]:
        return ["RC,200,OK"]

    def report_alert_response(_parsed: dict, lang: str = "fra") -> list[str]:
        return ["RC,200,OK"]

    def rm_alert_response(_aid: int) -> list[str]:
        return ["RC,200,OK"]

    def total_points() -> int:
        return 0

try:
    from waze_users import note_presence, user_poll_lines
except ImportError:
    def note_presence(_peer: str, _body: bytes) -> None:
        pass

    def user_poll_lines(_peer: str = "") -> list[str]:
        return []

_ROUTE_IMPORT_ERR = ""
try:
    from waze_route import (
        dest_label_from_request,
        parse_routing_request,
        routing_body,
        wzm_status_line,
    )
except Exception as e:
    _ROUTE_IMPORT_ERR = f"{type(e).__name__}: {e}"

    def parse_routing_request(body: bytes):
        return None

    def dest_label_from_request(_body: bytes) -> str:
        return ""

    def routing_body(*_a, **_k) -> bytes:
        return b"RC,500,Service unavailable\r\n"

    def wzm_status_line(*_a, **_k) -> str:
        return "  wzm (waze_route import FAIL)"

REGISTER_OK = "RegisterSuccessful,ios6user,ios6pass"

# Le client est en protocole 202 ; la seule source GPL publique est en 150.
# OnLoginResponse lit un nombre FIXE de champs : trop peu → err_parser_unexpected_data,
# trop → le reste de la ligne devient un faux tag (err_parser_missing_tag_handler).
# Dans les deux cas la transaction échoue et le client relance Login.
# On ne peut pas deviner ce nombre pour la 202 → on le cherche automatiquement.
VARIANT_FILE = ROOT / "logs" / "login-variant.txt"

# Commandes qui ne partent QUE si bLoggedIn == TRUE → preuve de login accepté.
PROOF_CMDS = {
    "at",
    "seeme",
    "gpspath",
    "nodepath",
    "createnewroads",
    "reportalert",
    "setmood",
    "getuserinfo",
    "requestroute",
}


def _log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        # Console en latin-1/ascii (sudo sans locale UTF-8) : ne jamais tuer le thread.
        enc = sys.stdout.encoding or "ascii"
        print(line.encode(enc, "replace").decode(enc, "replace"), flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _lines(rows: list[str]) -> bytes:
    return ("\r\n".join(rows) + "\r\n").encode("ascii")


def _line_fields(req_body: bytes, prefix: bytes) -> list[str]:
    for line in req_body.replace(b"\r\n", b"\n").split(b"\n"):
        if line.lower().startswith(prefix):
            return line.decode("latin1", errors="replace").split(",")
    return []


def _parse_routing_fallback(req_body: bytes):
    """Parse RoutingRequest même si waze_route n'est pas importé."""
    f = _line_fields(req_body, b"routingrequest,")
    if len(f) < 16:
        return None
    try:
        return (
            int(f[1]),
            int(f[7]) / 1e6,
            int(f[8]) / 1e6,
            int(f[14]) / 1e6,
            int(f[15]) / 1e6,
        )
    except (ValueError, IndexError):
        return None


def _coords_from_body(req_body: bytes) -> tuple[float, float] | None:
    """GPS réel uniquement — jamais le centre de MapDisplayed.

    Au dézoom / pan, MapDisplayed envoie le centre de *vue* (souvent hors
    carte locale) ; régénérer dessus écrasait maps/auto/ autour de chez toi.
    Sources : At / Location / GetGeoServerConfig (lon,lat en degrés).
    """
    for prefix, lon_i, lat_i in (
        (b"at,", 1, 2),
        (b"location,", 1, 2),
        (b"getgeoserverconfig,", 2, 3),
    ):
        f = _line_fields(req_body, prefix)
        need = max(lon_i, lat_i) + 1
        if len(f) < need:
            continue
        try:
            lon, lat = float(f[lon_i]), float(f[lat_i])
        except ValueError:
            continue
        if -180 <= lon <= 180 and -90 <= lat <= 90:
            return lon, lat
    return None


def _maybe_build_map(req_body: bytes) -> None:
    # MapDisplayed-only : log des tuiles, pas de rebuild (voir _note_map_displayed).
    cmds = {c.lower() for c in _cmds(req_body)}
    if cmds <= {"uid", "mapdisplayed", "stats", "gpsdisconnect"}:
        return
    if not (cmds & {"at", "location", "getgeoserverconfig", "getgeoconfig"}):
        return
    pair = _coords_from_body(req_body)
    if not pair:
        return
    lon, lat = pair
    if not coords_sane(lon, lat):
        _log(f"  GPS ignoré (fix invalide {lon:.6f},{lat:.6f})")
        return
    # Carte OSM en fond : seulement si GPS réel et déplacement suffisant.
    # Un 504 Overpass n'annule plus le détail déjà reçu.
    _log(f"  GPS {lon:.6f},{lat:.6f} — carte OSM auto si besoin")
    _schedule_map_build(lon, lat)


def _client_proto(req_body: bytes) -> tuple[int, bool]:
    """(numéro de protocole, legacy).

    legacy=True → le protocole est le 1er champ de Login (format GPL 150,
    RTNET_FORMAT_NETPACKET_9Login "Login,%d,%s,%s,..."). Sinon il est porté par
    ClientInfo (Waze 3.x) et la réponse LoginSuccessful n'est pas documentée.
    """
    ci = _line_fields(req_body, b"clientinfo,")
    if len(ci) > 1 and ci[1].isdigit():
        return int(ci[1]), False
    lg = _line_fields(req_body, b"login,")
    if len(lg) > 1 and lg[1].isdigit():
        return int(lg[1]), True
    return 0, False


def _req_user(req_body: bytes) -> str:
    lg = _line_fields(req_body, b"login,")
    if not lg:
        return "ios6user"
    # Legacy: Login,<proto>,<user>,<pw>…  |  3.x: Login,<user>,<pw>,…
    idx = 2 if (len(lg) > 1 and lg[1].isdigit()) else 1
    if len(lg) > idx and lg[idx]:
        return lg[idx]
    return "ios6user"


# ── Protocole 150 : réponse exacte, lue dans la source GPL ────────────────────
# mkoloberdin/waze @ iphone — Realtime/RealtimeNetRec.c, OnLoginResponse().
# Onze champs, dans cet ordre, terminés par la version serveur
# (ExtractNetworkString, MAX_SERVER_VERSION = 15 caractères max).
# RT_INVALID_LOGINID_VALUE vaut -1 : n'importe quel autre id est accepté.
GPL_SERVER_VERSION = "2.4.0.0"


def _body_login_gpl(user: str, proto: int) -> tuple[str, bytes]:
    rows = [
        "LoginSuccessful,"
        + ",".join(
            [
                "1",                    # iServerID     (≠ -1)
                f"waze{user}cookie01",  # ServerCookie  (63 max)
                "1",                    # iMyRanking
                str(total_points()),    # iMyTotalPoints
                "1",                    # iMyRating
                "1",                    # iMyPreviousRanking
                "0",                    # iMyAddon
                "0",                    # iPointsTimeStamp
                "0",                    # iExclusiveMoods
                str(proto),             # iServerMaxProtocol
                GPL_SERVER_VERSION,     # serverVersion
            ]
        )
    ]
    _log(f"  protocole {proto} (GPL) — format LoginSuccessful connu, 11 champs")
    for r in rows:
        _log(f"    {r}")
    return "gpl150", _lines(["RC,200,OK", *rows])


def _variants(user: str, proto: int = 202) -> list[tuple[str, list[str]]]:
    """Formats candidats pour LoginSuccessful, du plus probable au plus exotique."""
    cookie = f"waze{user}cookie01"
    # id, cookie, rank, points, rating, prevRank, addon, pointsTs, moods, maxProto
    head = f"1,{cookie},1,{total_points()},1,1,0,0,0,{proto}"
    ver = "3.9.6.1"
    out: list[tuple[str, list[str]]] = []

    out.append(("gpl11-seul", [f"LoginSuccessful,{head},{ver}"]))
    out.append(("gpl11+inbox", [f"LoginSuccessful,{head},{ver}", "UpdateInboxCount,0"]))

    # Champs entiers ajoutés APRÈS la version (protocole plus récent).
    for n in range(1, 7):
        tail = "," + ",".join(["0"] * n)
        out.append((f"ver+{n}int", [f"LoginSuccessful,{head},{ver}{tail}"]))

    # Champs entiers ajoutés AVANT la version.
    for n in range(1, 5):
        mid = "," + ",".join(["0"] * n)
        out.append((f"{n}int+ver", [f"LoginSuccessful,{head}{mid},{ver}"]))

    # Variantes « IPA » historiques (id utilisateur / nickname après la version).
    out.append(
        ("ipa17", [f"LoginSuccessful,{head},{ver},1,{user},0,1360000000,0,{user}"])
    )
    out.append(
        (
            "ipa17+pad",
            [f"LoginSuccessful,{head},{ver},1,{user},0,1360000000,0,{user},0,0,0,0,0,F,F"],
        )
    )
    out.append(("ver+user", [f"LoginSuccessful,{head},{ver},{user}"]))
    out.append(("ver+8int", [f"LoginSuccessful,{head},{ver}," + ",".join(["0"] * 8)]))
    return out


_LOGIN = {
    "idx": 0,
    "last_advance": 0.0,
    "locked": False,
    "count": 0,
}


def _load_locked_variant() -> None:
    forced = os.environ.get("LOGIN_VARIANT", "").strip()
    if not forced and VARIANT_FILE.is_file():
        forced = VARIANT_FILE.read_text(encoding="utf-8").strip()
        if forced:
            _LOGIN["locked"] = True
    if not forced:
        return
    names = [n for n, _ in _variants("ios6user")]
    if forced.isdigit():
        _LOGIN["idx"] = int(forced) % len(names)
    elif forced in names:
        _LOGIN["idx"] = names.index(forced)
    if os.environ.get("LOGIN_VARIANT", "").strip():
        _LOGIN["locked"] = True
    _log(f"  variante login figée: {names[_LOGIN['idx']]}")


def _body_login(req_body: bytes) -> tuple[str, bytes]:
    user = _req_user(req_body)
    proto, legacy = _client_proto(req_body)

    # Protocole 150 : la source est publique, aucune raison de tâtonner.
    if legacy:
        return _body_login_gpl(user, proto)

    variants = _variants(user, proto or 202)
    now = time.time()

    # Nouveau Login = la variante précédente a échoué → on passe à la suivante.
    if (
        not _LOGIN["locked"]
        and _LOGIN["count"] > 0
        and now - float(_LOGIN["last_advance"]) > 6.0
    ):
        _LOGIN["idx"] = (int(_LOGIN["idx"]) + 1) % len(variants)
        _LOGIN["last_advance"] = now
    elif _LOGIN["count"] == 0:
        _LOGIN["last_advance"] = now

    _LOGIN["count"] = int(_LOGIN["count"]) + 1
    idx = int(_LOGIN["idx"])
    name, rows = variants[idx]
    state = "FIGÉE" if _LOGIN["locked"] else f"essai {idx + 1}/{len(variants)}"
    _log(f"  variante login [{state}] {name}")
    for r in rows:
        _log(f"    {r}")
    return name, _lines(["RC,200,OK", *rows])


def _note_login_proof(cmds: list[str], user_hint: str = "ios6user") -> None:
    if _LOGIN["locked"]:
        return
    hit = [c for c in cmds if c.lower() in PROOF_CMDS]
    if not hit:
        return
    name = _variants(user_hint)[int(_LOGIN["idx"])][0]
    _LOGIN["locked"] = True
    try:
        VARIANT_FILE.parent.mkdir(parents=True, exist_ok=True)
        VARIANT_FILE.write_text(name, encoding="utf-8")
    except Exception:
        pass
    _log("=" * 62)
    _log(f"  ★★★ LOGIN ACCEPTÉ — variante « {name} » (commande {hit[0]})")
    _log(f"  Variante mémorisée dans {VARIANT_FILE}")
    _log("=" * 62)


# Waze identifie sa carte mondiale par le numéro 77001 (editor_main.c,
# editor_sync.c, roadmap_screen.c). En forçant Map.Static County on évite tout
# l'annuaire des comtés américains : le client ouvre directement notre carte.
WORLD_FIPS = 77001


def _server_params() -> list[tuple[str, str, str]]:
    return [
        ("Download", "Config", f"{BASE}/resources/config/"),
        ("Download", "Langs", f"{BASE}/resources/langs/"),
        ("Download", "Images", f"{BASE}/resources/images/"),
        ("Download", "Sound", f"{BASE}/resources/sounds/"),
        ("Download", "Sound_Ver", "1.3"),
        ("Download", "Config_Ver", "1.4"),
        ("Download", "Langs_Ver", "1.3"),
        # Tuiles HTTP : le client complète la carte au pan/dézoom sans SSH.
        ("Download", "Tiles", f"{BASE}/tiles"),
        # TTS WAS bloque le login (« Preparing navigation voice »). MP3 Minimal à la place.
        ("TTS", "Feature Enabled", "no"),
        ("Navigation", "Navigation guidance on", "yes"),
        ("Navigation", "Navigation guidance enabled", "yes"),
        ("Navigation", "Guidance type default", "Minimal"),
        ("Navigation", "Navigation guidance type", "Minimal"),
        ("Prompts", "Name", "fra"),
        ("Prompts", "Updated new", "no"),
        ("System", "Language", "fra"),
        ("System", "Default Language", "fra"),
        # Look Waze 2.4 (capture Fontainebleau) : fond gris-bleu, rues grises
        # fines, axes beige — pas le bleu/blanc OSM. Catégories du schema GPL.
        ("Map", "Background", "#C5D0D4"),
        ("Streets", "Thickness", "1"),
        ("Streets", "Color", "#9A9A9A"),
        ("Streets", "Delta1", "1"),
        ("Streets", "Color1", "#E6E6E6"),
        ("Streets", "LabelColor", "#222222"),
        ("Secondary", "Thickness", "2"),
        ("Secondary", "Color", "#C4A86A"),
        ("Secondary", "Delta1", "2"),
        ("Secondary", "Color1", "#E6D09A"),
        ("Primary", "Thickness", "3"),
        ("Primary", "Color", "#C4A050"),
        ("Primary", "Delta1", "2"),
        ("Primary", "Color1", "#E8C86A"),
        ("Highways", "Thickness", "3"),
        ("Highways", "Color", "#C4A050"),
        ("Highways", "Delta1", "2"),
        ("Highways", "Color1", "#E8C86A"),
        ("Freeways", "Thickness", "3"),
        ("Freeways", "Color", "#C4A050"),
        ("Freeways", "Delta1", "2"),
        ("Freeways", "Color1", "#E8C86A"),
        ("Ramps", "Thickness", "1"),
        ("Ramps", "Color", "#B0B0B0"),
        ("Ramps", "Delta1", "1"),
        ("Ramps", "Color1", "#E6E6E6"),
        ("Exit", "Thickness", "2"),
        ("Exit", "Color", "#C4A86A"),
        ("Exit", "Delta1", "1"),
        ("Exit", "Color1", "#E6D09A"),
        ("Download", "Source", f"{BASE}/maps"),
        ("Download", "Map name", "auto"),
        ("Download", "Enabled", "yes"),
        ("Map", "Static County", str(WORLD_FIPS)),
        # Recherche d'adresses (single_search / address_search → /rtserver/mozi*).
        ("Single Search", "Web-Service Address", f"{BASE}/rtserver"),
        ("Address Search", "Web-Service Address", f"{BASE}/rtserver"),
        ("Local Search", "Web-Service Address", f"{BASE}/rtserver"),
        # RoutingRequest en V2 → réponse préfixée ack\r\n (voir _ack_for).
        ("Realtime", "Web-Service V2 Commands", "RoutingRequest"),
        ("Realtime", "Web-Service V2 Suffix", ""),
        ("Scoreboard", "Feature enabled", "no"),
        ("User", "Show points ticker", "yes"),
        # Le ticker iPhone ne s'initialise que si Gray scale = yes
        # (roadmap_ticker.m → editor_screen_gray_scale()).
        ("Editor", "Gray scale", "yes"),
    ]


def _body_geo() -> bytes:
    """Réponse à GetGeoServerConfig.

    `on_geo_server_config` lit <id>,<name>,<lang>,<nb_paramètres>,<version> puis
    `on_server_config` compte les lignes reçues et n'appelle
    `on_recieved_completed()` que lorsque le compte annoncé est atteint. Le
    nombre doit donc coller exactement — d'où le calcul plutôt qu'un littéral.
    """
    rows = [
        f"ServerConfig,{i},{cat},{key},{val}"
        for i, (cat, key, val) in enumerate(_server_params())
    ]
    return _lines(
        ["RC,200,OK", f"GeoServerConfig,1,world,fra,{len(rows)},1", *rows]
    )


BODY_GEO = _body_geo()
BODY_REGISTER = _lines(["RC,200,OK", REGISTER_OK])
BODY_RC = _lines(["RC,200,OK"])
# VerifyStatus: 600 → err_as_could_not_find_matches (« aucun résultat », pas un crash)
BODY_NO_MATCH = _lines(["RC,600,No matches"])
# 500 → err_failed : échec propre côté client au lieu d'un parseur qui déraille
BODY_UNAVAILABLE = _lines(["RC,500,Service unavailable"])

SEARCH_CMDS = {
    "addresssearch",
    "search",
    "foursquaresearch",
    "getpoibyaddress",
    "localsearch",
    "autocomplete",
    "getautocomplete",
}
ROUTE_CMDS = {"routingrequest", "requestroute", "navigate", "getroute"}


def _cmds(req_body: bytes) -> list[str]:
    out: list[str] = []
    for line in req_body.replace(b"\r\n", b"\n").split(b"\n"):
        if not line.strip():
            continue
        out.append(line.split(b",", 1)[0].decode("latin1", errors="replace"))
    return out


def _ack_for(path: str, *, req_body: bytes = b"") -> bytes:
    """Préfixe `ack\\r\\n` exigé par OnHTTPAck pour le protocole V2."""
    if "/distrib/" in path.lower():
        return b"ack\r\n"
    # Realtime.Web-Service V2 Commands: RoutingRequest
    if b"routingrequest," in req_body.lower():
        return b"ack\r\n"
    return b""


def _note_proto_b64(req_body: bytes) -> None:
    for line in req_body.replace(b"\r\n", b"\n").split(b"\n"):
        if not line.startswith(b"ProtoBase64,"):
            continue
        b64 = line.split(b",", 1)[1].strip()
        try:
            raw = base64.b64decode(b64)
            _log(f"  ProtoBase64 decoded {len(raw)}B hex={raw[:40].hex()}…")
        except Exception as e:
            _log(f"  ProtoBase64 decode fail: {e}")


# ── Tuiles : indices calculés comme roadmap_tile.c (source GPL) ──────────────
# Coordonnées en micro-degrés. tile_id = base[scale] + lon_idx*rows + lat_idx.
_SQUARE_SIZE = 10_000
_MAX_SQUARE_SIZE = 30_000_000
_SCALE_STEP = 4


def _tile_scales() -> list[tuple[int, int, int]]:
    """(taille de tuile, index de base, nombre de lignes) par niveau d'échelle."""
    out: list[tuple[int, int, int]] = []
    size, base = _SQUARE_SIZE, 0
    while size <= _MAX_SQUARE_SIZE:
        rows = 179_999_999 // size + 1
        cols = 359_999_999 // size + 1
        out.append((size, base, rows))
        base += rows * cols
        size *= _SCALE_STEP
    return out


_TILE_SCALES = _tile_scales()


def _tile_id(lon_deg: float, lat_deg: float, scale: int = 0) -> int:
    size, base, rows = _TILE_SCALES[scale]
    lon_idx = (int(lon_deg * 1_000_000) + 180_000_000) // size
    lat_idx = (int(lat_deg * 1_000_000) + 90_000_000) // size
    return base + lon_idx * rows + lat_idx


def _note_map_displayed(req_body: bytes) -> None:
    """Journalise les tuiles demandées — ne rebuild JAMAIS la carte."""
    f = _line_fields(req_body, b"mapdisplayed,")
    if len(f) < 11:
        return
    try:
        lon, lat = float(f[9]), float(f[10])
    except ValueError:
        return
    ids = ", ".join(f"s{s}={_tile_id(lon, lat, s)}" for s in range(len(_TILE_SCALES)))
    _log(f"  centre {lon:.6f},{lat:.6f} → tuiles attendues: {ids}")
    _schedule_map_expand(lon, lat)


def _bridge_to_res_lines(req_body: bytes) -> list[str]:
    """BridgeToRes pour chaque BridgeTo du batch (RealtimeNetDefs.h)."""
    out: list[str] = []
    for line in req_body.replace(b"\r\n", b"\n").split(b"\n"):
        if not line.lower().startswith(b"bridgeto,"):
            continue
        parts = line.decode("latin1", errors="replace").split(",")
        if len(parts) >= 2 and parts[1].strip():
            svc = parts[1].strip()
            out.append(f"BridgeToRes,{svc},200,0")
    return out


def _realtime_tail(req_body: bytes, extra: list[str]) -> list[str]:
    rows = ["RC,200,OK", *_bridge_to_res_lines(req_body), *extra]
    return rows


def _classify(req_body: bytes, path: str = "", peer: str = "") -> tuple[str, bytes, bool]:
    low = req_body.lower()
    pl = path.lower()
    cmds = _cmds(req_body)
    cset = {c.lower() for c in cmds}
    _log(f"  cmds: {cmds}")

    _note_login_proof(cmds)
    _note_map_displayed(req_body)
    _maybe_build_map(req_body)

    # On route sur la commande, jamais sur l'URL : RTNet_GetGeoConfig ouvre sa
    # transaction avec l'action "login" (RealtimeNet.c), donc GetGeoServerConfig
    # arrive lui aussi sur /rtserver/login. Répondre LoginSuccessful à cette
    # requête la fait échouer — geo_config_parser n'accepte que RC,
    # GeoServerConfig, ServerConfig et UpdateConfig, sans handler par défaut.
    if cset & {"getgeoserverconfig", "getgeoconfig"}:
        _log(f"  req ({len(req_body)}B): {req_body!r}")
        return "GetGeo→GeoServerConfig", BODY_GEO, False

    if cset & {"login", "guestlogin"}:
        _log(f"  req ({len(req_body)}B): {req_body!r}")
        _note_proto_b64(req_body)
        name, body = _body_login(req_body)
        return f"Login→{name}", body, False

    if "register" in cset:
        _log(f"  req ({len(req_body)}B): {req_body!r}")
        return "Register→Freemap_userpass", BODY_REGISTER, False

    # Recherche : POST form vers /mozi ou /mozi_combo (wst, pas le protocole RTS).
    if (
        "/mozi" in pl
        or cset & SEARCH_CMDS
        or "/search" in pl
        or (
            b"q=" in req_body[:200].lower()
            and b"mobile=true" in req_body.lower()
        )
    ):
        q, lon, lat = parse_search_form(req_body)
        _log(f"  recherche q={q!r} near={lon},{lat}")
        single = "mozi_combo" in pl or "single" in pl
        body = search_body(q, lon=lon, lat=lat, single_search=single or True)
        n = body.count(b"AddressCandidate")
        return f"Recherche→{n} candidat(s)", body, False

    if cset & ROUTE_CMDS:
        _log(f"  req ({len(req_body)}B): {req_body!r}")
        parsed = parse_routing_request(req_body)
        if not parsed:
            parsed = _parse_routing_fallback(req_body)
        if not parsed:
            f = _line_fields(req_body, b"routingrequest,")
            _log(f"  parse RoutingRequest FAIL champs={len(f)}")
            return "Itinéraire→RC500 indisponible", BODY_UNAVAILABLE, False
        rid, lon1, lat1, lon2, lat2 = parsed
        dest = dest_label_from_request(req_body)
        _log(
            f"  itinéraire #{rid} {lon1:.5f},{lat1:.5f} → {lon2:.5f},{lat2:.5f}"
            + (f" dest={dest!r}" if dest else "")
        )
        _schedule_map_expand(lon2, lat2)
        try:
            body = routing_body(rid, lon1, lat1, lon2, lat2, dest_name=dest)
        except Exception as e:
            _log(f"  routing_body FAIL: {type(e).__name__}: {e}")
            return "Itinéraire→RC500 exception", BODY_UNAVAILABLE, False
        nseg = 0
        nturn = 0
        named = 0
        for line in body.split(b"\n"):
            ll = line.lower()
            if ll.startswith(b"routingresponse,") and not ll.startswith(
                b"routingresponsecode"
            ):
                parts = line.split(b",")
                if len(parts) > 7:
                    try:
                        nseg = int(parts[7])
                    except ValueError:
                        pass
            if ll.startswith(b"routesegments,"):
                # instruction = 5e champ de chaque sextuplet ; 0 = CONTINUE
                parts = line.decode("latin1", errors="replace").split(",")
                try:
                    nattrs = int(parts[5])
                except (IndexError, ValueError):
                    continue
                nums = parts[6 : 6 + nattrs]
                names = parts[6 + nattrs :]
                named += sum(1 for n in names if n.strip())
                for j in range(4, len(nums), 6):
                    try:
                        if int(nums[j]) != 0:
                            nturn += 1
                    except ValueError:
                        pass
        _log(
            f"  → {nseg} seg carte locale, {nturn} manœuvre(s), {named} nom(s)"
            + (f" dest={dest!r}" if dest else "")
        )
        return "Itinéraire→OSRM+wzm", body, False

    if "reportalert" in cset:
        parsed = parse_report_alert(req_body)
        if not parsed:
            _log("  ReportAlert parse FAIL")
            return "Report→RC200", BODY_RC, False
        rows = report_alert_response(parsed)
        bridge = _bridge_to_res_lines(req_body)
        if bridge:
            rows = ["RC,200,OK", *bridge, *rows[1:]]
        _log(f"  report type={parsed['type']} id={rows[-1].split(',')[1] if rows else '?'}")
        return "Report→AddAlert", _lines(rows), False

    if "reportrmalert" in cset:
        aid = parse_rm_alert(req_body)
        if aid is None:
            return "RmAlert→RC200", BODY_RC, False
        return "RmAlert", _lines(rm_alert_response(aid)), False

    if cset & {"at", "seeme"}:
        note_presence(peer, req_body)
        extra = live_alert_lines() + user_poll_lines(peer)
        if extra:
            n_al = sum(1 for r in extra if r.startswith("AddAlert"))
            n_u = sum(1 for r in extra if r.startswith("AddUser"))
            _log(f"  → {n_al} alerte(s), {n_u} wazer(s)")
            return "Realtime→live", _lines(_realtime_tail(req_body, extra)), False

    bridge = _bridge_to_res_lines(req_body)
    if bridge:
        return "Realtime→BridgeTo", _lines(_realtime_tail(req_body, [])), False

    return "Realtime→RC200", BODY_RC, False


def _http_envelope(
    body: bytes,
    *,
    ack: bytes,
    close: bool,
    ctype: str | None = None,
    status: str = "200 OK",
) -> bytes:
    ver = os.environ.get("CATCHER_HTTP_VER", "1.1")
    ct = ctype or os.environ.get("CATCHER_CTYPE", BIN_CT)
    conn = b"Connection: close\r\n" if close else b"Connection: keep-alive\r\n"
    hdr = (
        f"HTTP/{ver} {status}\r\n".encode()
        + f"Content-Type: {ct}\r\n".encode()
        + f"Content-Length: {len(body)}\r\n".encode()
        + conn
        + b"\r\n"
    )
    return ack + hdr + body


def _read_request(conn: socket.socket, idle: float) -> bytes | None:
    data = b""
    conn.settimeout(idle)
    try:
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                return None if not data else data
            data += chunk
            if b"\r\n\r\n" in data:
                head, _, rest = data.partition(b"\r\n\r\n")
                cl = 0
                for line in head.lower().split(b"\r\n"):
                    if line.startswith(b"content-length:"):
                        try:
                            cl = int(line.split(b":", 1)[1].strip())
                        except ValueError:
                            cl = 0
                while len(rest) < cl:
                    conn.settimeout(30.0)
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    rest += chunk
                return head + b"\r\n\r\n" + rest
    except socket.timeout:
        return b"" if not data else data


_PNG1 = bytes(
    [
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D,
        0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
        0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53, 0xDE, 0x00, 0x00, 0x00,
        0x0C, 0x49, 0x44, 0x41, 0x54, 0x08, 0xD7, 0x63, 0xF8, 0xCF, 0xC0, 0x00,
        0x00, 0x00, 0x03, 0x00, 0x01, 0x00, 0x05, 0xFE, 0x02, 0xFE, 0x00, 0x00,
        0x00, 0x00, 0x49, 0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82,
    ]
)


def _resolve_resource(path: str) -> Path | None:
    """Map S3 / resources / config / lang paths to fake-resources/."""
    p = unquote(urlparse(path).path)
    rel = p.lstrip("/")
    if rel.startswith("resources/"):
        rel = rel[len("resources/") :]
    name = Path(p).name
    parts = Path(rel).parts
    candidates: list[Path] = [
        RES / rel,
        RES / p.lstrip("/"),
        RES / "langs" / name,
        RES / "config" / name,
    ]
    if name == "lang.conf":
        candidates.extend(
            [
                RES / "config" / "lang.conf",
                RES / "config" / "1" / "lang.conf",
                RES / "resources" / "config" / "1" / "lang.conf",
            ]
        )
    if name.startswith("lang."):
        candidates.extend([RES / "langs" / name, RES / "resources" / "langs" / name])
    if "sounds" in parts or (len(parts) >= 1 and "sound" in "/".join(parts).lower()):
        stem = Path(name).stem if name else ""
        lang = "eng"
        for p in parts:
            if p in ("eng", "fra", "heb"):
                lang = p
        langs = [lang]
        if lang == "eng":
            langs.append("fra")
        elif lang == "fra":
            langs.append("eng")
        for lang in langs:
            for folder in (
                RES / "resources" / "sounds" / "1.0" / lang,
                RES / "sounds" / "1.0" / lang,
                RES / "sounds" / lang,
            ):
                if stem:
                    candidates.append(folder / stem)
                    candidates.append(folder / f"{stem}.mp3")
                candidates.append(folder / name)
    if name == "prompts.conf":
        candidates.extend(
            [
                RES / "resources" / "config" / "1.0" / "1" / "prompts.conf",
                RES / "config" / "1.0" / "1" / "prompts.conf",
            ]
        )
    if len(parts) >= 2 and parts[0] == "config":
        candidates.append(RES / "config" / parts[-1])
        if len(parts) >= 3:
            candidates.append(RES / "config" / parts[1] / parts[-1])
    if len(parts) >= 2 and parts[0] == "langs":
        candidates.append(RES / "langs" / parts[-1])
    for c in candidates:
        if c.is_file():
            return c
    return None


def _guess_ct(path: str, data: bytes) -> str:
    low = path.lower()
    if low.endswith(".png"):
        return "image/png"
    if low.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if low.endswith(".gif"):
        return "image/gif"
    if low.endswith((".html", ".htm")):
        return "text/html; charset=utf-8"
    if low.endswith((".conf", ".txt", ".lang")) or b"lang." in path.encode():
        return "text/plain; charset=utf-8"
    if "sounds" in low or low.endswith(".mp3"):
        return "audio/mpeg"
    if data[:4] == b"\x89PNG":
        return "image/png"
    return "application/octet-stream"


def _scoreboard_query(raw_path: str) -> dict[str, str]:
    q = parse_qs(urlparse(raw_path).query)
    def one(key: str, default: str = "") -> str:
        v = q.get(key) or []
        return (v[0] if v else default).strip()
    period = one("period", "weekly").lower()
    if period not in ("weekly", "all"):
        period = "weekly"
    geography = one("geography", "country").lower()
    lang = one("lang", "fra").lower()
    if lang.startswith("en"):
        lang = "eng"
    try:
        width = max(240, min(480, int(one("width", "320") or "320")))
    except ValueError:
        width = 320
    try:
        height = max(300, min(600, int(one("height", "400") or "400")))
    except ValueError:
        height = 400
    return {
        "period": period,
        "geography": geography,
        "lang": lang,
        "width": str(width),
        "height": str(height),
    }


def _is_scoreboard_get(path: str, head: bytes) -> bool:
    p = path.lower().split("?", 1)[0].rstrip("/") or "/"
    if p in ("/scoreboard", "/was/mvc/scoreboard") or p.startswith("/was/"):
        return True
    host = ""
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"host:"):
            host = line.split(b":", 1)[1].decode("latin1", "replace").strip().lower()
            break
    if "waze.com" in host and not host.startswith("rt."):
        if p in ("/", "") or "scoreboard" in p:
            return True
    return False


def _handle_conn(conn: socket.socket, scheme: str) -> None:
    peer = "?"
    idle = float(os.environ.get("CATCHER_IDLE_SEC", "180"))
    try:
        try:
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass
        peer = conn.getpeername()[0]
        while True:
            raw = _read_request(conn, idle)
            if raw is None:
                return
            if raw == b"":
                continue

            head, _, req_body = raw.partition(b"\r\n\r\n")
            first = head.split(b"\r\n", 1)[0].decode("latin1", errors="replace")
            _log(f"{peer} {scheme.upper()} {first}")
            path = "/"
            raw_path = "/"
            parts = first.split(" ")
            if len(parts) >= 2:
                raw_path = parts[1]
                path = raw_path.split("?", 1)[0]

            is_rts = "POST" in first and (
                "/rtserver" in path
                or "/distrib/" in path
                or "/mozi" in path.lower()
                or b"clientinfo" in req_body.lower()
                or b"register" in req_body.lower()
                or b"login" in req_body.lower()
                or b"stats," in req_body.lower()
                or b"routingrequest," in req_body.lower()
                or b"q=" in req_body[:120].lower()
            )
            if is_rts:
                label, body, close = _classify(req_body, path=path, peer=peer)
                ack = _ack_for(path, req_body=req_body)
                resp = _http_envelope(body, ack=ack, close=close)
                conn.sendall(resp)
                _log(f"  → {label} ack={ack!r} close={close} wire={len(resp)}B")
                if "Login→" in label and "gpl150" not in label and not _LOGIN["locked"]:
                    _log("  (si un nouveau Login arrive → variante refusée, on essaie la suivante)")
                if close:
                    try:
                        conn.shutdown(socket.SHUT_WR)
                    except Exception:
                        pass
                    time.sleep(0.2)
                    return
                continue

            if "GET" in first:
                # Repo Cydia servie par le catcher (évite raw.githubusercontent 307).
                pl = path.lower().split("?", 1)[0]
                if pl == "/cydia" or pl == "/cydia/":
                    body = (
                        b"<html><body><h1>waze-ios6 Cydia</h1>"
                        b"<p>Add this URL as Cydia source:</p>"
                        b"<code>"
                        + BASE.encode("ascii", errors="replace")
                        + b"/cydia</code></body></html>"
                    )
                    conn.sendall(
                        _http_envelope(
                            body, ack=b"", close=False, ctype="text/html; charset=utf-8"
                        )
                    )
                    _log("  ★ cydia index")
                    continue
                if pl.startswith("/cydia/"):
                    rel = unquote(urlparse(path).path)[len("/cydia/") :]
                    # Empêche .. hors de cydia/
                    cand = (ROOT / "cydia" / rel).resolve()
                    root_c = (ROOT / "cydia").resolve()
                    if str(cand).startswith(str(root_c)) and cand.is_file():
                        payload = cand.read_bytes()
                        ct = _guess_ct(str(cand), payload)
                        if cand.suffix == ".deb":
                            ct = "application/vnd.debian.binary-package"
                        elif cand.name == "Packages":
                            ct = "text/plain; charset=utf-8"
                        elif cand.name.endswith(".bz2"):
                            ct = "application/x-bzip2"
                        _log(f"  ★ cydia {rel} ({len(payload)}B)")
                        conn.sendall(
                            _http_envelope(payload, ack=b"", close=False, ctype=ct)
                        )
                    else:
                        _log(f"  · cydia 404 {rel}")
                        conn.sendall(
                            _http_envelope(
                                b"Not Found\n",
                                ack=b"",
                                close=False,
                                ctype="text/plain",
                                status="404 Not Found",
                            )
                        )
                    continue
                if _is_scoreboard_get(path, head):
                    _log(f"  · classement désactivé {path}")
                    conn.sendall(
                        _http_envelope(
                            b"",
                            ack=b"",
                            close=False,
                            ctype="text/plain",
                            status="404 Not Found",
                        )
                    )
                    continue
                is_tile = "/tiles" in path.lower()
                if is_tile:
                    # Jamais de stub vide : l'iPhone les met en cache et l'écran
                    # reste blanc / flood de re-téléchargements hors zone.
                    blob, kind = _get_wzm_tile(
                        path, allow_stub=False, wait_build_sec=90.0
                    )
                    if blob:
                        _note_tile_served(kind)
                        _log(
                            f"  ★ tuile {kind}: {Path(path).name} ({len(blob)}B)"
                        )
                        conn.sendall(
                            _http_envelope(
                                blob, ack=b"", close=False, ctype=BIN_CT
                            )
                        )
                    else:
                        _log(
                            f"  · tuile absente (pas de stub): {Path(path).name}"
                        )
                        conn.sendall(
                            _http_envelope(
                                b"",
                                ack=b"",
                                close=False,
                                ctype="text/plain",
                                status="404 Not Found",
                            )
                        )
                    continue
                if "/maps/" in path.lower():
                    _log(f"  ★★★ PAQUET DE CARTE demandé: {path}")
                else:
                    _log(f"  ★ GET {path}")
                res = _resolve_resource(path)
                payload = res.read_bytes() if res else b""
                if not payload:
                    name = Path(path).name
                    rel = unquote(urlparse(path).path).lstrip("/")
                    for c in (
                        RES / path.lstrip("/"),
                        TILES / name,
                        MAPS / rel[len("maps/") :] if rel.startswith("maps/") else MAPS / rel,
                        RES / "tiles" / name,
                        RES / "resources" / "images" / "1.0" / "2x" / name,
                    ):
                        if c.is_file():
                            payload = c.read_bytes()
                            break
                if not payload and path.lower().endswith(
                    (".png", ".jpg", ".jpeg", ".gif")
                ):
                    payload = _PNG1
                ct = _guess_ct(path, payload)
                conn.sendall(_http_envelope(payload, ack=b"", close=False, ctype=ct))
                continue

            conn.sendall(_http_envelope(BODY_RC, ack=_ack_for(path), close=False))
    except Exception as e:
        _log(f"{peer} error: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _bind_listen(port: int) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", port))
    except OSError as e:
        raise SystemExit(f"bind :{port} failed: {e}  → sudo ss -ltnp sport = :{port}") from e
    s.listen(64)
    return s


def _serve_plain(sock: socket.socket, port: int) -> None:
    _log(f"HTTP  :{port}")
    while True:
        c, _ = sock.accept()
        threading.Thread(target=_handle_conn, args=(c, "http"), daemon=True).start()


def _serve_tls(sock: socket.socket, port: int) -> None:
    cert, key = TLS_DIR / "leaf-chain.crt", TLS_DIR / "leaf.key"
    if not cert.exists() or not key.exists():
        raise SystemExit(f"missing certs {TLS_DIR}")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    except ssl.SSLError:
        pass
    ctx.load_cert_chain(str(cert), str(key))
    _log(f"CATCHER_REV={CATCHER_REV} HTTPS :{port}")
    while True:
        c, _ = sock.accept()
        try:
            ss = ctx.wrap_socket(c, server_side=True)
        except Exception as e:
            _log(f"TLS accept: {e}")
            try:
                c.close()
            except Exception:
                pass
            continue
        threading.Thread(target=_handle_conn, args=(ss, "https"), daemon=True).start()


def main() -> None:
    http_port = int(os.environ.get("CATCHER_HTTP_PORT", "80"))
    https_port = int(os.environ.get("CATCHER_HTTPS_PORT", "443"))
    _log(f"CATCHER_REV={CATCHER_REV} → {PC_IP}")
    if _ROUTE_IMPORT_ERR:
        _log(f"  waze_route import FAIL: {_ROUTE_IMPORT_ERR}")
    _load_locked_variant()
    _log("Protocole 150 (Waze 2.4.0.0) : réponse exacte issue de la source GPL.")
    _log(
        f"Protocole 202 (Waze 3.9.6) : balayage de {len(_variants('ios6user'))} "
        "formats LoginSuccessful ; chaque relance de Login = format refusé."
    )
    _log("Succès = ★★★ LOGIN ACCEPTÉ (le client envoie At/SeeMe).")
    _log("Remise à zéro du balayage: rm logs/login-variant.txt")
    _log(f"Carte annoncée: Map.Static County={WORLD_FIPS}.")
    _log("  Carte = maps/auto. Expansion Overpass si dest/pan hors bbox (fusion, pas d'écrasement).")
    _log("  Nav = segments wzm (zoom rue) + RoutePoints OSRM (dézoom). Tuiles HTTP + stub.")
    _log(wzm_status_line())

    http_sock = _bind_listen(http_port)
    https_sock = _bind_listen(https_port)

    threading.Thread(target=_serve_plain, args=(http_sock, http_port), daemon=True).start()
    threading.Thread(target=_serve_tls, args=(https_sock, https_port), daemon=True).start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
