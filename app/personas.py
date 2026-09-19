"""Personas: a folder of one singer's songs, prepared as a training set.

Scanning reads the folder and never writes to it.  Analysis copies each included
song into the library, separates the vocal, measures key and tempo, and drafts
the lyrics.  Export writes the files a trainer expects, one set per song:

    <song>.flac          the recording
    <song>.lyrics.txt    full lyrics with [Verse] / [Chorus] style section tags
    <song>.txt           a style caption that starts with the persona's trigger word
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
from pathlib import Path

import numpy as np

from . import config
from .library import slugify

log = logging.getLogger("yue2.personas")

AUDIO_TYPES = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}
MIN_SECONDS = 90
# A filename that credits someone else ("Ft. Alan Williams on vocals") is not one voice.
OTHER_SINGER = re.compile(r"\b(ft\.?|feat\.?|featuring|duet|with .+ on vocals)\b", re.I)
CHUNK_RATE = 16000          # what Gemma's audio encoder takes
CHUNK_MAX = 28.0            # seconds; Gemma listens to about 30 at a time
CHUNK_MIN = 14.0


# ------------------------------------------------------------------- the folder
def import_roots() -> list[Path]:
    return [Path(p) for p in config.IMPORT_ROOTS]


def allowed(path: Path) -> bool:
    """Only folders under an import root may be read."""
    resolved = path.resolve()
    for root in import_roots():
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def browse(path: str | None) -> dict:
    """Folders and audio files at a path under an import root, for the picker."""
    if not path:
        return {"path": None, "parent": None, "folders": [str(r) for r in import_roots() if r.is_dir()], "songs": 0}
    folder = Path(path)
    if not allowed(folder) or not folder.is_dir():
        raise ValueError("that folder is not available to the app")
    parent = str(folder.parent) if allowed(folder.parent) and folder.resolve() not in [r.resolve() for r in import_roots()] else None
    entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    return {"path": str(folder), "parent": parent,
            "folders": [str(p) for p in entries if p.is_dir() and not p.name.startswith(".")],
            "songs": sum(1 for p in entries if p.is_file() and p.suffix.lower() in AUDIO_TYPES)}


def probe(path: Path) -> dict:
    """Duration, bit rate and the title tag, from ffprobe."""
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration,bit_rate:format_tags=title,artist",
                          "-of", "json", str(path)], capture_output=True, text=True, timeout=60)
    data = json.loads(out.stdout or "{}").get("format", {})
    tags = {k.lower(): v for k, v in (data.get("tags") or {}).items()}
    return {"duration": float(data.get("duration") or 0), "bit_rate": int(data.get("bit_rate") or 0),
            "title": tags.get("title"), "artist": tags.get("artist")}


def title_from_name(name: str) -> str:
    """'03 Modern Girl.mp3' -> 'Modern Girl'; 'a_man_like_you.mp3' -> 'A Man Like You'."""
    stem = Path(name).stem.replace("_", " ")
    stem = re.sub(r"^\s*\d+\s*[.\-_)]?\s*", "", stem).strip()
    return stem[:1].upper() + stem[1:] if stem else name


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _same_song(title: str) -> str:
    """A key that matches two versions of one song: 'It's Only Love' and 'Its Only Love'."""
    text = re.sub(r"\(.*?\)|\[.*?\]| - .*$", "", title.lower())
    return re.sub(r"[^a-z0-9]", "", text)


def scan(folder: Path) -> list[dict]:
    """Every audio file in the folder, with a suggestion to include it or not and why.
    Exact copies are left out, a second version of a song is offered but not ticked,
    and a filename naming another singer, or a very short file, is flagged."""
    if not allowed(folder) or not folder.is_dir():
        raise ValueError("that folder is not available to the app")
    songs, by_hash, by_title = [], {}, {}
    files = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_TYPES),
                   key=lambda p: p.name.lower())
    for path in files:
        info = probe(path)
        title = (info["title"] or title_from_name(path.name)).strip()
        digest = sha256(path)
        song = {"file": path.name, "title": title, "duration": round(info["duration"], 1), "bit_rate": info["bit_rate"],
                "sha256": digest, "include": True, "flag": None}
        if digest in by_hash:
            song.update(include=False, flag=f"an exact copy of {by_hash[digest]['file']}")
        elif OTHER_SINGER.search(path.name):
            song.update(include=False, flag="the filename names another singer")
        elif info["duration"] and info["duration"] < MIN_SECONDS:
            song.update(include=False, flag=f"shorter than {MIN_SECONDS} seconds")
        else:
            key = _same_song(title)
            if key in by_title:
                song.update(include=False, flag=f"another version of {by_title[key]['file']}")
            else:
                by_title[key] = song
        by_hash.setdefault(digest, song)
        songs.append(song)
    # A song one of whose versions names another singer is left out in every version:
    # 'did_it_ever.mp3' is the same duet as 'Did It Ever (Ft. Alan Williams on vocals)'.
    duets = {_same_song(s["title"]): s["file"] for s in songs if OTHER_SINGER.search(s["file"])}
    for song in songs:
        other = duets.get(_same_song(song["title"]))
        if other and other != song["file"] and song["include"]:
            song.update(include=False, flag=f"another version of {other}, which names another singer")
    return songs


# --------------------------------------------------------------- vocal chunks
def read_mono(path: Path) -> np.ndarray:
    """16 kHz mono floats via ffmpeg, whatever the file."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(CHUNK_RATE),
                          "-f", "s16le", "-"], capture_output=True, check=True, timeout=600).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def sung_chunks(samples: np.ndarray, rate: int = CHUNK_RATE) -> list[tuple[float, float]]:
    """Stretches of singing no longer than CHUNK_MAX, cut at the quietest moment,
    so a line is rarely split.  Stretches with no voice in them are dropped."""
    hop = rate // 20                                       # 50 ms frames
    frames = len(samples) // hop
    if not frames:
        return []
    rms = np.sqrt(np.mean(samples[: frames * hop].reshape(frames, hop) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms / (rms.max() + 1e-12) + 1e-12)
    voiced = db > -35
    fps = rate / hop
    chunks, start = [], 0
    while start < frames:
        while start < frames and not voiced[start]:
            start += 1                                     # skip silence before the next phrase
        if start >= frames:
            break
        end = int(start + CHUNK_MAX * fps)
        if end >= frames:
            end = frames
        else:
            lo = int(start + CHUNK_MIN * fps)
            end = lo + int(np.argmin(db[lo:end]))          # the quietest point in the window
        if voiced[start:end].mean() > 0.1:
            chunks.append((round(start / fps, 2), round(end / fps, 2)))
        start = end
    return chunks


def write_chunk(samples: np.ndarray, span: tuple[float, float], dest: Path) -> Path:
    import wave
    a, b = int(span[0] * CHUNK_RATE), int(span[1] * CHUNK_RATE)
    pcm = (np.clip(samples[a:b], -1, 1) * 32767).astype(np.int16).tobytes()
    with wave.open(str(dest), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(CHUNK_RATE)
        fh.writeframes(pcm)
    return dest


# ------------------------------------------------------------------ lyrics
WHISPER_MODEL = "large-v3-turbo"
_whisper = None


def transcribe(vocals: Path) -> list[dict]:
    """The sung lines of a separated vocal, with their times, from Whisper on the CPU.
    Measured on one song against its real lyrics: 16% of words wrong, where Gemma
    listening to the same vocal got 43% wrong."""
    global _whisper
    from faster_whisper import WhisperModel
    if _whisper is None:
        root = config.DATA_DIR / "models" / "whisper"
        root.mkdir(parents=True, exist_ok=True)
        _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", download_root=str(root))
    segments, _ = _whisper.transcribe(str(vocals), language="en", vad_filter=True, beam_size=5,
                                      condition_on_previous_text=False)
    lines = []
    for seg in segments:
        # Whisper runs sung lines together; split at sentence ends, sharing out the time.
        parts = [p.strip() for p in re.split(r"(?<=[.?!])\s+", seg.text.strip()) if p.strip()]
        total = sum(len(p) for p in parts) or 1
        at = seg.start
        for part in parts:
            share = (seg.end - seg.start) * len(part) / total
            lines.append({"start": round(at, 2), "end": round(at + share, 2), "text": part.rstrip(".")})
            at += share
    return lines


SECTION_TAGS = {"intro": "Intro", "verse": "Verse", "pre-chorus": "Pre-Chorus", "prechorus": "Pre-Chorus",
                "chorus": "Chorus", "bridge": "Bridge", "outro": "Outro", "interlude": "Bridge", "solo": "Bridge"}


def score_sections(abc: str) -> list[tuple[str, float]]:
    """The sections SheetSage marked in a score, in order, with their length in whole
    notes, from each bar's time signature.  Only the first voice's bars are counted."""
    sections, meter, voice, first_voice = [], 1.0, None, None
    for raw in (abc or "").splitlines():
        line = raw.strip()
        if line.startswith("%"):
            name = line[1:].strip().lower()
            if name in SECTION_TAGS:
                sections.append([name, 0.0])
            continue
        m = re.match(r"^M:\s*(\d+)/(\d+)", line)
        if m:
            meter = int(m.group(1)) / int(m.group(2))
            continue
        v = re.match(r"^V:\s*(\S+)", line)
        if v:
            voice = v.group(1)
            first_voice = first_voice or voice
            continue
        if not line or re.match(r"^[A-Za-z]:", line) or not sections or voice not in (None, first_voice):
            continue
        sections[-1][1] += meter * sum(1 for bar in line.split("|") if bar.strip())
    return [(name, length) for name, length in sections if length > 0]


def tag_lyrics(lines: list[dict], sections: list[tuple[str, float]], duration: float) -> str:
    """Each sung line under the section playing when it starts.  The sections are
    laid over the song in proportion to their length, so a tempo SheetSage got
    wrong by a factor does not matter.  Without sections, the lines go under one verse."""
    if not lines:
        return ""
    if not sections or not duration:
        return "[Verse]\n" + "\n".join(l["text"] for l in lines)
    total = sum(length for _, length in sections)
    bounds, at = [], 0.0
    for name, length in sections:
        bounds.append((SECTION_TAGS[name], at, at + duration * length / total))
        at += duration * length / total
    blocks: list[tuple[str, list[str]]] = []
    for tag, start, end in bounds:
        sung = [l["text"] for l in lines if start <= (l["start"] + l["end"]) / 2 < end]
        if blocks and blocks[-1][0] == tag and tag != "Chorus":
            blocks[-1][1].extend(sung)          # an interlude beside a bridge is one bridge
        else:
            blocks.append((tag, sung))
    # Lines past the last boundary (a rounding matter) join the last section.
    tail = [l["text"] for l in lines if (l["start"] + l["end"]) / 2 >= bounds[-1][2]]
    blocks[-1][1].extend(tail)
    return "\n\n".join(f"[{tag}]" + ("\n" + "\n".join(sung) if sung else "") for tag, sung in blocks)


DESCRIBE = ("Describe this music for a music generator as one line of comma-separated tags: "
            "genre, lead instruments, drums and mood. Output only the tags.")


# --------------------------------------------------------------- style and export
def key_and_tempo(abc: str) -> tuple[str | None, int | None]:
    key = re.search(r"^K:\s*([A-G][#b]?m?)\b", abc or "", re.M)
    tempo = re.search(r"^Q:\s*\d+/\d+\s*=\s*(\d+)", abc or "", re.M)
    name = key.group(1) if key else None
    if name:
        name = name[:-1] + " minor" if name.endswith("m") else name + " major"
    return name, int(tempo.group(1)) if tempo else None


def caption(trigger: str, description: str, voice: str, key: str | None, tempo: int | None) -> str:
    """The style caption a trainer reads: the trigger word first, then the sound."""
    # "key of X" and "N BPM" are the forms the FS_Audio dataset builder looks for; with
    # them present it does not append its own, so the key is not stated twice.
    parts = [trigger.strip(), description.strip(), f"{voice} vocal" if voice else "", f"key of {key}" if key else "",
             f"{tempo} BPM" if tempo else ""]
    return ", ".join(p for p in parts if p)


def song_dir(persona_id: str, song: dict) -> Path:
    return config.DATA_DIR / "personas" / persona_id / "songs" / f"{slugify(song['title'])}-{song['id']}"


def export_name(song: dict) -> str:
    return f"{slugify(song['title'])}-{song['id']}"
