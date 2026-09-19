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

SECTIONS = ("intro", "verse", "pre-chorus", "chorus", "bridge", "outro")
# How firmly the LoRA holds the model to its training.  Steady is the author's own
# setting; Varied loosens it, for more movement between sections.
FEELS = {"steady": 1.0, "varied": 0.8}
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
