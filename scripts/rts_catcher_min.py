#!/usr/bin/env python3
"""CATCHER_REV=realtime-login-20260816m

Breakthrough: System.ServerId: 1 skips GetGeo → license + empty map.
Next failure = Realtime GuestLogin/Login getting GeoServerConfig instead of
LoginSuccessful (login_parser). GuestLogin may also need V2 ack.

Routing:
  GetGeoServerConfig → RC + GeoServerConfig (+ ServerConfig)
  GuestLogin / Login / Register / ClientInfo (no GetGeo) → RC + LoginSuccessful
  anything else (At, KeepAlive, …) → RC,200,OK

Default: plain body + optional ack\\r\\n for login (CATCHER_LOGIN_ACK=1).
"""

from __future__ import annotations

import datetime as dt
import os
import socket
import ssl
import struct
import threading
import time
import zlib
from pathlib import Path

CATCHER_REV = "realtime-login-20260816m"

os.environ.setdefault("CATCHER_LOGIN_ACK", "1")
os.environ.setdefault("CATCHER_CTYPE", "binary/octet-stream")
os.environ.setdefault("CATCHER_HTTP_VER", "1.0")
os.environ.setdefault("CATCHER_DRAIN_SEC", "2.0")
os.environ.setdefault("CATCHER_NL", "lf")

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "logs" / "rts-catcher.txt"
TLS_DIR = ROOT / "mitm" / "certs" / "tls"
RES = ROOT / "mitm" / "fake-resources"

PC_IP = os.environ.get("PC_IP", "192.168.1.191").strip()
BASE = f"http://{PC_IP}"
NL = "\n" if os.environ.get("CATCHER_NL", "lf").lower() != "crlf" else "\r\n"
BIN_CT = "binary/octet-stream"

# Freemap OnLoginResponse fields (then IPA may ignore trailing extras)
LOGIN_OK = (
    "LoginSuccessful,1,cookie123456,1,100,1,1,0,0,0,202,3.9.6.1,"
    "1,guest,0,1360000000,0,guest"
)


def _log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _lines(*rows: str) -> bytes:
    return (NL.join(rows) + NL).encode("ascii")


BODY_GEO5 = _lines(
    "RC,200,OK",
    "GeoServerConfig,1,world,eng,5,1",
    f"ServerConfig,0,Download,Config,{BASE}/resources/config/",
    f"ServerConfig,1,Download,Langs,{BASE}/resources/langs/",
    f"ServerConfig,2,Download,Images,{BASE}/resources/images/",
    f"ServerConfig,3,Download,Sound,{BASE}/resources/sounds/",
    f"ServerConfig,4,Download,Langs TTS,{BASE}/resources/lang_tts/",
)
BODY_LOGIN = _lines("RC,200,OK", LOGIN_OK)
BODY_REGISTER = _lines("RC,200,OK", "RegisterSuccessful,4242,ios6regcookie")
BODY_RC = _lines("RC,200,OK")
BODY_LOGIN_GEO = _lines(
    "RC,200,OK",
    LOGIN_OK,
    "GeoServerConfig,1,world,eng,5,1",
    f"ServerConfig,0,Download,Config,{BASE}/resources/config/",
    f"ServerConfig,1,Download,Langs,{BASE}/resources/langs/",
    f"ServerConfig,2,Download,Images,{BASE}/resources/images/",
    f"ServerConfig,3,Download,Sound,{BASE}/resources/sounds/",
    f"ServerConfig,4,Download,Langs TTS,{BASE}/resources/lang_tts/",
)


def _classify(req_body: bytes) -> tuple[str, bytes, bool]:
    """Return (label, body, want_ack)."""
    low = req_body.lower()
    login_ack = os.environ.get("CATCHER_LOGIN_ACK", "1").strip() not in (
        "0",
        "false",
        "no",
        "off",
    )

    if b"getgeoserverconfig" in low or b"getgeoconfig" in low:
        # Still allow GetGeo if some phone has ServerId=-1
        if b"clientinfo," in low:
            return "ClientInfo+GetGeo → Login+Geo5", BODY_LOGIN_GEO, login_ack
        return "GetGeo → geo5", BODY_GEO5, False

    if b"guestlogin" in low or low.startswith(b"login,") or b"\nlogin," in low:
        return "GuestLogin/Login → LoginSuccessful", BODY_LOGIN, login_ack

    if b"register," in low:
        return "Register → RegisterSuccessful", BODY_REGISTER, login_ack

    if b"clientinfo," in low:
        # Post-ServerId skip: ClientInfo alone may still appear — treat as login
        return "ClientInfo → LoginSuccessful", BODY_LOGIN, login_ack

    return "other → RC only", BODY_RC, False


def _waze_gzip(data: bytes) -> bytes:
    comp = zlib.compressobj(6, zlib.DEFLATED, -15)
    body = comp.compress(data) + comp.flush()
    header = b"\x1f\x8b\x08\x00" + struct.pack("<I", 0) + b"\x00\xff"
    crc = zlib.crc32(data) & 0xFFFFFFFF
    trailer = struct.pack("<II", crc, len(data) % (2**32))
    return header + body + trailer


def _http_envelope(body: bytes, *, ack: bool, gzip: bool = False) -> bytes:
    ver = os.environ.get("CATCHER_HTTP_VER", "1.0")
    ctype = os.environ.get("CATCHER_CTYPE", BIN_CT)
    if gzip:
        payload = _waze_gzip(body)
        enc = b"Content-Encoding: gzip\r\n"
    else:
        payload = body
        enc = b""
    hdr = (
        f"HTTP/{ver} 200 OK\r\n".encode()
        + f"Content-Type: {ctype}\r\n".encode()
        + enc
        + f"Content-Length: {len(payload)}\r\n".encode()
        + b"Connection: close\r\n\r\n"
    )
    return (b"ack\r\n" if ack else b"") + hdr + payload


def _read_request(conn: socket.socket, limit: int = 65536) -> bytes:
    data = b""
    conn.settimeout(15.0)
    try:
        while len(data) < limit:
            chunk = conn.recv(4096)
            if not chunk:
                break
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
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    rest += chunk
                return head + b"\r\n\r\n" + rest
    except socket.timeout:
        pass
    return data


def _close_clean(conn: socket.socket) -> None:
    try:
        if not isinstance(conn, ssl.SSLSocket):
            conn.shutdown(socket.SHUT_WR)
    except Exception:
        pass
    time.sleep(float(os.environ.get("CATCHER_DRAIN_SEC", "2.0")))
    try:
        conn.close()
    except Exception:
        pass


def _res_candidates(path: str) -> list[Path]:
    name = Path(path).name
    rel = path.lstrip("/")
    out = [
        RES / rel,
        RES / "resources" / rel,
        RES / "resources" / "config" / "1.0" / "1" / name,
        RES / "resources" / "langs" / name,
        RES / "langs" / name,
        RES / "config" / name,
        RES / "newVconfig" / "1" / name,
    ]
    seen: set[str] = set()
    uniq: list[Path] = []
    for c in out:
        if str(c) not in seen:
            seen.add(str(c))
            uniq.append(c)
    return uniq


def _handle_one(conn: socket.socket, scheme: str) -> None:
    peer = "?"
    try:
        try:
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass
        if isinstance(conn, ssl.SSLSocket):
            try:
                _log(f"  TLS {conn.version()} {conn.cipher()}")
            except Exception:
                pass

        peer = conn.getpeername()[0]
        raw = _read_request(conn)
        if not raw:
            _log(f"{peer} empty")
            return

        head, _, req_body = raw.partition(b"\r\n\r\n")
        first = head.split(b"\r\n", 1)[0].decode("latin1", errors="replace")
        _log(f"{peer} {scheme.upper()} {first}")
        for line in head.split(b"\r\n")[1:]:
            low = line.lower()
            if any(
                low.startswith(x)
                for x in (b"host:", b"user-agent:", b"content-length:", b"accept-encoding:")
            ):
                _log(f"  hdr: {line.decode('latin1', errors='replace')}")

        path = "/"
        parts = first.split(" ")
        if len(parts) >= 2:
            path = parts[1].split("?", 1)[0]

        is_rts = "POST" in first and (
            "/rtserver" in path
            or b"clientinfo" in req_body.lower()
            or b"login" in req_body.lower()
            or b"getgeo" in req_body.lower()
        )
        if is_rts:
            _log(f"  req ({len(req_body)}B) {req_body!r}")
            label, body, ack = _classify(req_body)
            resp = _http_envelope(body, ack=ack, gzip=False)
            conn.sendall(resp)
            _log(f"  → {label} ack={ack} plain={len(body)}B wire={len(resp)}B")
            _log(f"  → body:\n{body.decode('ascii', errors='replace')}")
            return

        if "GET" in first:
            host = ""
            for line in head.split(b"\r\n"):
                if line.lower().startswith(b"host:"):
                    host = line.split(b":", 1)[1].strip().decode("latin1", errors="replace")
            _log(f"  ★ GET {host!r} {path!r}")
            for c in _res_candidates(path):
                if c.is_file():
                    data = c.read_bytes()
                    _log(f"RES → {c.relative_to(ROOT)} ({len(data)}B)")
                    conn.sendall(_http_envelope(data, ack=False))
                    return
            # empty OK for missing assets
            conn.sendall(_http_envelope(b"", ack=False))
            return

        conn.sendall(_http_envelope(BODY_RC, ack=False))
    except Exception as e:
        _log(f"{peer} error: {e}")
    finally:
        _close_clean(conn)


def _serve_plain(port: int) -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    s.listen(20)
    _log(f"HTTP  :{port}")
    while True:
        c, _ = s.accept()
        threading.Thread(target=_handle_one, args=(c, "http"), daemon=True).start()


def _serve_tls(port: int) -> None:
    cert, key = TLS_DIR / "leaf-chain.crt", TLS_DIR / "leaf.key"
    if not cert.exists() or not key.exists():
        raise SystemExit(f"missing certs {TLS_DIR}")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    if hasattr(ssl, "TLSVersion"):
        ctx.minimum_version = ssl.TLSVersion.TLSv1
    try:
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    except ssl.SSLError:
        pass
    ctx.load_cert_chain(str(cert), str(key))
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    s.listen(20)
    ack = os.environ.get("CATCHER_LOGIN_ACK", "1")
    _log(
        f"CATCHER_REV={CATCHER_REV} HTTPS :{port} "
        f"login_ack={ack} (GuestLogin→LoginSuccessful)"
    )
    while True:
        c, _ = s.accept()
        try:
            tls = ctx.wrap_socket(c, server_side=True)
        except Exception as e:
            _log(f"TLS fail: {e}")
            try:
                c.close()
            except Exception:
                pass
            continue
        threading.Thread(target=_handle_one, args=(tls, "https"), daemon=True).start()


def main() -> None:
    LOG.write_text(f"# {CATCHER_REV}\n", encoding="utf-8")
    for d in (
        RES / "resources" / "config" / "1.0" / "1",
        RES / "resources" / "langs",
        RES / "langs",
    ):
        d.mkdir(parents=True, exist_ok=True)
    src = RES / "config" / "lang.conf"
    if src.is_file():
        dest = RES / "resources" / "config" / "1.0" / "1" / "lang.conf"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
    for name in ("lang.eng", "lang.en"):
        for dest in (RES / "langs" / name, RES / "resources" / "langs" / name):
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.is_file():
                dest.write_text("OK=OK\nRTL=No\n", encoding="utf-8")

    _log(f"CATCHER_REV={CATCHER_REV} → {PC_IP}")
    _log("GetGeo skip OK (ServerId=1). Now mocking Realtime LoginSuccessful.")
    _log("Empty map = tiles not mocked yet (next step after login works).")

    threading.Thread(
        target=_serve_plain,
        args=(int(os.environ.get("CATCHER_HTTP_PORT", "80")),),
        daemon=True,
    ).start()
    try:
        _serve_tls(int(os.environ.get("CATCHER_HTTPS_PORT", "443")))
    except KeyboardInterrupt:
        _log("stopped")


if __name__ == "__main__":
    main()
