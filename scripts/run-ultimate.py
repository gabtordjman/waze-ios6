#!/usr/bin/env python3
"""Waze iOS6 — lance le catcher RTS mock."""
from __future__ import annotations

import atexit
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

CATCHER_REV = "login-gpl11-min-20260824b"

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CATCHER = HERE / "rts_catcher_min.py"
DEAD_IP = "75.101.158.200"
DNS_SCRIPT = HERE / "run-dns-sinkhole.sh"

if not CATCHER.is_file():
    sys.exit(f"ERREUR: {CATCHER} introuvable")

os.environ["CATCHER_CTYPE"] = "binary/octet-stream"
os.environ.setdefault("CATCHER_HTTP_PORT", "80")
os.environ.setdefault("CATCHER_HTTPS_PORT", "443")
os.environ.setdefault("CATCHER_HTTP_VER", "1.1")
os.environ.setdefault(
    "OPENSSL_CONF", str(ROOT / "mitm" / "certs" / "tls" / "openssl-ios6.cnf")
)

phones = [
    p.strip()
    for p in os.environ.get("PHONES", "192.168.1.60,192.168.1.61").split(",")
    if p.strip()
]
phones = list(dict.fromkeys(phones))

pc_ip = os.environ.get("PC_IP", "").strip()
if not pc_ip:
    try:
        pc_ip = subprocess.check_output(["hostname", "-I"], text=True).split()[0]
    except Exception:
        pc_ip = "192.168.1.191"
os.environ["PC_IP"] = pc_ip

http_port = int(os.environ.get("CATCHER_HTTP_PORT", "80"))
https_port = int(os.environ.get("CATCHER_HTTPS_PORT", "443"))
MY_PID = os.getpid()

print(f"CATCHER_REV={CATCHER_REV}  pid={MY_PID}", flush=True)
print(f"PC={pc_ip}  phones={phones}", flush=True)


def _stop_our_catcher() -> None:
    """Stop only our Python catcher — never kill nginx/apache workers on :80."""
    for pat in ("rts_catcher_min.py", "run-ultimate.py"):
        subprocess.run(["pkill", "-9", "-f", pat], check=False)
    time.sleep(0.8)


def _port_owner(port: int) -> str:
    try:
        return subprocess.check_output(
            ["ss", "-ltnp", f"sport = :{port}"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def _ensure_port(port: int) -> None:
    print(f"Port :{port}…", flush=True)
    _stop_our_catcher()
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("0.0.0.0", port))
        print(f"  :{port} OK", flush=True)
        return
    except OSError:
        owner = _port_owner(port)
        print(f"ERREUR: :{port} occupé par un autre service (nginx/apache ?)", flush=True)
        if owner:
            for line in owner.splitlines():
                if "LISTEN" in line:
                    print(f"  {line}", flush=True)
        print("  → sh stop.sh  puis  sudo sh go.sh", flush=True)
        print("  → si nginx: sudo systemctl stop nginx", flush=True)
        sys.exit(1)
    finally:
        probe.close()


_ensure_port(http_port)
_ensure_port(https_port)

if DNS_SCRIPT.is_file() and os.environ.get("SKIP_DNS") != "1":
    subprocess.run(["sh", str(DNS_SCRIPT)], check=False, cwd=str(ROOT))

dnat_ok = False


def _iptables(args: list[str]) -> bool:
    try:
        subprocess.check_call(
            ["iptables", *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _setup_dnat() -> None:
    global dnat_ok
    try:
        Path("/proc/sys/net/ipv4/ip_forward").write_text("1")
    except Exception:
        pass
    ok_any = False
    for ph in phones:
        for dport, local in (("80", "80"), ("443", "443")):
            for args in (
                [
                    "-t", "nat", "-D", "PREROUTING",
                    "-s", ph, "-d", DEAD_IP, "-p", "tcp", "--dport", dport,
                    "-j", "DNAT", "--to-destination", f"{pc_ip}:{local}",
                ],
                [
                    "-t", "nat", "-D", "POSTROUTING",
                    "-s", ph, "-d", pc_ip, "-p", "tcp", "--dport", local,
                    "-j", "MASQUERADE",
                ],
            ):
                _iptables(args)
            if _iptables(
                [
                    "-t", "nat", "-A", "PREROUTING",
                    "-s", ph, "-d", DEAD_IP, "-p", "tcp", "--dport", dport,
                    "-j", "DNAT", "--to-destination", f"{pc_ip}:{local}",
                ]
            ) and _iptables(
                [
                    "-t", "nat", "-A", "POSTROUTING",
                    "-s", ph, "-d", pc_ip, "-p", "tcp", "--dport", local,
                    "-j", "MASQUERADE",
                ]
            ):
                ok_any = True
                print(f"DNAT {ph} → {DEAD_IP}:{dport} → {pc_ip}:{local}", flush=True)
    dnat_ok = ok_any


def _clear_dnat() -> None:
    if not dnat_ok:
        return
    for ph in phones:
        for dport, local in (("80", "80"), ("443", "443")):
            _iptables(
                [
                    "-t", "nat", "-D", "PREROUTING",
                    "-s", ph, "-d", DEAD_IP, "-p", "tcp", "--dport", dport,
                    "-j", "DNAT", "--to-destination", f"{pc_ip}:{local}",
                ]
            )
            _iptables(
                [
                    "-t", "nat", "-D", "POSTROUTING",
                    "-s", ph, "-d", pc_ip, "-p", "tcp", "--dport", local,
                    "-j", "MASQUERADE",
                ]
            )


_setup_dnat()
atexit.register(_clear_dnat)

pcap = ROOT / "logs" / "ultimate-latest.pcap"
tcpdump_proc = None


def _stop_tcpdump() -> None:
    global tcpdump_proc
    if tcpdump_proc and tcpdump_proc.poll() is None:
        tcpdump_proc.send_signal(signal.SIGINT)
        try:
            tcpdump_proc.wait(timeout=3)
        except Exception:
            tcpdump_proc.kill()


def _on_exit(*_a) -> None:
    _stop_tcpdump()
    _clear_dnat()
    sys.exit(0)


signal.signal(signal.SIGINT, _on_exit)
signal.signal(signal.SIGTERM, _on_exit)

try:
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    iface = os.environ.get("IFACE", "wlp3s0")
    if pcap.is_file():
        pcap.unlink()
    filt = " or ".join(f"host {p}" for p in phones)
    tcpdump_proc = subprocess.Popen(
        [
            "tcpdump", "-i", iface, "-s", "0", "-U", "-w", str(pcap),
            f"({filt}) or host {DEAD_IP}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"tcpdump → {pcap}", flush=True)
except Exception as exc:
    print(f"tcpdump skip: {exc}", flush=True)

print("Démarrage catcher…", flush=True)
sys.argv[0] = str(CATCHER)
exec(compile(CATCHER.read_text(encoding="utf-8"), str(CATCHER), "exec"), {
    "__name__": "__main__",
    "__file__": str(CATCHER),
})
