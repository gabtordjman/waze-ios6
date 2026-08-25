#!/usr/bin/env python3
"""Génère le pack MP3 Minimal (prompts Waze 2.4) sous fake-resources."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "mitm" / "fake-resources" / "resources" / "sounds" / "1.0" / "eng"

# MPEG-1 Layer III, 32 kbps, 44.1 kHz, mono — frame valide, non vide.
_MP3 = bytes.fromhex(
    "fff330c400000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
)

PROMPTS = [
    "click",
    "within",
    "200",
    "400",
    "400meters",
    "800",
    "1000",
    "1000meters",
    "1500",
    "1500meters",
    "TurnLeft",
    "TurnRight",
    "KeepLeft",
    "KeepRight",
    "ExitLeft",
    "ExitRight",
    "Straight",
    "Roundabout",
    "Exit",
    "First",
    "Second",
    "Third",
    "Fourth",
    "Fifth",
    "Sixth",
    "Seventh",
    "AndThen",
    "StartDrive",
    "StartDrive1",
    "StartDrive2",
    "StartDrive3",
    "StartDrive4",
    "StartDrive5",
    "StartDrive6",
    "StartDrive7",
    "StartDrive8",
    "StartDrive9",
    "TickerPoints",
    "Arrive",
    "Marked",
    "ApproachAccident",
    "ApproachHazard",
    "ApproachTraffic",
]

SPOKEN = {
    "click": "ready",
    "within": "in",
    "200": "200 meters",
    "400": "400 meters",
    "400meters": "400 meters",
    "800": "800 meters",
    "1000": "1 kilometer",
    "1000meters": "1 kilometer",
    "1500": "1.5 kilometers",
    "1500meters": "1.5 kilometers",
    "TurnLeft": "turn left",
    "TurnRight": "turn right",
    "KeepLeft": "keep left",
    "KeepRight": "keep right",
    "ExitLeft": "exit left",
    "ExitRight": "exit right",
    "Straight": "continue straight",
    "Roundabout": "roundabout",
    "Exit": "exit",
    "First": "first exit",
    "Second": "second exit",
    "Third": "third exit",
    "Fourth": "fourth exit",
    "Fifth": "fifth exit",
    "Sixth": "sixth exit",
    "Seventh": "seventh exit",
    "AndThen": "and then",
    "StartDrive": "starting route",
    "StartDrive1": "starting route",
    "StartDrive2": "starting route",
    "StartDrive3": "starting route",
    "StartDrive4": "starting route",
    "StartDrive5": "starting route",
    "StartDrive6": "starting route",
    "StartDrive7": "starting route",
    "StartDrive8": "starting route",
    "StartDrive9": "starting route",
    "TickerPoints": "ready",
    "Arrive": "you have arrived",
    "Marked": "marked",
    "ApproachAccident": "accident ahead",
    "ApproachHazard": "hazard ahead",
    "ApproachTraffic": "traffic ahead",
}


def _sapi_wav(text: str, wav: Path) -> bool:
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{wav.as_posix().replace('/', '\\\\')}'); "
        f"$s.Speak('{text.replace(chr(39), '')}'); "
        "$s.Dispose();"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            timeout=20,
        )
        return r.returncode == 0 and wav.is_file() and wav.stat().st_size > 100
    except Exception:
        return False


def _espeak_wav(text: str, wav: Path) -> bool:
    for cmd in (("espeak", "-w", str(wav), text), ("espeak-ng", "-w", str(wav), text)):
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=20)
            if r.returncode == 0 and wav.is_file() and wav.stat().st_size > 100:
                return True
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return False


def _make_wav(text: str, wav: Path) -> bool:
    if sys.platform == "win32" and _sapi_wav(text, wav):
        return True
    return _espeak_wav(text, wav)


def _ffmpeg_mp3(wav: Path, mp3: Path) -> bool:
    for cmd in ("ffmpeg", "ffmpeg.exe"):
        try:
            r = subprocess.run(
                [cmd, "-y", "-i", str(wav), "-codec:a", "libmp3lame", "-q:a", "7", str(mp3)],
                capture_output=True,
                timeout=20,
            )
            if r.returncode == 0 and mp3.is_file() and mp3.stat().st_size > 100:
                return True
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return False


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_tmp.wav"
    spoken = 0
    use_voice = os.environ.get("WAZE_SPOKEN_PROMPTS") == "1"
    for name in PROMPTS:
        dest = OUT / f"{name}.mp3"
        text = SPOKEN.get(name, name)
        if use_voice and _make_wav(text, tmp) and _ffmpeg_mp3(tmp, dest):
            spoken += 1
        else:
            dest.write_bytes(_MP3 * 8)
        bare = OUT / name
        shutil.copyfile(dest, bare)
    if tmp.exists():
        tmp.unlink()
    print(f"prompts={len(PROMPTS)} spoken_mp3={spoken} dir={OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
