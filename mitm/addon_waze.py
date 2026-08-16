"""
Addon mitmproxy — Waze iOS 6

Ce qu'on a appris des logs :
  - Safari + mitm CA OK (apple.com en HTTPS marche)
  - Waze PASSE par le proxy pour Facebook SDK
  - graph.facebook.com/v2.2/343050668156 → 400 (API morte)
  - AUCUNE requête *.waze.com → soit bloqué avant, soit API hors proxy

Cet addon :
  - mocke les réponses Facebook attendues par le vieux SDK
  - log clairement FB / WAZE / autres (filtre le bruit Apple)
  - sert http://cert.ios6/
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from mitmproxy import ctx, http

WAZE_HOST_RE = re.compile(
    r"(^|\.)(waze\.com|waze\.co\.il|row\.waze\.com|rt\.waze\.com|"
    r"desc\.waze\.com|config\.waze\.com)$",
    re.I,
)

NOISE_HOST_RE = re.compile(
    r"(apple\.com|icloud\.com|mzstatic\.com|cdn-apple\.com|"
    r"push\.apple\.com|me\.com)$",
    re.I,
)

CERT_HOSTS = {"cert.ios6", "cert.waze", "waze-cert"}
ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
SUMMARY = LOG_DIR / "summary.txt"
CERT_DIR = Path(__file__).resolve().parent / "certs"

# Facebook App ID historique de Waze
WAZE_FB_APP_ID = "343050668156"

FB_APP_OK = {
    "name": "Waze",
    "supports_implicit_sdk_logging": True,
    "gdpv4_nux_enabled": False,
    "gdpv4_nux_content": "",
    "ios_dialog_configs": {},
    "app_events_feature_bitmask": 0,
    "id": WAZE_FB_APP_ID,
}

IOS6_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fix TLS / Waze — iOS 6</title>
<style>
body{font-family:Helvetica,Arial,sans-serif;margin:16px;background:#f2f2f2;color:#222}
h1{font-size:22px} h2{font-size:18px}
a{display:block;margin:12px 0;padding:14px;background:#007aff;color:#fff;
  text-decoration:none;text-align:center;border-radius:6px;font-size:17px}
.sec{background:#fff;padding:12px;margin:12px 0;border:1px solid #ccc}
</style>
</head>
<body>
<h1>Waze / TLS iOS 6</h1>
<div class="sec">
<p>1. Installe Modern CA Roots puis <b>coupe le proxy</b> et reteste Waze.</p>
<p>2. Ou garde mitm + CA mitmproxy (Waze Facebook est mocké automatiquement).</p>
</div>
<a href="/ModernCARoots-iOS6.mobileconfig" style="background:#ff9500">Modern CA Roots</a>
<a href="/mitmproxy-ca.mobileconfig">mitmproxy CA</a>
</body>
</html>
"""


def _line(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = f"[{stamp}] {msg}"
    ctx.log.info(text)
    with SUMMARY.open("a", encoding="utf-8") as f:
        f.write(text + "\n")


def _host(flow: http.HTTPFlow) -> str:
    return (flow.request.pretty_host or "").lower()


def _is_noise(host: str) -> bool:
    return bool(NOISE_HOST_RE.search(host))


def _is_waze_host(host: str) -> bool:
    return bool(WAZE_HOST_RE.search(host)) or host.endswith(".waze.com")


def _is_fb(host: str) -> bool:
    return "facebook.com" in host or "fbcdn.net" in host or host.endswith("fb.com")


class WazeIOS6:
    def load(self, loader) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        SUMMARY.write_text(
            "# Waze iOS6 mitm summary\n"
            "# Facebook mock ON — ouvre Waze et cherche des lignes WAZE/FB\n\n",
            encoding="utf-8",
        )
        _line("addon chargé — FB mock ON — http://cert.ios6/")

    def request(self, flow: http.HTTPFlow) -> None:
        host = _host(flow)
        path = flow.request.path or "/"

        if host in CERT_HOSTS or (host == "mitm.it" and path.startswith("/ios6")):
            self._serve_cert(flow)
            return

        # --- Mock Facebook Graph (vieux SDK Waze) ---
        if _is_fb(host) and self._mock_facebook(flow):
            return

        if _is_waze_host(host):
            _line(f"WAZE REQ  {flow.request.method} {flow.request.pretty_url}")
        elif _is_fb(host):
            _line(f"FB   REQ  {flow.request.method} {flow.request.pretty_url}")
        elif not _is_noise(host):
            _line(f"HTTP REQ  {flow.request.method} {flow.request.pretty_url}")

    def response(self, flow: http.HTTPFlow) -> None:
        if flow.response is None:
            return
        host = _host(flow)
        if host in CERT_HOSTS:
            return
        if getattr(flow, "_waze_mocked", False):
            return

        code = flow.response.status_code
        if _is_waze_host(host):
            _line(f"WAZE RESP {code} {flow.request.method} {flow.request.pretty_url}")
            self._preview(flow, "WAZE")
        elif _is_fb(host):
            _line(f"FB   RESP {code} {flow.request.method} {flow.request.pretty_url}")
            self._preview(flow, "FB")
        elif not _is_noise(host):
            _line(f"HTTP RESP {code} {flow.request.method} {flow.request.pretty_url}")

    def error(self, flow: http.HTTPFlow) -> None:
        if flow.error:
            _line(f"ERR  {flow.request.pretty_url} :: {flow.error}")

    def _preview(self, flow: http.HTTPFlow, tag: str) -> None:
        resp = flow.response
        if not resp or not resp.content or len(resp.content) > 4000:
            return
        try:
            preview = " ".join((resp.get_text(strict=False) or "").split())[:300]
            if preview:
                _line(f"{tag} BODY {preview}")
        except Exception:
            pass

    def _mock_facebook(self, flow: http.HTTPFlow) -> bool:
        """Retourne True si la requête a été mockée (ne pas forwarder)."""
        path = flow.request.path or ""
        host = _host(flow)

        # Config app Waze : GET /v2.2/343050668156?fields=...
        if WAZE_FB_APP_ID in path and flow.request.method == "GET":
            body = json.dumps(FB_APP_OK).encode()
            flow.response = http.Response.make(
                200,
                body,
                {"Content-Type": "application/json; charset=utf-8"},
            )
            flow._waze_mocked = True  # type: ignore[attr-defined]
            _line(f"FB   MOCK 200 app config {WAZE_FB_APP_ID}")
            return True

        # Events / logging : POST vers graph → ack vide
        if flow.request.method == "POST" and (
            "/activities" in path
            or "/importantForAccuracy" in path
            or "app_events" in path
            or path.rstrip("/").endswith(WAZE_FB_APP_ID)
        ):
            flow.response = http.Response.make(
                200,
                b'{"success":true}',
                {"Content-Type": "application/json"},
            )
            flow._waze_mocked = True  # type: ignore[attr-defined]
            _line(f"FB   MOCK 200 POST {path[:80]}")
            return True

        # Autres GET graph vers cet app → objet minimal
        if "graph.facebook.com" in host and WAZE_FB_APP_ID in path:
            flow.response = http.Response.make(
                200,
                json.dumps({"id": WAZE_FB_APP_ID, "name": "Waze"}).encode(),
                {"Content-Type": "application/json"},
            )
            flow._waze_mocked = True  # type: ignore[attr-defined]
            _line(f"FB   MOCK 200 generic {path[:80]}")
            return True

        return False

    def _serve_cert(self, flow: http.HTTPFlow) -> None:
        path = (flow.request.path or "/").split("?", 1)[0]

        def _file(name: str, ctype: str):
            return (ctype, (CERT_DIR / name).read_bytes())

        mapping = {
            "/": ("text/html; charset=utf-8", IOS6_HTML.encode("utf-8")),
            "/ios6": ("text/html; charset=utf-8", IOS6_HTML.encode("utf-8")),
            "/ModernCARoots-iOS6.mobileconfig": _file(
                "ModernCARoots-iOS6.mobileconfig", "application/x-apple-aspen-config"
            ),
            "/mitmproxy-ca.mobileconfig": _file(
                "mitmproxy-ca.mobileconfig", "application/x-apple-aspen-config"
            ),
            "/mitmproxy-ca.der.cer": _file(
                "mitmproxy-ca.der.cer", "application/x-x509-ca-cert"
            ),
            "/mitmproxy-ca.cer": _file(
                "mitmproxy-ca.cer", "application/x-x509-ca-cert"
            ),
        }
        key = path
        if path.startswith("/cert/"):
            key = "/" + path.split("/")[-1]
        if key not in mapping:
            key = "/"
        ctype, body = mapping[key]
        flow.response = http.Response.make(200, body, {"Content-Type": ctype})
        _line(f"CERT served {path}")


addons = [WazeIOS6()]
