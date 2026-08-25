#!/usr/bin/env python3
"""Génère les MP3 de guidage français (gTTS) pour Waze 2.4 Prompts.Name=fra."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENG = ROOT / "mitm" / "fake-resources" / "resources" / "sounds" / "1.0" / "eng"
FRA = ROOT / "mitm" / "fake-resources" / "resources" / "sounds" / "1.0" / "fra"
LANG_SRC = ROOT / "mitm" / "fake-resources" / "resources" / "langs" / "lang.fra"
LANG_DST = ROOT / "mitm" / "fake-resources" / "langs" / "lang.fra"

# Noms de fichiers = stems GPL (roadmap_prompts / navigate).
PHRASES = {
    "Arrive": "Vous êtes arrivé",
    "TurnLeft": "Tournez à gauche",
    "TurnRight": "Tournez à droite",
    "KeepLeft": "Serrez à gauche",
    "KeepRight": "Serrez à droite",
    "Straight": "Continuez tout droit",
    "Roundabout": "Au rond-point",
    "Exit": "Prenez la sortie",
    "ExitLeft": "Sortez à gauche",
    "ExitRight": "Sortez à droite",
    "AndThen": "puis",
    "within": "dans",
    "ApproachAccident": "Attention, accident",
    "ApproachTraffic": "Attention, trafic",
    "ApproachHazard": "Attention, danger",
    "Marked": "indiquée",
    "First": "première",
    "Second": "deuxième",
    "Third": "troisième",
    "Fourth": "quatrième",
    "Fifth": "cinquième",
    "Sixth": "sixième",
    "Seventh": "septième",
    "200": "200 mètres",
    "400": "400 mètres",
    "800": "800 mètres",
    "1000": "1 kilomètre",
    "1500": "1 kilomètre 500",
    "400meters": "400 mètres",
    "1000meters": "1 kilomètre",
    "1500meters": "1 kilomètre 500",
    "StartDrive": "En route",
    "StartDrive1": "C'est parti",
    "StartDrive2": "Allons-y",
    "StartDrive3": "On y va",
    "StartDrive4": "En avant",
    "StartDrive5": "Direction",
    "StartDrive6": "C'est parti, on y va",
    "StartDrive7": "En route",
    "StartDrive8": "Allons-y",
    "StartDrive9": "C'est parti",
    "TickerPoints": "points",
}


def _gtts_mp3(text: str, dest: Path) -> None:
    from gtts import gTTS

    tts = gTTS(text=text, lang="fr", slow=False)
    tts.save(str(dest))


def main() -> int:
    FRA.mkdir(parents=True, exist_ok=True)
    if LANG_SRC.is_file():
        LANG_DST.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(LANG_SRC, LANG_DST)
        fr_stub = ROOT / "mitm" / "fake-resources" / "langs" / "lang.fr"
        shutil.copy2(LANG_SRC, fr_stub)

    click_src = ENG / "click.mp3"
    if click_src.is_file():
        shutil.copy2(click_src, FRA / "click.mp3")
        shutil.copy2(click_src, FRA / "click")

    try:
        import gtts  # noqa: F401
    except ImportError:
        print("pip install gTTS  (requis pour les voix françaises)", file=sys.stderr)
        return 1

    for stem, phrase in PHRASES.items():
        mp3 = FRA / f"{stem}.mp3"
        print(f"  TTS {stem}: {phrase}", flush=True)
        _gtts_mp3(phrase, mp3)
        bare = FRA / stem
        shutil.copy2(mp3, bare)
        if mp3.stat().st_size < 400:
            print(f"trop petit: {mp3}", file=sys.stderr)
            return 1
    print(f"OK {len(PHRASES)} prompts -> {FRA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
