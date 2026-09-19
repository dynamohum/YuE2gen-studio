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
MIN_BARS = 4


def vocal_bars(abc: str) -> list[str]:
    """The bars of the Vocal voice, in order."""
    bars, voice = [], None
    for raw in (abc or "").splitlines():
        line = raw.strip()
        match = VOICE.match(line)
        if match:
            voice = match.group(1)
            continue
        if voice != "Vocal" or not line or line.startswith("%") or HEADER.match(line):
            continue
        bars.extend(bar for bar in line.split("|") if bar.strip())
    return bars


def problems(abc: str, need_chords: bool = True) -> list[str]:
    """What makes this score unusable, in words a person can act on.  Empty when fine."""
    found = []
    if not KEY.search(abc or ""):
        found.append("no key")
    bars = vocal_bars(abc)
    if not bars:
        found.append("no vocal part")
    elif len(bars) < MIN_BARS:
        found.append(f"only {len(bars)} bar{'s' if len(bars) != 1 else ''}")
    if need_chords and bars and not any(CHORD.search(bar) for bar in bars):
        found.append("no chord symbols")
    return found
