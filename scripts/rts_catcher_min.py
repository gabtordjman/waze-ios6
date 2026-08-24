#!/usr/bin/env python3
"""CATCHER_REV=login-gpl11-min-20260824b

Freemap login_parser (RealtimeNetRec.c):
  - OnLoginResponse: exactly 11 CSV fields after tag, then bLoggedIn=TRUE
  - Extra CSV on same line poisons the parser → login retry
  - Separate tagged lines OK: UpdateInboxCount (ServerConfig removed from login —
    phone prefs already have Download.* URLs; ServerConfig during login can confuse
    geo_config context)

Response uses CRLF. V2 /distrib/ → wire prefix ack\\r\\n before HTTP.
"""

from __future__ import annotations

import base64
import datetime as dt
import os
import socket
import ssl
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

CATCHER_REV = "login-gpl11-min-20260824b"

os.environ.setdefault("CATCHER_CTYPE", "binary/octet-stream")
os.environ.setdefault("CATCHER_HTTP_VER", "1.1")
os.environ.setdefault("CATCHER_IDLE_SEC", "180")

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "logs" / "rts-catcher.txt"
TLS_DIR = ROOT / "mitm" / "certs" / "tls"
RES = ROOT / "mitm" / "fake-resources"

PC_IP = os.environ.get("PC_IP", "192.168.1.191").strip()
BASE = f"http://{PC_IP}"
BIN_CT = "binary/octet-stream"

# 11 fields after LoginSuccessful — stop at ver (no PAD tail on same line).
REGISTER_OK = "RegisterSuccessful,ios6user,ios6pass"


def _login_line(req_body: bytes) -> str:
    """Build LoginSuccessful; reuse ios6user from request when present."""
    user = "ios6user"
    for line in req_body.replace(b"\r\n", b"\n").split(b"\n"):
        if line.lower().startswith(b"login,"):
            parts = line.decode("latin1", errors="replace").split(",")
            if len(parts) > 1 and parts[1].strip():
                user = parts[1].strip()
            break
    cookie = f"waze{user}cookie01"
    return f"LoginSuccessful,1,{cookie},1,100,1,1,0,0,0,202,3.9.6.1"


def _log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _lines(rows: list[str]) -> bytes:
    return ("\r\n".join(rows) + "\r\n").encode("ascii")


def _server_configs() -> list[str]:
    return [
        f"ServerConfig,0,Download,Config,{BASE}/resources/config/",
        f"ServerConfig,1,Download,Langs,{BASE}/resources/langs/",
        f"ServerConfig,2,Download,Images,{BASE}/resources/images/",
        f"ServerConfig,3,Download,Sound,{BASE}/resources/sounds/",
        f"ServerConfig,4,Download,Langs TTS,{BASE}/resources/lang_tts/",
        f"ServerConfig,5,Download,Tiles,{BASE}/tiles/",
    ]


BODY_GEO5 = _lines(
    [
        "RC,200,OK",
        "GeoServerConfig,1,world,eng,5,1",
        *_server_configs(),
    ]
)
BODY_REGISTER = _lines(["RC,200,OK", REGISTER_OK])
BODY_RC = _lines(["RC,200,OK"])


def _body_login(req_body: bytes) -> bytes:
    return _lines(["RC,200,OK", _login_line(req_body), "UpdateInboxCount,0"])


def _cmds(req_body: bytes) -> list[str]:
    out: list[str] = []
    for line in req_body.replace(b"\r\n", b"\n").split(b"\n"):
        if not line.strip():
            continue
        out.append(line.split(b",", 1)[0].decode("latin1", errors="replace"))
    return out


def _ack_for(path: str) -> bytes:
    if "/distrib/" in path.lower():
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


def _classify(req_body: bytes, path: str = "") -> tuple[str, bytes, bool]:
    low = req_body.lower()
    pl = path.lower()
    cmds = _cmds(req_body)
    _log(f"  cmds: {cmds}")

    if (
        "/login" in pl
        or b"guestlogin" in low
        or b"\nlogin," in low
        or low.startswith(b"login,")
        or any(c.lower() in ("login", "guestlogin") for c in cmds)
    ):
        _log(f"  req ({len(req_body)}B): {req_body!r}")
        _note_proto_b64(req_body)
        body = _body_login(req_body)
        _log(f"  login line: {_login_line(req_body)}")
        return "Login→GPL11+Inbox+keepalive", body, False

    if b"register," in low:
        _log(f"  req ({len(req_body)}B): {req_body!r}")
        return "Register→Freemap_userpass", BODY_REGISTER, False

    if b"getgeoserverconfig" in low or b"getgeoconfig" in low:
        return "GetGeo→geo5", BODY_GEO5, False

    # Post-login batch (At, Stats, MapDisplayed, …) — RC,200,OK suffices
    if any(
        c.lower()
        in (
            "at",
            "stats",
            "mapdisplayed",
            "location",
            "keepalive",
            "routingrequest",
            "addresssearch",
            "foursquaresearch",
            "search",
        )
        for c in cmds
    ):
        return "Realtime batch→RC", BODY_RC, False

    return "RC only", BODY_RC, False


def _http_envelope(body: bytes, *, ack: bytes, close: bool, ctype: str | None = None) -> bytes:
    ver = os.environ.get("CATCHER_HTTP_VER", "1.1")
    ct = ctype or os.environ.get("CATCHER_CTYPE", BIN_CT)
    conn = b"Connection: close\r\n" if close else b"Connection: keep-alive\r\n"
    hdr = (
        f"HTTP/{ver} 200 OK\r\n".encode()
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
    if low.endswith((".conf", ".txt", ".lang")) or b"lang." in path.encode():
        return "text/plain; charset=utf-8"
    if data[:4] == b"\x89PNG":
        return "image/png"
    return "application/octet-stream"


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
            parts = first.split(" ")
            if len(parts) >= 2:
                path = parts[1].split("?", 1)[0]

            is_rts = "POST" in first and (
                "/rtserver" in path
                or "/distrib/" in path
                or b"clientinfo" in req_body.lower()
                or b"register" in req_body.lower()
                or b"login" in req_body.lower()
                or b"stats," in req_body.lower()
            )
            if is_rts:
                label, body, close = _classify(req_body, path=path)
                ack = _ack_for(path)
                resp = _http_envelope(body, ack=ack, close=close)
                conn.sendall(resp)
                _log(f"  → {label} ack={ack!r} close={close} wire={len(resp)}B")
                if "Login→" in label:
                    _log("  ★ Login. Succès = 1 seul Login, plus de Searching, ★ GET tiles.")
                if close:
                    try:
                        conn.shutdown(socket.SHUT_WR)
                    except Exception:
                        pass
                    time.sleep(0.2)
                    return
                continue

            if "GET" in first:
                _log(f"  ★ GET {path}")
                res = _resolve_resource(path)
                payload = res.read_bytes() if res else b""
                if not payload:
                    name = Path(path).name
                    for c in (
                        RES / path.lstrip("/"),
                        RES / "tiles" / name,
                        RES / "resources" / "images" / "1.0" / "2x" / name,
                    ):
                        if c.is_file():
                            payload = c.read_bytes()
                            break
                if not payload and (
                    path.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))
                    or "/tiles" in path.lower()
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
    _log("Login→GPL11 CRLF + UpdateInboxCount + keepalive (no ServerConfig on login).")

    http_sock = _bind_listen(http_port)
    https_sock = _bind_listen(https_port)

    threading.Thread(target=_serve_plain, args=(http_sock, http_port), daemon=True).start()
    threading.Thread(target=_serve_tls, args=(https_sock, https_port), daemon=True).start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
