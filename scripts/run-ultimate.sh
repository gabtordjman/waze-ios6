#!/usr/bin/env python3
# CATCHER_REV=reg-proto202-20260816aa
"""Waze iOS6 catcher launcher."""
from __future__ import annotations

import atexit
import os
import signal
import subprocess
import sys
from pathlib import Path

CATCHER_REV = "reg-proto202-20260816aa"

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CATCHER = HERE / "rts_catcher_min.py"
DEAD_IP = "75.101.158.200"

print(f"CATCHER_REV={CATCHER_REV}  Register→LoginSuccessful fields (proto 202)", flush=True)
print("Freemap user,pass abandoned (no public pcap; GPL 150 ≠ IPA 202).", flush=True)
print("Succès = Login POST ou ★ GET tiles", flush=True)

if not CATCHER.is_file():
    sys.exit(f"ERREUR: {CATCHER} introuvable")

os.environ["CATCHER_CTYPE"] = "binary/octet-stream"
os.environ.setdefault("CATCHER_HTTP_PORT", "80")
os.environ.setdefault("CATCHER_HTTPS_PORT", "443")
os.environ.setdefault("CATCHER_DRAIN_SEC", "0.15")
os.environ.setdefault("CATCHER_HTTP_VER", "1.1")
os.environ.setdefault(
    "OPENSSL_CONF", str(ROOT / "mitm" / "certs" / "tls" / "openssl-ios6.cnf")
)

phone = os.environ.get("PHONE", "192.168.1.60")
# Both iPhones on the LAN (3GS .60 / 4S .61) — comma-separated
phones = [
    p.strip()
    for p in os.environ.get("PHONES", f"{phone},192.168.1.61").split(",")
    if p.strip()
]
phones = list(dict.fromkeys(phones))  # unique, keep order

pc_ip = os.environ.get("PC_IP", "").strip()
if not pc_ip:
    try:
        pc_ip = subprocess.check_output(["hostname", "-I"], text=True).split()[0]
    except Exception:
        pc_ip = "192.168.1.191"
os.environ["PC_IP"] = pc_ip

print(f"PC={pc_ip}  phones={phones}", flush=True)
print("'Searching network' = Realtime PAS loggé (tuiles après login).", flush=True)
print("Patch: scp scripts/iphone-patch-4.sh root@192.168.1.60:/tmp/ && ssh … sh /tmp/iphone-patch-4.sh", flush=True)
print(flush=True)

# Free :80 / :443 — leftover catcher / nginx causes Errno 98
http_port = int(os.environ.get("CATCHER_HTTP_PORT", "80"))
https_port = int(os.environ.get("CATCHER_HTTPS_PORT", "443"))


def _free_port(port: int) -> None:
    """Kill whatever is listening on TCP port (needs root)."""
    killed = False
    for cmd in (
        ["fuser", "-k", f"{port}/tcp"],
        ["fuser", "-k", "-n", "tcp", str(port)],
    ):
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            killed = True
            break
        except FileNotFoundError:
            continue
    if not killed:
        try:
            out = subprocess.check_output(
                ["ss", "-ltnp", f"sport = :{port}"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            import re

            for m in re.finditer(r"pid=(\d+)", out):
                pid = m.group(1)
                subprocess.run(
                    ["kill", "-9", pid],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                print(f"  killed pid {pid} on :{port}", flush=True)
                killed = True
        except Exception:
            pass
    # brief wait for TIME_WAIT / kernel release
    import time as _time

    _time.sleep(0.4)
    print(f"  port :{port} {'libéré' if killed else 'check (fuser/ss)'}", flush=True)


print("Libération ports catcher…", flush=True)
_free_port(http_port)
_free_port(https_port)

# If ServerConfig is ignored, IPA still hits DEAD_IP:80 — steal those packets.
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
    except Exception as exc:
        print(f"ip_forward skip: {exc}", flush=True)
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
            ok1 = _iptables(
                [
                    "-t", "nat", "-A", "PREROUTING",
                    "-s", ph, "-d", DEAD_IP, "-p", "tcp", "--dport", dport,
                    "-j", "DNAT", "--to-destination", f"{pc_ip}:{local}",
                ]
            )
            ok2 = _iptables(
                [
                    "-t", "nat", "-A", "POSTROUTING",
                    "-s", ph, "-d", pc_ip, "-p", "tcp", "--dport", local,
                    "-j", "MASQUERADE",
                ]
            )
            if ok1 and ok2:
                ok_any = True
                print(f"DNAT OK: {ph} → {DEAD_IP}:{dport} → {pc_ip}:{local}", flush=True)
    dnat_ok = ok_any
    if not dnat_ok:
        print("DNAT échec (lance en root).", flush=True)


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

tcpdump_proc = None
pcap = ROOT / "logs" / "ultimate-latest.pcap"


def _stop_tcpdump(*_a):
    if tcpdump_proc and tcpdump_proc.poll() is None:
        tcpdump_proc.send_signal(signal.SIGINT)
        try:
            tcpdump_proc.wait(timeout=3)
        except Exception:
            tcpdump_proc.kill()


def _pcap_summary() -> None:
    _stop_tcpdump()
    if not pcap.is_file():
        print("pcap: absent", flush=True)
        return
    print(f"\n=== pcap {pcap} ===", flush=True)
    for label, filt in (
        ("ALL", ""),
        ("port 80", "tcp port 80"),
        ("443", "tcp port 443"),
        ("53 DNS", "udp port 53 or tcp port 53"),
        ("75.101", f"host {DEAD_IP}"),
        ("to PC", f"host {pc_ip}"),
        ("RST", "tcp[tcpflags] & tcp-rst != 0"),
    ):
        try:
            cmd = ["tcpdump", "-nn", "-r", str(pcap)]
            if filt:
                cmd.append(filt)
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            lines = [
                ln.decode("latin1", errors="replace")
                for ln in out.splitlines()
                if ln.strip() and not ln.lower().startswith(b"reading from file")
            ]
            print(f"  {label}: {len(lines)}", flush=True)
            if label in ("ALL", "to PC", "port 80", "443") and lines:
                for ln in lines[:15]:
                    print(f"    {ln}", flush=True)
        except subprocess.CalledProcessError as exc:
            err = (exc.output or b"").decode("latin1", errors="replace")[:200]
            print(f"  {label}: ERREUR {err}", flush=True)
        except Exception as exc:
            print(f"  {label}: ERREUR {exc}", flush=True)


try:
    logs = ROOT / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    iface = os.environ.get("IFACE", "").strip()
    if not iface:
        try:
            out = subprocess.check_output(["ip", "route", "get", phones[0]], text=True)
            parts = out.split()
            iface = parts[parts.index("dev") + 1] if "dev" in parts else "wlp3s0"
        except Exception:
            iface = "wlp3s0"
    # Fresh pcap each run
    if pcap.is_file():
        pcap.unlink()
    host_filt = " or ".join(f"host {p}" for p in phones)
    tcpdump_proc = subprocess.Popen(
        [
            "tcpdump",
            "-i",
            iface,
            "-s",
            "0",
            "-U",
            "-w",
            str(pcap),
            # ALL traffic from phones (not only 80/443) — find where Realtime goes
            f"({host_filt}) or host {DEAD_IP}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"tcpdump pid={tcpdump_proc.pid} iface={iface} pcap={pcap}", flush=True)
    print("pcap = TOUT le trafic des iPhones (pas seulement :80/:443)", flush=True)
except Exception as exc:
    print(f"tcpdump skip: {exc}", flush=True)

signal.signal(signal.SIGINT, lambda *_: (_pcap_summary(), _clear_dnat(), sys.exit(0)))
signal.signal(signal.SIGTERM, lambda *_: (_pcap_summary(), _clear_dnat(), sys.exit(0)))

try:
    sys.argv[0] = str(CATCHER)
    # Force matching ctype / drain for this rev
    os.environ["CATCHER_REV_FORCE"] = CATCHER_REV
    code = compile(CATCHER.read_text(encoding="utf-8"), str(CATCHER), "exec")
    exec(code, {"__name__": "__main__", "__file__": str(CATCHER)})
finally:
    _pcap_summary()
    _clear_dnat()
