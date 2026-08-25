"""Configuration partagée lab LAN / VPS public.

Charge `.env` à la racine du dépôt s'il existe (non versionné).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LAB_IP = "192.168.1.191"
_ENV_LOADED = False


def load_dotenv(path: Path | None = None) -> None:
    """Charge KEY=VALUE depuis .env (sans écraser l'environnement déjà défini)."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    env_path = path or (ROOT / ".env")
    if not env_path.is_file():
        _ENV_LOADED = True
        return
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val
    _ENV_LOADED = True


load_dotenv()


def mode() -> str:
    return os.environ.get("WAZE_MODE", "lab").strip().lower()


def is_vps() -> bool:
    return mode() == "vps"


def server_ip() -> str:
    """IP annoncée aux clients (BASE URL, tweak)."""
    for key in ("WAZE_SERVER_IP", "PC_IP"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    try:
        return subprocess.check_output(["hostname", "-I"], text=True).split()[0]
    except Exception:
        return DEFAULT_LAB_IP


def base_url() -> str:
    return f"http://{server_ip()}"


def apply_to_environ() -> None:
    """Expose WAZE_SERVER_IP et PC_IP pour scripts legacy."""
    load_dotenv()
    ip = server_ip()
    os.environ.setdefault("WAZE_SERVER_IP", ip)
    os.environ.setdefault("PC_IP", ip)
