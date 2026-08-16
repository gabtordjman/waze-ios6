#!/usr/bin/env python3
"""CATCHER_REV=reg-proto202-20260816aa

Docs (no public Register pcap found):
  - Freemap GPL RealtimeNetRec.c OnRegisterResponse (protocol ~150):
      RC,200,OK
      RegisterSuccessful,<user>,<pass>
  - That format was tried for hours on this IPA → Failed to create account, no Login.
  - This IPA sends ClientInfo protocol 202 and a truncated Register, (no %d,%d,%s).
  - Jeske/BlackHat: after auth the client needs server ID + cookie (LoginSuccessful fields).

Hypothesis (protocol 202): RegisterSuccessful payload mirrors LoginSuccessful
(id,cookie,rank,points,…) so the random-register path can leave a session ready
(or at least parse). STOP blind A–G cycling.
"""

from __future__ import annotations

import datetime as dt
import os
import socket
import ssl
import threading
import time
from pathlib import Path

CATCHER_REV = "reg-proto202-20260816aa"

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

# Freemap OnLoginResponse field order (RealtimeNetRec.c)
LOGIN_OK = "LoginSuccessful,1,cookie123456,1,100,1,1,0,0,0,202,3.9.6.1"
# Same fields under RegisterSuccessful — protocol-202 hypothesis
REGISTER_OK = "RegisterSuccessful,1,cookie123456,1,100,1,1,0,0,0,202,3.9.6.1"


def _log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _lines(rows: list[str], *, crlf: bool = False) -> bytes:
    nl = "\r\n" if crlf else "\n"
    return (nl.join(rows) + nl).encode("ascii")


BODY_GEO5 = _lines(
    [
        "RC,200,OK",
        "GeoServerConfig,1,world,eng,5,1",
        f"ServerConfig,0,Download,Config,{BASE}/resources/config/",
        f"ServerConfig,1,Download,Langs,{BASE}/resources/langs/",
        f"ServerConfig,2,Download,Images,{BASE}/resources/images/",
        f"ServerConfig,3,Download,Sound,{BASE}/resources/sounds/",
        f"ServerConfig,4,Download,Langs TTS,{BASE}/resources/lang_tts/",
    ]
)
BODY_LOGIN = _lines(["RC,200,OK", LOGIN_OK])
BODY_REGISTER = _lines(["RC,200,OK", REGISTER_OK])
BODY_RC = _lines(["RC,200,OK"])


def _cmds(req_body: bytes) -> list[str]:
    out: list[str] = []
    for line in req_body.replace(b"\r\n", b"\n").split(b"\n"):
        if not line.strip():
            continue
        out.append(line.split(b",", 1)[0].decode("latin1", errors="replace"))
    return out


def _ack_for(path: str) -> bytes:
    # IPA always hits /distrib/ for Register; OnHTTPAck requires ack\r\n
    if "/distrib/" in path.lower():
        return b"ack\r\n"
    return b""


def _classify(req_body: bytes, path: str = "") -> tuple[str, bytes, bool]:
    """Returns label, body, close_after (True=Connection:close)."""
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
        return "Login→LoginSuccessful", BODY_LOGIN, False

    if b"register," in low:
        _log(f"  req ({len(req_body)}B): {req_body!r}")
        # close so WST finalizes on EOF; Login (if any) = new TCP
        return "Register→proto202_LoginFields", BODY_REGISTER, True

    if b"getgeoserverconfig" in low or b"getgeoconfig" in low:
        return "GetGeo→geo5", BODY_GEO5, False

    return "RC only", BODY_RC, False


def _http_envelope(body: bytes, *, ack: bytes, close: bool) -> bytes:
    ver = os.environ.get("CATCHER_HTTP_VER", "1.1")
    ctype = os.environ.get("CATCHER_CTYPE", BIN_CT)
    conn = b"Connection: close\r\n" if close else b"Connection: keep-alive\r\n"
    hdr = (
        f"HTTP/{ver} 200 OK\r\n".encode()
        + f"Content-Type: {ctype}\r\n".encode()
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
                _log(f"  → body:\n{body.decode('ascii', errors='replace')}")
                if "Register→" in label:
                    _log("  Succès = Login POST ou tuiles. Failed = encore faux format.")
                if "Login→" in label:
                    _log("  ★ Login")
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
                name = Path(path).name
                payload = b""
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
                conn.sendall(_http_envelope(payload, ack=b"", close=False))
                continue

            conn.sendall(
                _http_envelope(BODY_RC, ack=_ack_for(path), close=False)
            )
    except Exception as e:
        _log(f"{peer} error: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _serve_plain(port: int) -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    s.listen(20)
    _log(f"HTTP  :{port}")
    while True:
        c, _ = s.accept()
        threading.Thread(target=_handle_conn, args=(c, "http"), daemon=True).start()


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
    _log(f"CATCHER_REV={CATCHER_REV} HTTPS :{port}")
    while True:
        c, _ = s.accept()

        def _wrap(sock: socket.socket) -> None:
            try:
                ss = ctx.wrap_socket(sock, server_side=True)
            except Exception as e:
                _log(f"TLS accept: {e}")
                try:
                    sock.close()
                except Exception:
                    pass
                return
            _handle_conn(ss, "https")

        threading.Thread(target=_wrap, args=(c,), daemon=True).start()


def main() -> None:
    http_port = int(os.environ.get("CATCHER_HTTP_PORT", "80"))
    https_port = int(os.environ.get("CATCHER_HTTPS_PORT", "443"))
    _log(f"CATCHER_REV={CATCHER_REV} → {PC_IP}")
    _log("Register→LoginSuccessful fields (proto 202). Freemap user,pass abandoned.")
    threading.Thread(target=_serve_plain, args=(http_port,), daemon=True).start()
    threading.Thread(target=_serve_tls, args=(https_port,), daemon=True).start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
