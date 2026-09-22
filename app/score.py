"""Reading a score's ABC well enough to tell a usable score from a broken one.

A score plan is text the model writes token by token, and at high temperature it can
lose the thread: garbled voice headers, no vocal part, a single bar.  Such a score
renders into something that is not the song, so it is caught here instead.
"""
from __future__ import annotations

import re

KEY = re.compile(r"^K:\s*\S", re.M)
VOICE = re.compile(r"^V:\s*(\S+)")
HEADER = re.compile(r"^[A-Za-z]:")
CHORD = re.compile(r'"[A-G][#b]?[^"\s]*"')
COLLAPSE = re.compile(r"([^\w\s])\1{7,}")
MIN_BARS = 4


def estimate(abc: str) -> dict | None:
    """How long the score says the music is: bars, tempo, and the seconds they imply.

    Used to check a transcription against the recording it came from. A score whose
    tempo is wrong describes more or less music than the recording holds, and a
    cover follows the score, so it plays at that tempo.
    """
    if not abc:
        return None
    meter = re.search(r"^M:(\d+)/(\d+)", abc, re.M)
    beats = int(meter.group(1)) if meter else 4
    tempo = re.search(r"^Q:1/4=(\d+)", abc, re.M)
    bpm = int(tempo.group(1)) if tempo else 120
    totals: dict[str, int] = {}
    voice = None
    for raw in abc.split("\n"):
        line = raw.strip()
        if line.startswith("V:"):
            voice = line[2:].strip().split()[0] if line[2:].strip() else None
            continue
        if not line or line[0] == "%" or HEADER.match(line) or not voice:
            continue
        totals[voice] = totals.get(voice, 0) + line.count("|")
    bars = max(totals.values()) if totals else 0
    if not bars or not bpm:
        return None
    return {"bars": bars, "bpm": bpm, "seconds": round(bars * beats * 60 / bpm, 1)}


def vocal_bars(abc: str, voice_name: str = "Vocal") -> list[str]:
    """The bars of one voice, the Vocal voice unless told otherwise, in order."""
    bars, voice = [], None
    for raw in (abc or "").splitlines():
        line = raw.strip()
        match = VOICE.match(line)
        if match:
            voice = match.group(1)
            continue
        if voice != voice_name or not line or line.startswith("%") or HEADER.match(line):
            continue
        bars.extend(bar for bar in line.split("|") if bar.strip())
    return bars


def problems(abc: str, need_chords: bool = True, instrumental: bool = False) -> list[str]:
    """What makes this score unusable, in words a person can act on.  Empty when fine.
    An instrumental plan keeps a Vocal voice of rests that carries the chords, and
    puts its melody in an Ins voice; either one will do."""
    found = []
    if COLLAPSE.search(abc or ""):
        found.append("repetitive token collapse")
    if not KEY.search(abc or ""):
        found.append("no key")
    bars = vocal_bars(abc)
    if instrumental and not bars:
        bars = vocal_bars(abc, "Ins")
    if not bars:
        found.append("no instrument part" if instrumental else "no vocal part")
    elif len(bars) < MIN_BARS:
        found.append(f"only {len(bars)} bar{'s' if len(bars) != 1 else ''}")
    if need_chords and bars and not any(CHORD.search(bar) for bar in bars):
        found.append("no chord symbols")
    return found
