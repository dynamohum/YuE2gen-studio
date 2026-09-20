"""Instrumentals: YuE2 with a LoRA that plans and plays a song with no vocal.

Where a song has lyrics, an instrumental has a structure, in one of three forms
the LoRA was trained on:

    [instrumental]                         YuE2 chooses the sections
    [intro] [verse] [chorus] ...           you choose the sections, YuE2 the lengths
    [intro 0:00-0:15] [verse 0:15-0:45]    you choose both

The LoRA adapts the language model only, so it is loaded on the CLIP side, for
the plan and for the render alike."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

SECTIONS = ("intro", "verse", "pre-chorus", "chorus", "bridge", "outro")
# The LoRA is always held at full strength.
#
# There was a Feel control that loosened it to 0.8, then 0.9, for more movement
# between sections. Measured at real song lengths, any loosening lets the vocal
# back in: at two minutes, 0.90 sang through 94%, 94% and 66% of three renders,
# and 0.95 through 15% of one, while full strength was clean on every seed and
# every length tried. An earlier sweep that looked clean had used one-minute
# renders, which are too short to fail this way.
#
# So the control is gone rather than retuned: its only safe setting was the
# default. Movement is still available through Plan variety, Harmony,
# Interpretation and choosing the sections, none of which risk a vocal.
FEELS = {"steady": 1.0}

# A finished instrumental is judged by how much of it carries a vocal: the share
# of seconds whose separated vocal is above the noise the separation leaves
# behind.  A clean instrumental measures a fraction of a per cent; the take that
# prompted this measured 65%.
VOCAL_FLOOR = 0.01     # RMS below which a second counts as silent
SUNG = 0.10            # share of sung seconds worth telling someone about
BARE = "[instrumental]"
_TAG = re.compile(r"^\[\s*([a-z-]+)(?:\s+(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2}))?\s*\]$")


def normalise(text: str) -> str:
    """The structure as the LoRA expects it, one tag per line, lower case.  Raises
    ValueError with a reason a person can act on."""
    tags = [part for part in re.split(r"\s*\n\s*|(?<=\])\s+(?=\[)", (text or "").strip().lower()) if part]
    if not tags or tags == [BARE]:
        return BARE
    lines, timed, clock = [], None, 0
    for tag in tags:
        match = _TAG.match(tag)
        if not match or match.group(1) not in SECTIONS:
            raise ValueError(f"{tag!r} is not a section. Use {', '.join(SECTIONS)}.")
        has_time = match.group(2) is not None
        if timed is None:
            timed = has_time
        elif timed != has_time:
            raise ValueError("give every section a time, or none of them")
        if has_time:
            start = int(match.group(2)) * 60 + int(match.group(3))
            end = int(match.group(4)) * 60 + int(match.group(5))
            if end <= start or start != clock:
                raise ValueError(f"{tag} does not follow on from the section before it")
            clock = end
            lines.append(f"[{match.group(1)} {match.group(2)}:{match.group(3)}-{match.group(4)}:{match.group(5)}]")
        else:
            lines.append(f"[{match.group(1)}]")
    if len(lines) > 40:
        raise ValueError("a structure can have 40 sections at most")
    return "\n".join(lines)


def seconds(structure: str) -> int | None:
    """The total length of a timed structure, or None when it has no times."""
    ends = re.findall(r"-(\d{1,2}):(\d{2})\]", structure or "")
    return int(ends[-1][0]) * 60 + int(ends[-1][1]) if ends else None


def with_lora(graph: dict, loader: str, lora: str, text_nodes: tuple[str, ...], strength: float = 1.0) -> dict:
    """Put the LoRA between the checkpoint and the YuE2 text nodes.  The model side
    is left alone (strength 0), so the audio sampler is unchanged."""
    graph["20"] = {"class_type": "LoraLoader", "inputs": {
        "model": [loader, 0], "clip": [loader, 1], "lora_name": lora,
        "strength_model": 0.0, "strength_clip": strength}}
    for node in text_nodes:
        graph[node]["inputs"]["clip"] = ["20", 1]
    return graph


def sings(abc: str | None) -> int:
    """How many notes the plan puts in the Vocal voice.

    The instrumental LoRA writes that voice as rests carrying the chords and puts
    the melody in Ins. When it slips and writes an actual melody there, the
    render sings — every time, in everything measured: two plans with notes in
    that voice sang through two thirds of themselves, and fifteen with rests
    alone came out clean. The plan exists before the render, so this is known
    before any of it is generated.
    """
    voice, notes = None, 0
    for raw in (abc or "").split("\n"):
        line = raw.strip()
        if line.startswith("V:"):
            voice = line[2:].strip().split()[0] if line[2:].strip() else None
            continue
        if not line or line[0] == "%" or re.match(r"^[A-Za-z]:", line):
            continue
        if voice != "Vocal":
            continue
        notes += len(re.findall(r"[A-Ga-g]", re.sub(r'"[^"]*"', "", line)))
    return notes


def excerpt(src: Path, dest: Path, spans: int = 3, each: float = 10.0) -> Path:
    """A short montage of the piece, for a check that need not read all of it.

    Singing that has crept into an instrumental runs through it rather than
    appearing for a bar, so three spans spread across the track find it while
    separating a fraction of the audio."""
    total = duration_of(src)
    if total <= spans * each:
        shutil.copy(src, dest)
        return dest
    starts = [total * fraction - each / 2 for fraction in (0.25, 0.5, 0.75)][:spans]
    parts = " ".join(
        f"[0:a]atrim=start={max(0.0, start):.2f}:duration={each},asetpts=N/SR/TB[a{i}];"
        for i, start in enumerate(starts))
    joins = "".join(f"[a{i}]" for i in range(len(starts)))
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-filter_complex",
         f"{parts}{joins}concat=n={len(starts)}:v=0:a=1[out]", "-map", "[out]", str(dest)],
        check=True, capture_output=True, timeout=120)
    return dest


def duration_of(src: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],
        check=True, capture_output=True, timeout=60).stdout
    try:
        return float(out.decode().strip())
    except ValueError:
        return 0.0


def sung_share(vocals: Path) -> float:
    """How much of a separated vocal is actually someone singing, as a share of
    its seconds.  Returns 0.0 when it cannot be read: a check that fails should
    not accuse a take."""
    try:
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(vocals), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
            check=True, capture_output=True, timeout=300).stdout
    except (subprocess.SubprocessError, OSError):
        return 0.0
    import numpy as np

    samples = np.frombuffer(raw, dtype=np.float32)
    seconds = len(samples) // 16000
    if seconds < 2:
        return 0.0
    frames = samples[:seconds * 16000].reshape(seconds, 16000).astype(np.float64)
    loud = np.sqrt((frames ** 2).mean(axis=1))
    return round(float((loud > VOCAL_FLOOR).sum()) / seconds, 4)
