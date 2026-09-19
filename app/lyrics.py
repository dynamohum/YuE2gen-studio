"""Lyric drafts from a short brief, written by a language model on the engine.

The prompt asks for YuE2's own layout: a title line, then sections tagged
[Verse], [Chorus] and so on.  parse() tidies what comes back, since a model can
still add a stray note or bold a heading, and says what is missing."""
from __future__ import annotations

import re

STRUCTURES = {
    "verse-chorus-bridge": ["Verse", "Chorus", "Verse", "Chorus", "Bridge", "Chorus"],
    "verse-chorus": ["Verse", "Chorus", "Verse", "Chorus"],
    "intro-outro": ["Intro", "Verse", "Chorus", "Verse", "Chorus", "Outro"],
    "story": ["Verse", "Verse", "Chorus", "Verse", "Chorus", "Outro"],
}
DEFAULT_STRUCTURE = "verse-chorus-bridge"
TAGS = {"verse", "chorus", "bridge", "intro", "outro", "pre-chorus"}

PROMPT = """You are a songwriter. Write original lyrics for a song.

What it is about: {brief}
The music: {style}
Structure, in this order: {structure}

Rules:
- The first line is: Title: <the song title>
- Then each section starts with its tag alone on a line, in square brackets, exactly as listed: {tags}
- Put one blank line between sections.
- Verses and choruses have 4 lines each. A bridge, intro or outro has 2 to 4 lines.
- Every chorus uses the same words.
- Keep lines singable: roughly 6 to 10 syllables, with rhymes at the ends of lines.
- The music description is for the sound only. Do not name instruments, genres or production in the lyrics.
- Use concrete images and plain words. Avoid cliches.
- Do not reuse lines from existing songs.
- Write in English unless the brief asks for another language.
- Output only the title and the lyrics. No notes, no explanations, no markdown."""


def build_prompt(brief: str, style: str, structure: str) -> str:
    sections = STRUCTURES.get(structure, STRUCTURES[DEFAULT_STRUCTURE])
    return PROMPT.format(brief=" ".join(brief.split()), style=" ".join(style.split()) or "any",
                         structure=", ".join(sections),
                         tags=" ".join(f"[{name}]" for name in dict.fromkeys(sections)))


def _tag(line: str) -> str | None:
    """'[Verse]', '**[verse 2]**' or 'Chorus:' as a section name; None for a lyric line."""
    bare = line.strip().strip("*_#").strip()
    match = re.fullmatch(r"\[([A-Za-z -]+?)(?:\s*\d+)?\]|([A-Za-z -]+?)(?:\s*\d+)?:", bare)
    if not match:
        return None
    name = (match.group(1) or match.group(2)).strip().lower()
    if name not in TAGS:
        return None
    return "Pre-Chorus" if name == "pre-chorus" else name.title()


def parse(text: str) -> dict:
    """{'title', 'lyrics', 'sections', 'problems'} from a model's reply."""
    title = None
    sections: list[tuple[str, list[str]]] = []
    for raw in (text or "").replace("\r", "").split("\n"):
        line = raw.strip()
        if not line or line.startswith("```"):
            continue
        if title is None and not sections and re.match(r"^\**\s*title\s*:", line, re.I):
            title = re.sub(r"^\**\s*title\s*:\s*", "", line, flags=re.I).strip("* \"'") or None
            continue
        tag = _tag(line)
        if tag:
            sections.append((tag, []))
        elif sections:
            sections[-1][1].append(line.strip("*_").strip())
        # Anything before the first section that is not the title is a preamble: dropped.
    sections = [(name, lines) for name, lines in sections if lines]
    problems = []
    if not sections:
        problems.append("no song sections")
    lyrics = "\n\n".join(f"[{name}]\n" + "\n".join(lines) for name, lines in sections)
    return {"title": title, "lyrics": lyrics, "sections": [name for name, _ in sections], "problems": problems}
