#!/usr/bin/env python3
# CATCHER_REV=cycle-20260816i
# Launcher: cycle 6 GetGeo variants (plain/gzip, LF/CRLF, geo5/bare)
"""Waze iOS6 catcher launcher."""
from __future__ import annotations

import atexit
import os
import signal
import subprocess
import sys
from pathlib import Path

CATCHER_REV = "cycle-20260816i"

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CATCHER = HERE / "rts_catcher_min.py"
DEAD_IP = "75.101.158.200"

print(
    f"CATCHER_REV={CATCHER_REV}  MODE=cycle (6 variantes GetGeo)",
    flush=True,
)
print(
    "Chaque ouverture Waze teste la variante suivante. Succès = ★ GET sur :80",
    flush=True,
)

if not CATCHER.is_file():
    sys.exit(f"ERREUR: {CATCHER} introuvable — copie aussi rts_catcher_min.py")

os.environ["CATCHER_MODE"] = "cycle"
os.environ["CATCHER_BODY"] = "cycle"
os.environ["CATCHER_NL"] = "lf"
os.environ["CATCHER_CTYPE"] = "binary/octet-stream"
os.environ.setdefault("CATCHER_HTTP_PORT", "80")
os.environ.setdefault("CATCHER_HTTPS_PORT", "443")
os.environ.setdefault("CATCHER_DRAIN_SEC", "5.0")
os.environ.setdefault("CATCHER_HTTP_VER", "1.0")
os.environ.setdefault(
    "OPENSSL_CONF", str(ROOT / "mitm" / "certs" / "tls" / "openssl-ios6.cnf")
)

phone = os.environ.get("PHONE", "192.168.1.60")
pc_ip = os.environ.get("PC_IP", "").strip()
if not pc_ip:
    try:
        pc_ip = subprocess.check_output(["hostname", "-I"], text=True).split()[0]
    except Exception:
        pc_ip = "192.168.1.191"
os.environ["PC_IP"] = pc_ip

print(f"PC={pc_ip}  phone={phone}", flush=True)
print("Sur le téléphone (PuTTY), AVANT de rouvrir Waze :", flush=True)
print(
    "  APP=/var/mobile/Applications/8047C930-9816-413D-8F01-98BEB2775E5A",
    flush=True,
)
print('  grep -rn "75.101" "$APP" 2>/dev/null | head', flush=True)
print('  find "$APP" -name preferences -o -name "session*" 2>/dev/null', flush=True)
print('  rm -f "$APP"/Documents/preferences "$APP"/Documents/session* 2>/dev/null', flush=True)
print('  rm -f "$APP"/Library/Preferences/com.waze*.plist 2>/dev/null', flush=True)
print("  killall -9 Waze", flush=True)
print("Puis rouvre Waze — succès = GET lang.conf ou lang.eng sur :80", flush=True)
print(flush=True)

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
    # Idempotent: delete then add
    for args in (
        [
            "-t",
            "nat",
            "-D",
            "PREROUTING",
            "-s",
            phone,
            "-d",
            DEAD_IP,
            "-p",
            "tcp",
            "--dport",
            "80",
            "-j",
            "DNAT",
            "--to-destination",
            f"{pc_ip}:80",
        ],
        [
            "-t",
            "nat",
            "-D",
            "POSTROUTING",
            "-s",
            phone,
            "-d",
            pc_ip,
            "-p",
            "tcp",
            "--dport",
            "80",
            "-j",
            "MASQUERADE",
        ],
    ):
        _iptables(args)
    ok1 = _iptables(
        [
            "-t",
            "nat",
            "-A",
            "PREROUTING",
            "-s",
            phone,
            "-d",
            DEAD_IP,
            "-p",
            "tcp",
            "--dport",
            "80",
            "-j",
            "DNAT",
            "--to-destination",
            f"{pc_ip}:80",
        ]
    )
    ok2 = _iptables(
        [
            "-t",
            "nat",
            "-A",
            "POSTROUTING",
            "-s",
            phone,
            "-d",
            pc_ip,
            "-p",
            "tcp",
            "--dport",
            "80",
            "-j",
            "MASQUERADE",
        ]
    )
    dnat_ok = ok1 and ok2
    if dnat_ok:
        print(f"DNAT OK: {phone} → {DEAD_IP}:80  redirigé vers {pc_ip}:80", flush=True)
    else:
        print(
            "DNAT échec (lance en root). Si ServerConfig ignoré, lang.conf part vers IP morte.",
            flush=True,
        )


def _clear_dnat() -> None:
    if not dnat_ok:
        return
    _iptables(
        [
            "-t",
            "nat",
            "-D",
            "PREROUTING",
            "-s",
            phone,
            "-d",
            DEAD_IP,
            "-p",
            "tcp",
            "--dport",
            "80",
            "-j",
            "DNAT",
            "--to-destination",
            f"{pc_ip}:80",
        ]
    )
    _iptables(
        [
            "-t",
            "nat",
            "-D",
            "POSTROUTING",
            "-s",
            phone,
            "-d",
            pc_ip,
            "-p",
            "tcp",
            "--dport",
            "80",
            "-j",
            "MASQUERADE",
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
        ("port 80", "tcp port 80"),
        ("75.101", f"host {DEAD_IP}"),
        ("RST", "tcp[tcpflags] & tcp-rst != 0"),
        ("FIN", "tcp[tcpflags] & tcp-fin != 0"),
        ("443", "tcp port 443"),
    ):
        try:
            out = subprocess.check_output(
                ["tcpdump", "-nn", "-r", str(pcap), filt],
                stderr=subprocess.STDOUT,
            )
            n = sum(
                1
                for ln in out.splitlines()
                if ln.strip() and not ln.lower().startswith(b"reading from file")
            )
            print(f"  {label}: {n}", flush=True)
            if label in ("port 80", "75.101") and n:
                shown = 0
                for ln in out.decode("latin1", errors="replace").splitlines():
                    if not ln.strip() or ln.lower().startswith("reading from file"):
                        continue
                    print(f"    {ln}", flush=True)
                    shown += 1
                    if shown >= 12:
                        break
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
            out = subprocess.check_output(["ip", "route", "get", phone], text=True)
            parts = out.split()
            iface = parts[parts.index("dev") + 1] if "dev" in parts else "wlp3s0"
        except Exception:
            iface = "wlp3s0"
    # Fresh pcap each run
    if pcap.is_file():
        pcap.unlink()
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
            f"(host {phone} and (port 443 or port 80)) or host {DEAD_IP}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"tcpdump pid={tcpdump_proc.pid} iface={iface} pcap={pcap}", flush=True)
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
