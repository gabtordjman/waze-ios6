#!/usr/bin/env python3
"""HTTP + HTTPS mock for legacy Waze iOS 3.9.x.

ClientInfo + GetGeoServerConfig on /rtserver/login → login_parser style:
  RC,200,OK
  LoginSuccessful,...
  GeoServerConfig,...

After geo config, iPhone downloads lang.conf / lang.* from
  http://waze-client-resources.s3.amazonaws.com/...
Bucket is dead → we DNS-hijack S3 here and serve fake files.
"""

from __future__ import annotations

import datetime as dt
import os
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "logs" / "rts-catcher.txt"
TLS_DIR = ROOT / "mitm" / "certs" / "tls"
RES = ROOT / "mitm" / "fake-resources"

WS = "https://rt.waze.com/rtserver"

FAKE_HTML = (
    b"<html><body><h1>RTS catcher OK</h1>"
    b"<p>Mock RTS + lang resources. Ouvre Waze.</p></body></html>"
)


def _log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _lines(*rows: str, nl: str = "\r\n") -> bytes:
    return (nl.join(rows) + nl).encode("utf-8")


def _waze_gzip(data: bytes) -> bytes:
    """Gzip with flags=0 (required by Waze roadmap_http_comp)."""
    import struct
    import zlib

    comp = zlib.compressobj(6, zlib.DEFLATED, -15)
    body = comp.compress(data) + comp.flush()
    header = b"\x1f\x8b\x08\x00" + struct.pack("<I", 0) + b"\x00\xff"
    crc = zlib.crc32(data) & 0xFFFFFFFF
    trailer = struct.pack("<II", crc, len(data) % (2**32))
    return header + body + trailer


# ClientInfo → login_parser: RC+LoginSuccessful+GeoServerConfig
# Request uses LF (\n) only — match that. Login is HTTPS but NOT V2 (no ack).
# Download URLs in this IPA default to S3 (DNS sinkhole), not 75.101 — no phone patch needed.
FORM_CT = "application/x-www-form-urlencoded; charset=utf-8"
BIN_CT = "binary/octet-stream"

# id,cookie,rank,points,rating,prev,addon,ts,moods,maxProto,ver,userid,fb,friends,joined,pic,email
# Login server-id MUST be coherent; use 1 like GeoServerConfig id
_LOGIN_GPL = "LoginSuccessful,1,cookie123456,1,100,1,1,0,0,0,202,3.9.6.1"
_LOGIN_IPA = _LOGIN_GPL + ",1,guest,0,1360000000,0,guest"
_LOGIN_PAD = _LOGIN_IPA + ",0,0,0,0,0,F,F"
_GEO_OK = "GeoServerConfig,1,world,en,0,1"

_VARIANT_I = 0


def _variants() -> list[tuple[str, bytes, dict]]:
    """GetGeo uses geo_config_parser — LoginSuccessful has no handler → hard fail."""
    gpl = _lines("RC,200,OK", _LOGIN_GPL, _GEO_OK, nl="\r\n")
    ipa = _lines("RC,200,OK", _LOGIN_IPA, _GEO_OK, nl="\r\n")
    geo_rc = _lines("RC,200,OK", _GEO_OK, nl="\r\n")
    return [
        ("RC+Geo ONLY (correct for GetGeo)", geo_rc, {"ctype": BIN_CT}),
        ("RC+Geo gzip", geo_rc, {"ctype": BIN_CT, "gzip": True}),
        ("IPA17 Login+Geo (WRONG for GetGeo)", ipa, {"ctype": BIN_CT}),
        ("GPL11 Login+Geo (WRONG for GetGeo)", gpl, {"ctype": BIN_CT}),
    ]


def _clientinfo_body() -> tuple[bytes, dict]:
    global _VARIANT_I
    variants = _variants()
    force = os.environ.get("FORCE_VARIANT", "").strip()
    if force.isdigit():
        idx = int(force) % len(variants)
    else:
        idx = _VARIANT_I % len(variants)
        _VARIANT_I += 1
    name, body, opts = variants[idx]
    _log(f"MOCK → [{idx + 1}/{len(variants)}] {name} ({len(body)}B {opts})")
    return body, opts


def _geo_only_body() -> tuple[bytes, dict]:
    return _clientinfo_body()


def _login_ok_body() -> bytes:
    return _lines("RC,200,OK", _LOGIN_IPA)


def _generic_ok() -> bytes:
    return _lines("RC,200,OK")


def build_rts_response(path: str, body: bytes) -> tuple[bytes, dict]:
    """Returns (body, opts) with optional ctype / gzip / raw_ack."""
    text = body.decode("utf-8", errors="replace")
    path_l = path.lower()
    low = text.lower()

    if (
        "clientinfo," in low
        or "getgeoserverconfig" in low
        or "getgeoconfig" in low
        or "/rtserver/login" in path_l
        or path_l.endswith("/login")
    ):
        return _clientinfo_body()

    if "guestlogin" in low or (
        "\nlogin," in f"\n{low}" or low.startswith("login,")
    ):
        _log("MOCK → Login OK")
        return _login_ok_body(), {"ctype": "binary/octet-stream"}

    if "register," in low:
        _log("MOCK → Register OK")
        return (
            _lines("RC,200,OK", "RegisterSuccessful,4242,ios6regcookie"),
            {"ctype": "binary/octet-stream"},
        )

    _log("MOCK → RC,200 only")
    return _generic_ok(), {"ctype": "binary/octet-stream"}


def _resolve_resource(path: str) -> Path | None:
    """Map S3 / legacy /resources/... /config/<id>/lang.conf paths."""
    p = unquote(urlparse(path).path)
    rel = p.lstrip("/")
    if rel.startswith("resources/"):
        rel = rel[len("resources/") :]
    name = Path(p).name
    candidates = [
        RES / rel,
        RES / p.lstrip("/"),
        RES / "langs" / name,
        RES / "config" / name,
    ]
    # GPL: .../config/<serverId>/lang.conf
    parts = Path(rel).parts
    if name == "lang.conf":
        candidates.append(RES / "config" / "lang.conf")
    if name.startswith("lang."):
        candidates.append(RES / "langs" / name)
    if len(parts) >= 2 and parts[0] == "config":
        candidates.append(RES / "config" / name)
    if len(parts) >= 2 and parts[0] == "langs":
        candidates.append(RES / "langs" / name)
    for c in candidates:
        if c.is_file():
            return c
    return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    scheme = "http"

    def log_message(self, fmt: str, *args) -> None:
        _log(f"{self.scheme} httpd: " + (fmt % args))

    def _dump_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        peer = self.client_address[0]
        _log(f"{peer} {self.scheme.upper()} {self.command} {self.path}")
        for k, v in list(self.headers.items())[:12]:
            _log(f"  hdr {k}: {v}")
        if body:
            preview = " ".join(body.decode("utf-8", errors="replace").split())[
                :400
            ]
            _log(f"  body-text: {preview}")
            dump = (
                ROOT
                / "logs"
                / f"rts-body-{self.scheme}-{dt.datetime.now():%H%M%S-%f}.bin"
            )
            dump.write_bytes(body)
            _log(f"  saved {dump.name}")
        return body

    def do_GET(self) -> None:
        self._dump_body()
        host = (self.headers.get("Host") or "").lower()
        path = self.path.split("?", 1)[0]
        _log(f"GET host={host!r} path={path!r}")

        if path in ("/", "/index.html") and "s3" not in host and "amazonaws" not in host:
            self._reply(200, FAKE_HTML, "text/html; charset=utf-8")
            return

        # Resource download (lang / config / sounds / images)
        res = _resolve_resource(path)
        if res is not None:
            data = res.read_bytes()
            _log(f"RES → {res.relative_to(ROOT)} ({len(data)} bytes)")
            self._reply(200, data, "application/octet-stream")
            return

        # Empty placeholder for missing images/sounds so download errors don't hang
        if any(
            x in path
            for x in (
                "/images/",
                "/sounds/",
                "/langs/",
                "/config/",
                "/resources/",
            )
        ):
            _log(f"RES missing → empty 200 for {path}")
            self._reply(200, b"", "application/octet-stream")
            return

        self._reply(200, _generic_ok())

    def do_POST(self) -> None:
        body = self._dump_body()
        resp, opts = build_rts_response(self.path, body)
        ctype = opts.get("ctype", "binary/octet-stream")
        enc_hdr = b""
        if opts.get("gzip"):
            resp = _waze_gzip(resp)
            enc_hdr = b"Content-Encoding: gzip\r\n"
        prefix = b"ack\r\n" if opts.get("raw_ack") else b""
        # HTTP/1.0 + Connection:close: Waze waits on Content-Length; every
        # byte must hit the wire before TLS close (makefile buffering was
        # a suspect for infinite spinner with no network error).
        payload = (
            prefix
            + b"HTTP/1.0 200 OK\r\n"
            + f"Content-Type: {ctype}\r\n".encode()
            + enc_hdr
            + f"Content-Length: {len(resp)}\r\n".encode()
            + b"Connection: close\r\n"
            + b"\r\n"
            + resp
        )
        sock = self.connection
        try:
            # Bypass rfile/wfile buffering — write the full TLS record(s).
            if hasattr(sock, "sendall"):
                sock.sendall(payload)
            else:
                self.wfile.write(payload)
                self.wfile.flush()
        except Exception as e:
            _log(f"  → send error: {e}")
        _log(
            f"  → SENT {len(payload)}B wire (body {len(resp)}B) "
            f"ctype={ctype} gzip={bool(opts.get('gzip'))} ack={bool(opts.get('raw_ack'))} "
            f"body={resp!r}"
        )
        self.close_connection = True
        # Stop BaseHTTPRequestHandler.finish() from touching a half-closed SSL socket
        try:
            self.wfile._sock = None  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            sock.shutdown(socket.SHUT_WR)
        except Exception:
            pass

    def do_HEAD(self) -> None:
        self._dump_body()
        self._reply(200, b"")

    def _reply(
        self,
        code: int,
        body: bytes,
        ctype: str = "binary/octet-stream",
        extra: dict | None = None,
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)


class HTTPSHandler(Handler):
    scheme = "https"


def _serve(httpd: ThreadingHTTPServer, label: str) -> None:
    _log(f"{label} serving")
    try:
        httpd.serve_forever()
    except Exception as e:
        _log(f"{label} stopped: {e}")


def main() -> None:
    http_port = int(os.environ.get("CATCHER_HTTP_PORT", "80"))
    https_port = int(os.environ.get("CATCHER_HTTPS_PORT", "443"))

    LOG.write_text("# Waze RTS + lang resources mock\n", encoding="utf-8")

    httpd = ThreadingHTTPServer(("0.0.0.0", http_port), Handler)
    threading.Thread(
        target=_serve, args=(httpd, f"http:{http_port}"), daemon=True
    ).start()
    _log(f"HTTP  on 0.0.0.0:{http_port} (RTS + S3 lang mocks)")

    cert = TLS_DIR / "leaf-chain.crt"
    key = TLS_DIR / "leaf.key"
    if not cert.exists() or not key.exists():
        _log(f"ERREUR: certificats manquants dans {TLS_DIR}")
        raise SystemExit(1)

    httpsd = ThreadingHTTPServer(("0.0.0.0", https_port), HTTPSHandler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    if hasattr(ssl, "TLSVersion"):
        ctx.minimum_version = ssl.TLSVersion.TLSv1
    ctx.load_cert_chain(str(cert), str(key))
    try:
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    except ssl.SSLError:
        pass
    httpsd.socket = ctx.wrap_socket(httpsd.socket, server_side=True)
    _log(f"HTTPS on 0.0.0.0:{https_port}")
    _log("DNS: pointe aussi waze-client-resources.s3.amazonaws.com → ce PC")

    try:
        httpsd.serve_forever()
    except KeyboardInterrupt:
        _log("stopped")
        httpd.shutdown()


if __name__ == "__main__":
    main()
