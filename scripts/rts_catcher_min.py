#!/usr/bin/env python3
"""Waze iOS 3.9.x RTS catcher — ultimate v3.

From IPA 3.9.6 (strings + Freemap parser):
  GeoServerConfig,<id>,<name>,<lang>,<num_params>,<version>
  then num_params × ServerConfig,<serial>,<category>,<key>,<value>

After geo OK, app downloads lang.conf via Download.Config from preferences:
  http://75.101.158.200/resources/config/1.0/<serverId>/lang.conf
That AWS IP is dead → inject ServerConfig to rewrite Download.* to this PC.

gzip: Content-Length = plaintext size (WST counts decompressed bytes).
"""

from __future__ import annotations

import datetime as dt
import gzip
import os
import socket
import ssl
import struct
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "logs" / "rts-catcher.txt"
DNSLOG = ROOT / "logs" / "dnsmasq-waze.log"
TLS_DIR = ROOT / "mitm" / "certs" / "tls"
RES = ROOT / "mitm" / "fake-resources"

PC_IP = os.environ.get("PC_IP", "192.168.1.191").strip()
BASE = f"http://{PC_IP}"


def _geo_body_with_downloads() -> bytes:
    """RC + GeoServerConfig + ServerConfig rows that point downloads at the PC."""
    rows = [
        "RC,200,OK",
        "GeoServerConfig,1,world,eng,5,1",
        f"ServerConfig,0,Download,Config,{BASE}/resources/config/",
        f"ServerConfig,1,Download,Langs,{BASE}/resources/langs/",
        f"ServerConfig,2,Download,Images,{BASE}/resources/images/",
        f"ServerConfig,3,Download,Sound,{BASE}/resources/sounds/",
        f"ServerConfig,4,Download,Langs TTS,{BASE}/resources/lang_tts/",
    ]
    return ("\r\n".join(rows) + "\r\n").encode("ascii")


# CRLF terminators match ExtractNetworkString(",\\r\\n") / VerifyStatus
BODY_GEO = _geo_body_with_downloads()
BODY_GEO_BARE = b"RC,200,OK\r\nGeoServerConfig,1,world,eng,0,1\r\n"
BODY_LOGIN = (
    b"RC,200,OK\r\n"
    b"LoginSuccessful,1,cookie123456,1,100,1,1,0,0,0,202,3.9.6.1,"
    b"1,guest,0,1360000000,0,guest\r\n"
    b"GeoServerConfig,1,world,eng,0,1\r\n"
)
# TEST: un RC,200,OK par commande batchée reçue (ClientInfo + GetGeoServerConfig)
# Hypothèse: le parseur attend un ack séparé par commande envoyée dans le POST,
# pas un seul RC global pour tout le batch.
BODY_DOUBLE_RC = (
    b"RC,200,OK\r\n"
    b"RC,200,OK\r\n"
    b"GeoServerConfig,1,world,eng,0,1\r\n"
)

# wst_init default content-type
BIN_CT = "binary/octet-stream"
FORM_CT = "application/x-www-form-urlencoded; charset=utf-8"


def _log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _gzip(plain: bytes) -> bytes:
    out = gzip.compress(plain, compresslevel=9, mtime=0)
    if out[0:2] != b"\x1f\x8b" or out[3] != 0:
        raise RuntimeError(f"bad gzip hdr {out[:10]!r}")
    return out


def _http_response(body: bytes, *, mode: str, ctype: str) -> bytes:
    """
    ultimate / gzip_plain_cl — gzip + Content-Length=len(PLAIN)  [DEFAULT v2]
    plain_cl                 — no gzip, CL=len(body)
    gzip_wire_cl             — WRONG (hang) — only for repro
    gzip_nocL                — gzip, no CL
    """
    if mode in ("ultimate", "gzip_plain_cl"):
        gz = _gzip(body)
        # CRITICAL: CL = plaintext size for WST accounting
        return (
            b"HTTP/1.1 200 OK\r\n"
            + f"Content-Type: {ctype}\r\n".encode()
            + b"Content-Encoding: gzip\r\n"
            + f"Content-Length: {len(body)}\r\n".encode()
            + b"Connection: close\r\n"
            + b"\r\n"
            + gz
        )
    if mode == "gzip_wire_cl":
        gz = _gzip(body)
        return (
            b"HTTP/1.1 200 OK\r\n"
            + f"Content-Type: {ctype}\r\n".encode()
            + b"Content-Encoding: gzip\r\n"
            + f"Content-Length: {len(gz)}\r\n".encode()
            + b"Connection: close\r\n"
            + b"\r\n"
            + gz
        )
    if mode == "gzip_nocL":
        gz = _gzip(body)
        return (
            b"HTTP/1.1 200 OK\r\n"
            + f"Content-Type: {ctype}\r\n".encode()
            + b"Content-Encoding: gzip\r\n"
            + b"Connection: close\r\n"
            + b"\r\n"
            + gz
        )
    # plain_cl
    return (
        b"HTTP/1.1 200 OK\r\n"
        + f"Content-Type: {ctype}\r\n".encode()
        + f"Content-Length: {len(body)}\r\n".encode()
        + b"Connection: close\r\n"
        + b"\r\n"
        + body
    )


def _read_request(conn: socket.socket, limit: int = 65536) -> bytes:
    data = b""
    conn.settimeout(10.0)
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
    # Client often FINs in <20ms on parse fail; still drain briefly
    time.sleep(float(os.environ.get("CATCHER_DRAIN_SEC", "0.3")))
    try:
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 5))
    except Exception:
        pass
    try:
        if isinstance(conn, ssl.SSLSocket):
            try:
                conn.unwrap()
            except Exception:
                pass
        conn.close()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def _watch_dns() -> None:
    time.sleep(0.5)
    deadline = time.time() + 35.0
    last = DNSLOG.stat().st_size if DNSLOG.is_file() else 0
    hits = 0
    while time.time() < deadline:
        try:
            if DNSLOG.is_file():
                sz = DNSLOG.stat().st_size
                if sz > last:
                    with DNSLOG.open("rb") as f:
                        f.seek(last)
                        text = f.read().decode("utf-8", errors="replace")
                    last = sz
                    for line in text.splitlines():
                        if "192.168.1.60" not in line:
                            continue
                        low = line.lower()
                        if any(
                            x in low
                            for x in (
                                "waze-client-resources",
                                "s3.amazonaws",
                                "newvconfig",
                                "75.101",
                            )
                        ):
                            hits += 1
                            _log(f"  DNS+: {line.strip()}")
        except Exception:
            pass
        time.sleep(0.4)
    _log(f"  DNS watch: {hits} hit(s)" if hits else "  DNS watch: aucun (OK si ServerConfig→PC)")


def _res_candidates(path: str) -> list[Path]:
    """IPA builds: Download.Config + Ver + serverId + lang.conf
    e.g. /resources/config/1.0/1/lang.conf
    """
    name = Path(path).name
    rel = path.lstrip("/")
    out = [
        RES / rel,
        RES / path.lstrip("/"),
        RES / "resources" / rel,
        RES / "newVconfig" / name,
        RES / "config" / name,
        RES / "langs" / name,
        RES / "resources" / "langs" / name,
    ]
    if name == "lang.conf":
        out += [
            RES / "resources" / "config" / "1.0" / "1" / "lang.conf",
            RES / "resources" / "config" / "1" / "lang.conf",
            RES / "newVconfig" / "1" / "lang.conf",
            RES / "config" / "lang.conf",
            RES / "config" / "1" / "lang.conf",
        ]
    if name.startswith("lang."):
        out += [RES / "langs" / name, RES / "resources" / "langs" / name]
    # de-dup preserve order
    seen: set[str] = set()
    uniq: list[Path] = []
    for c in out:
        k = str(c)
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq


def _handle_one(conn: socket.socket, scheme: str) -> None:
    peer = "?"
    mode = os.environ.get("CATCHER_MODE", "ultimate").strip()
    body_kind = os.environ.get("CATCHER_BODY", "geo").strip()
    ctype = os.environ.get("CATCHER_CTYPE", BIN_CT).strip()
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
            _log(f"  hdr: {line.decode('latin1', errors='replace')}")

        path = "/"
        parts = first.split(" ")
        if len(parts) >= 2:
            path = parts[1].split("?", 1)[0]
        host = ""
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"host:"):
                host = line.split(b":", 1)[1].strip().decode("latin1", errors="replace")

        if "POST" in first and "/rtserver" in path:
            _log(f"  req ({len(req_body)}B) {req_body!r}")
            if body_kind == "login":
                body = BODY_LOGIN
            elif body_kind == "bare":
                body = BODY_GEO_BARE
            elif body_kind == "double_rc":
                body = BODY_DOUBLE_RC
            else:
                body = BODY_GEO  # geo + Download.* → PC (v3)
            resp = _http_response(body, mode=mode, ctype=ctype)
            conn.sendall(resp)
            wh, _, payload = resp.partition(b"\r\n\r\n")
            _log(
                f"  → mode={mode} body={body_kind} plain={len(body)}B "
                f"payload={len(payload)}B wire={len(resp)}B "
                f"CL_in_hdr=plain_size PC={PC_IP}"
            )
            _log(f"  → plain={body!r}")
            _log(f"  → resp-hdr:\n{wh.decode('latin1', errors='replace')}")
            threading.Thread(target=_watch_dns, daemon=True).start()
            return

        if "GET" in first:
            _log(f"  GET {host!r} {path!r}")
            for c in _res_candidates(path):
                if c.is_file():
                    data = c.read_bytes()
                    _log(f"RES → {c.relative_to(ROOT)} ({len(data)}B)")
                    conn.sendall(
                        _http_response(
                            data, mode="plain_cl", ctype="text/plain; charset=utf-8"
                        )
                    )
                    return
            _log(f"  GET MISS {path!r} — tried {[str(c) for c in _res_candidates(path)[:6]]}")
            if any(
                x in path
                for x in ("/config/", "/newVconfig/", "/langs/", "/resources/", "/")
            ):
                conn.sendall(_http_response(b"", mode="plain_cl", ctype="application/octet-stream"))
                return

        conn.sendall(_http_response(BODY_GEO, mode=mode, ctype=ctype))
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
    mode = os.environ.get("CATCHER_MODE", "ultimate")
    _log(f"HTTPS :{port} mode={mode}")
    _log(f"v3: Geo+ServerConfig Download.* → {PC_IP} | gzip CL=plain")
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
    LOG.write_text("# ultimate v3 — ServerConfig redirects Download.* to PC\n", encoding="utf-8")
    # Ensure IPA-shaped paths exist for lang.conf
    for d in (
        RES / "newVconfig" / "1",
        RES / "resources" / "config" / "1.0" / "1",
        RES / "resources" / "config" / "1",
        RES / "resources" / "langs",
    ):
        d.mkdir(parents=True, exist_ok=True)
    src = RES / "config" / "lang.conf"
    if not src.is_file():
        src = RES / "resources" / "config" / "1.0" / "1" / "lang.conf"
    if src.is_file():
        for dest in (
            RES / "newVconfig" / "1" / "lang.conf",
            RES / "resources" / "config" / "1.0" / "1" / "lang.conf",
            RES / "resources" / "config" / "1" / "lang.conf",
            RES / "config" / "lang.conf",
        ):
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.is_file():
                dest.write_bytes(src.read_bytes())
    _log(f"BODY_GEO ({len(BODY_GEO)}B):\n{BODY_GEO.decode('ascii', errors='replace')}")
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
