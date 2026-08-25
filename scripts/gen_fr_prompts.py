#!/usr/bin/env python3
"""Génère les MP3 de guidage (gTTS) pour Waze 2.4 — packs fra et eng séparés."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENG = ROOT / "mitm" / "fake-resources" / "resources" / "sounds" / "1.0" / "eng"
FRA = ROOT / "mitm" / "fake-resources" / "resources" / "sounds" / "1.0" / "fra"
LANG_FRA = ROOT / "mitm" / "fake-resources" / "resources" / "langs" / "lang.fra"
LANG_ENG = ROOT / "mitm" / "fake-resources" / "resources" / "langs" / "lang.eng"

PHRASES_FR = {
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

PHRASES_EN = {
    "Arrive": "You have arrived",
    "TurnLeft": "Turn left",
    "TurnRight": "Turn right",
    "KeepLeft": "Keep left",
    "KeepRight": "Keep right",
    "Straight": "Continue straight",
    "Roundabout": "At the roundabout",
    "Exit": "Take the exit",
    "ExitLeft": "Exit left",
    "ExitRight": "Exit right",
    "AndThen": "then",
    "within": "in",
    "ApproachAccident": "Accident ahead",
    "ApproachTraffic": "Traffic ahead",
    "ApproachHazard": "Hazard ahead",
    "Marked": "marked",
    "First": "first",
    "Second": "second",
    "Third": "third",
    "Fourth": "fourth",
    "Fifth": "fifth",
    "Sixth": "sixth",
    "Seventh": "seventh",
    "200": "200 meters",
    "400": "400 meters",
    "800": "800 meters",
    "1000": "1 kilometer",
    "1500": "1.5 kilometers",
    "400meters": "400 meters",
    "1000meters": "1 kilometer",
    "1500meters": "1.5 kilometers",
    "StartDrive": "Let's go",
    "StartDrive1": "On our way",
    "StartDrive2": "Here we go",
    "StartDrive3": "Let's go",
    "StartDrive4": "Off we go",
    "StartDrive5": "Now departing",
    "StartDrive6": "Let's get going",
    "StartDrive7": "Let's go",
    "StartDrive8": "On our way",
    "StartDrive9": "Here we go",
    "TickerPoints": "points",
}


def _gtts_mp3(text: str, dest: Path, lang: str) -> None:
    import tempfile
    import time

    from gtts import gTTS

    tts = gTTS(text=text, lang=lang, slow=False)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    try:
        tts.save(tmp)
        last_err: Exception | None = None
        for _ in range(5):
            try:
                shutil.copy2(tmp, dest)
                last_err = None
                break
            except OSError as e:
                last_err = e
                time.sleep(0.35)
        if last_err is not None:
            print(f"  skip {dest.name}: {last_err}", file=sys.stderr)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def sync_lang_files() -> None:
    """lang.eng = clés anglaises (identité). Copies sous langs/ pour le GET catcher."""
    if LANG_FRA.is_file():
        for dest in (
            ROOT / "mitm" / "fake-resources" / "langs" / "lang.fra",
            ROOT / "mitm" / "fake-resources" / "langs" / "lang.fr",
        ):
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(LANG_FRA, dest)
        keys: list[str] = []
        for line in LANG_FRA.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#") or "=" not in line:
                continue
            keys.append(line.split("=", 1)[0])
        lines = [
            "# English UI — roadmap_lang_get() keys, identity mapping.",
            "lang=English",
            "RTL=No",
        ]
        seen = {"lang", "RTL"}
        for k in keys:
            if k in seen:
                continue
            seen.add(k)
            lines.append(f"{k}={k}")
        text = "\n".join(lines) + "\n"
        for dest in (
            LANG_ENG,
            ROOT / "mitm" / "fake-resources" / "langs" / "lang.eng",
        ):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")


def _write_pack(dest: Path, phrases: dict[str, str], lang: str, force: bool) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for stem, phrase in phrases.items():
        mp3 = dest / f"{stem}.mp3"
        if mp3.is_file() and mp3.stat().st_size > 400 and not force:
            bare = dest / stem
            if not bare.is_file():
                shutil.copy2(mp3, bare)
            continue
        print(f"  TTS {lang}/{stem}: {phrase}", flush=True)
        _gtts_mp3(phrase, mp3, lang)
        try:
            shutil.copy2(mp3, dest / stem)
        except OSError:
            pass
        if not mp3.is_file() or mp3.stat().st_size < 400:
            print(f"trop petit ou absent: {mp3}", file=sys.stderr)
            continue
        n += 1
    print(f"OK {lang}: {n} nouveaux, {len(phrases)} total -> {dest}")
    return 0


def main() -> int:
    args = set(sys.argv[1:])
    force = "--force" in args
    do_fr = "--en" not in args
    do_en = "--fr" not in args
    sync_lang_files()
    if "--langs-only" in args:
        print("OK lang.fra / lang.eng")
        return 0

    try:
        import gtts  # noqa: F401
    except ImportError:
        print("pip install gTTS  (voix). lang.fra / lang.eng déjà synchronisés.", file=sys.stderr)
        return 0 if "--langs-only" in args else 1

    if do_fr:
        click_src = ENG / "click.mp3"
        if click_src.is_file():
            shutil.copy2(click_src, FRA / "click.mp3")
            shutil.copy2(click_src, FRA / "click")
        if _write_pack(FRA, PHRASES_FR, "fr", force):
            return 1
    if do_en:
        click_src = FRA / "click.mp3"
        if not click_src.is_file():
            click_src = ENG / "click.mp3"
        if click_src.is_file():
            shutil.copy2(click_src, ENG / "click.mp3")
            shutil.copy2(click_src, ENG / "click")
        if _write_pack(ENG, PHRASES_EN, "en", force):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
