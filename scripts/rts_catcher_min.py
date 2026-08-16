#!/usr/bin/env python3
"""CATCHER_REV=cycle-20260816i

Waze iOS 3.9.x RTS catcher — cycles GetGeo response variants per POST.

Both phones accept TLS and get a 200, but never GET :80 → transaction fails
inside WST/geo_config (not a DNS/prefs issue). We cycle the likely causes:

  1) plain + LF + 5×ServerConfig   (match phone request LF; rewrite Download.*)
  2) plain + LF + bare             (num_params=0; prefs already patched)
  3) gzip wire-CL + LF + geo5
  4) gzip plain-CL + LF + geo5     (if WST counts post-inflate bytes)
  5) plain + CRLF + geo5
  6) plain + LF + lang=en          (rts_catcher.py used "en" not "eng")

Success = any GET lang.conf / lang.eng on :80.
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

CATCHER_REV = "cycle-20260816i"

os.environ.setdefault("CATCHER_MODE", "cycle")
os.environ.setdefault("CATCHER_BODY", "cycle")
os.environ.setdefault("CATCHER_NL", "lf")
os.environ.setdefault("CATCHER_CTYPE", "binary/octet-stream")
os.environ.setdefault("CATCHER_HTTP_VER", "1.0")
os.environ.setdefault("CATCHER_DRAIN_SEC", "5.0")

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "logs" / "rts-catcher.txt"
TLS_DIR = ROOT / "mitm" / "certs" / "tls"
RES = ROOT / "mitm" / "fake-resources"

PC_IP = os.environ.get("PC_IP", "192.168.1.191").strip()
BASE = f"http://{PC_IP}"

BIN_CT = "binary/octet-stream"

_variant_i = 0
_variant_lock = threading.Lock()


def _log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _lines(nl: str, *rows: str) -> bytes:
    return (nl.join(rows) + nl).encode("ascii")


def _geo5(nl: str, lang: str = "eng") -> bytes:
    return _lines(
        nl,
        "RC,200,OK",
        f"GeoServerConfig,1,world,{lang},5,1",
        f"ServerConfig,0,Download,Config,{BASE}/resources/config/",
        f"ServerConfig,1,Download,Langs,{BASE}/resources/langs/",
        f"ServerConfig,2,Download,Images,{BASE}/resources/images/",
        f"ServerConfig,3,Download,Sound,{BASE}/resources/sounds/",
        f"ServerConfig,4,Download,Langs TTS,{BASE}/resources/lang_tts/",
    )


def _bare(nl: str, lang: str = "eng") -> bytes:
    return _lines(nl, "RC,200,OK", f"GeoServerConfig,1,world,{lang},0,1")


def _waze_gzip(data: bytes) -> bytes:
    """Gzip with flags=0 (required by Waze roadmap_http_comp)."""
    comp = zlib.compressobj(6, zlib.DEFLATED, -15)
    body = comp.compress(data) + comp.flush()
    header = b"\x1f\x8b\x08\x00" + struct.pack("<I", 0) + b"\x00\xff"
    crc = zlib.crc32(data) & 0xFFFFFFFF
    trailer = struct.pack("<II", crc, len(data) % (2**32))
    return header + body + trailer


def _http_ver() -> bytes:
    ver = os.environ.get("CATCHER_HTTP_VER", "1.0").strip() or "1.0"
    return f"HTTP/{ver} 200 OK\r\n".encode()


def _http_response(body: bytes, *, mode: str, ctype: str) -> bytes:
    status = _http_ver()
    if mode == "gzip_wire_cl":
        gz = _waze_gzip(body)
        return (
            status
            + f"Content-Type: {ctype}\r\n".encode()
            + b"Content-Encoding: gzip\r\n"
            + f"Content-Length: {len(gz)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
            + gz
        )
    if mode == "gzip_plain_cl":
        gz = _waze_gzip(body)
        return (
            status
            + f"Content-Type: {ctype}\r\n".encode()
            + b"Content-Encoding: gzip\r\n"
            + f"Content-Length: {len(body)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
            + gz
        )
    return (
        status
        + f"Content-Type: {ctype}\r\n".encode()
        + f"Content-Length: {len(body)}\r\n".encode()
        + b"Connection: close\r\n\r\n"
        + body
    )


# (label, mode, body_bytes)
def _variants() -> list[tuple[str, str, bytes]]:
    return [
        ("1/6 plain+LF+geo5", "plain_cl", _geo5("\n")),
        ("2/6 plain+LF+bare", "plain_cl", _bare("\n")),
        ("3/6 gzip_wire+LF+geo5", "gzip_wire_cl", _geo5("\n")),
        ("4/6 gzip_plainCL+LF+geo5", "gzip_plain_cl", _geo5("\n")),
        ("5/6 plain+CRLF+geo5", "plain_cl", _geo5("\r\n")),
        ("6/6 plain+LF+geo5+lang=en", "plain_cl", _geo5("\n", "en")),
    ]


def _next_variant() -> tuple[str, str, bytes]:
    global _variant_i
    force = os.environ.get("CATCHER_MODE", "cycle").strip()
    body_force = os.environ.get("CATCHER_BODY", "cycle").strip()
    variants = _variants()

    # Fixed experiment if not cycling
    if force != "cycle" and body_force != "cycle":
        nl = "\n" if os.environ.get("CATCHER_NL", "lf").lower() != "crlf" else "\r\n"
        if body_force == "bare":
            body = _bare(nl)
        else:
            body = _geo5(nl)
        return (f"fixed mode={force} body={body_force}", force, body)

    with _variant_lock:
        idx = _variant_i % len(variants)
        _variant_i += 1
    return variants[idx]


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
    drain = float(os.environ.get("CATCHER_DRAIN_SEC", "5.0"))
    time.sleep(drain)
    try:
        conn.close()
    except Exception:
        pass


def _watch_http() -> None:
    time.sleep(20.0)
    _log("  watch: si aucun GET :80 après ~20s → cette variante a échoué; rouvre Waze pour la suivante")


def _res_candidates(path: str) -> list[Path]:
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
        ]
    if name.startswith("lang."):
        out += [RES / "langs" / name, RES / "resources" / "langs" / name]
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
            low = line.lower()
            if low.startswith(b"host:") or low.startswith(b"user-agent:") or low.startswith(
                b"accept-encoding:"
            ) or low.startswith(b"content-length:"):
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
            _log(f"  req ({len(req_body)}B) {req_body[:120]!r}...")
            label, mode, body = _next_variant()
            resp = _http_response(body, mode=mode, ctype=ctype)
            conn.sendall(resp)
            wh, _, payload = resp.partition(b"\r\n\r\n")
            cl_hdr = "?"
            for line in wh.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    cl_hdr = line.split(b":", 1)[1].strip().decode()
            _log(
                f"  → VARIANT {label} plain={len(body)}B payload={len(payload)}B "
                f"wire={len(resp)}B CL={cl_hdr}"
            )
            _log(f"  → plain head={body[:80]!r}...")
            _log(f"  → resp-hdr:\n{wh.decode('latin1', errors='replace')}")
            threading.Thread(target=_watch_http, daemon=True).start()
            return

        if "GET" in first:
            _log(f"  ★ GET {host!r} {path!r}  ← GetGeo ACCEPTÉ")
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
            _log(f"  GET MISS {path!r}")
            conn.sendall(
                _http_response(b"", mode="plain_cl", ctype="application/octet-stream")
            )
            return

        conn.sendall(_http_response(_bare("\n"), mode="plain_cl", ctype=ctype))
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
    _log(f"CATCHER_REV={CATCHER_REV} HTTPS :{port} MODE=cycle (6 variantes)")
    _log(f"GetGeo cycle → Download.* → {PC_IP} | succès = ★ GET sur :80")
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
    LOG.write_text(f"# {CATCHER_REV} — cycle GetGeo variants\n", encoding="utf-8")
    for d in (
        RES / "newVconfig" / "1",
        RES / "resources" / "config" / "1.0" / "1",
        RES / "resources" / "config" / "1",
        RES / "resources" / "langs",
        RES / "langs",
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
    for lang_name in ("lang.eng", "lang.en"):
        for dest in (RES / "langs" / lang_name, RES / "resources" / "langs" / lang_name):
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.is_file():
                dest.write_text("OK=OK\nRTL=No\n", encoding="utf-8")

    _log(f"CATCHER_REV={CATCHER_REV} cycling 6 GetGeo variants → {PC_IP}")
    for label, mode, body in _variants():
        _log(f"  {label}: mode={mode} {len(body)}B")

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
