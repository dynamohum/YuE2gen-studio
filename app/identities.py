"""Identities: a folder of one singer's songs, prepared as a training set.

Scanning reads the folder and never writes to it.  Analysis copies each included
song into the library, separates the vocal, measures key and tempo, and drafts
the lyrics.  Export writes the files a trainer expects, one set per song:

    <song>.flac          the recording
    <song>.lyrics.txt    full lyrics with [Verse] / [Chorus] style section tags
    <song>.txt           a style caption that starts with the identity's trigger word
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

log = logging.getLogger("yue2.identities")

AUDIO_TYPES = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}
MIN_SECONDS = 90
# Longer than any song: most likely a whole album or a side in one file.  Analysing one
# takes a very long time and a great deal of memory, and it would train as one song.
MAX_SECONDS = 600
# A filename that credits someone else ("Ft. Alan Williams on vocals") is not one voice.
OTHER_SINGER = re.compile(r"\b(ft\.?|feat\.?|featuring|duet|with .+ on vocals)\b", re.I)
CHUNK_RATE = 16000          # what Gemma's audio encoder takes
CHUNK_MAX = 28.0            # seconds; Gemma listens to about 30 at a time
CHUNK_MIN = 14.0


# ------------------------------------------------------------------- the folder
def import_roots() -> list[Path]:
    """Folders a corpus may be built from: the one the user drops songs into, then
    whatever else this machine is allowed to read."""
    roots = [config.CORPUS_INBOX]
    roots.extend(Path(p) for p in config.IMPORT_ROOTS if Path(p) != config.CORPUS_INBOX)
    return roots


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


TOO_LONG = f"longer than {MAX_SECONDS // 60} minutes"


def too_long(seconds: float | None) -> bool:
    return bool(seconds) and seconds > MAX_SECONDS


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
        elif too_long(info["duration"]):
            song.update(include=False, flag=TOO_LONG)
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


# Whisper's stock inventions: text it produces over music or silence, learned from
# the endings of videos.  A whole line that is exactly one of these is dropped.  Its
# own confidence scores cannot tell them from sung lines -- measured, "Thank you."
# scored as well as real lyrics did -- so they are matched by what they say.
STOCK_PHRASES = re.compile(
    r"^(thank you( (so much|very much))?( for watching)?|thanks for watching|please subscribe"
    r"|subscribe( to my channel)?|subtitles by .*|see you (next time|in the next video))[.!]*$",
    re.IGNORECASE)


class Stopped(Exception):
    """The analysis was stopped while Whisper was listening."""


def transcribe(vocals: Path, on_progress=None, duration: float = 0.0, should_stop=None) -> list[dict]:
    """The sung lines of a separated vocal, with their times, from Whisper on the CPU.

    Whisper hears the whole vocal.  Its voice detector is off: built for speech, it
    judged most singing to be silence and threw it away before listening -- 4 min 21 s
    of a 5 min 55 s vocal, 1 min 33 s of a 3.5 minute one -- and that, not Whisper's
    ear, was most of its error.  Against real lyrics, with the detector on and then
    off: Modern Girl 10.7% of words wrong, then 1.5%; Silly Love Songs, whose chorus
    has lead and backing vocals over each other, 56% then 25%.  Gemini listening to
    the same vocals got 1.5% and 23%.

    Without the detector Whisper invents text over the instrumental stretches -- here
    "Thank you." and a line of French.  hallucination_silence_threshold drops what it
    writes over long silences, which needs word timestamps, and STOCK_PHRASES drops the
    stock lines that survive it.  The cost is time: the whole track is listened to."""
    global _whisper
    from faster_whisper import WhisperModel
    if _whisper is None:
        root = config.DATA_DIR / "models" / "whisper"
        root.mkdir(parents=True, exist_ok=True)
        try:
            _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8",
                                    download_root=str(root), local_files_only=True)
        except Exception:
            _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8",
                                    download_root=str(root), local_files_only=False)
    segments, _ = _whisper.transcribe(str(vocals), language="en", vad_filter=False, beam_size=5,
                                      condition_on_previous_text=False, word_timestamps=True,
                                      hallucination_silence_threshold=2.0)
    lines = []
    for seg in segments:
        # Checked between lines: a thread cannot be cancelled, so Stop asks it to end.
        if should_stop and should_stop():
            raise Stopped()
        # Segments arrive as they are decoded, and each carries its time, so the
        # caller can be told how far through the song this is.
        if on_progress and duration > 0:
            on_progress(max(0.0, min(1.0, seg.end / duration)))
        # Whisper runs sung lines together; split at sentence ends, sharing out the time.
        parts = [p.strip() for p in re.split(r"(?<=[.?!])\s+", seg.text.strip()) if p.strip()]
        total = sum(len(p) for p in parts) or 1
        at = seg.start
        for part in parts:
            share = (seg.end - seg.start) * len(part) / total
            if not STOCK_PHRASES.match(part):
                lines.append({"start": round(at, 2), "end": round(at + share, 2), "text": part.rstrip(".")})
            at += share
    return lines


def _word(token: str) -> str:
    return re.sub(r"[^a-z']", "", token.lower().replace("\u2019", "'"))


# Below this share of its words agreeing with what Whisper heard, a reply is taken to
# be something other than this recording: a famous song's published lyrics written
# out from memory, say.  On Modern Girl the two agreed on nearly every word.
AGREEMENT_FLOOR = 0.3


def time_lines(timed: list[dict], lines: list[str]) -> list[dict] | None:
    """Give lines heard by another model the times Whisper found.

    Whisper's lines carry times; an LLM's carry none, and its timestamps are not to
    be trusted.  So each Whisper line's time is shared across its words, the two
    word sequences are matched, and each LLM line takes the times of its matched
    words.  A line Whisper missed entirely, which is the error an LLM fixes, has no
    matched words: it is placed between the lines either side of it, in order.

    None when the two barely agree, so the caller keeps Whisper's own lines rather
    than laying out words that are not this recording's."""
    import difflib

    ww, wt = [], []
    for line in timed:
        tokens = [w for w in (_word(t) for t in line["text"].split()) if w]
        span = line["end"] - line["start"]
        for k, w in enumerate(tokens):
            ww.append(w)
            wt.append(line["start"] + span * (k + 0.5) / len(tokens))
    lw, li = [], []
    for i, line in enumerate(lines):
        for t in line.split():
            w = _word(t)
            if w:
                lw.append(w)
                li.append(i)
    if not ww or not lw:
        return None
    matched = {}
    for a, b, size in difflib.SequenceMatcher(None, ww, lw, autojunk=False).get_matching_blocks():
        for k in range(size):
            matched[b + k] = wt[a + k]
    if len(matched) < AGREEMENT_FLOOR * len(lw):
        return None
    times: list[list[float]] = [[] for _ in lines]
    for j, t in matched.items():
        times[li[j]].append(t)
    starts = [min(ts) if ts else None for ts in times]
    ends = [max(ts) if ts else None for ts in times]
    known = [i for i, t in enumerate(starts) if t is not None]
    for i in range(len(lines)):
        if starts[i] is not None:
            continue
        before = max((k for k in known if k < i), default=None)
        after = min((k for k in known if k > i), default=None)
        if before is not None and after is not None:
            at = ends[before] + (starts[after] - ends[before]) * (i - before) / (after - before)
        else:
            at = ends[before] if before is not None else starts[after]
        starts[i] = ends[i] = at
    return [{"start": round(a, 2), "end": round(b, 2), "text": text.strip()}
            for a, b, text in zip(starts, ends, lines)]


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


# How far a section boundary may move to reach a pause in the singing.  More room
# before than after: singers start a line on a pickup, ahead of the bar the section
# begins on, so the estimate is usually late, not early.
SNAP_BEFORE = 4.0
SNAP_AFTER = 2.0


def _snap(boundary: float, lines: list[dict], low: float, high: float) -> float:
    """Move a section boundary to the longest pause between sung lines near it.  A
    section almost always begins after a pause, and the proportional estimate lands
    a second or three late: on 104 corpus songs, half put the first line of the first
    verse under [Intro].  Stays where it is when it already sits in the longest pause."""
    lo, hi = max(low, boundary - SNAP_BEFORE), min(high, boundary + SNAP_AFTER)
    if lo >= hi:
        return boundary
    gaps, sung_until = [], 0.0
    for line in sorted(lines, key=lambda l: l["start"]):
        if line["start"] > sung_until:
            gaps.append((sung_until, line["start"]))
        sung_until = max(sung_until, line["end"])
    gaps.append((sung_until, float("inf")))
    best, here = None, None
    for start, end in gaps:
        if end <= lo or start >= hi:
            continue
        if start <= boundary <= end:
            here = (start, end)
        if best is None or end - start > best[1] - best[0]:
            best = (start, end)
    if best is None or (here and here[1] - here[0] >= 0.8 * (best[1] - best[0])):
        return boundary
    # The point of that pause nearest the estimate, inside the window.
    return min(max(boundary, max(best[0], lo)), min(best[1], hi))


def tag_lyrics(lines: list[dict], sections: list[tuple[str, float]], duration: float) -> str:
    """Each sung line under the section playing when it starts.  The sections are
    laid over the song in proportion to their length, so a tempo SheetSage got
    wrong by a factor does not matter, then each boundary moves to the pause in
    the singing nearest it.  Without sections, the lines go under one verse."""
    if not lines:
        return ""
    if not sections or not duration:
        return "[Verse]\n" + "\n".join(l["text"] for l in lines)
    total = sum(length for _, length in sections)
    edges, at = [0.0], 0.0
    for _, length in sections:
        at += duration * length / total
        edges.append(at)
    for i in range(1, len(edges) - 1):
        edges[i] = _snap(edges[i], lines, edges[i - 1], edges[i + 1])
    bounds = [(SECTION_TAGS[name], edges[i], edges[i + 1]) for i, (name, _) in enumerate(sections)]
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


def caption(trigger: str, description: str, voice: str, key: str | None, tempo: int | None,
            style_hint: str = "") -> str:
    """The style caption a trainer reads: the trigger word first, then the sound."""
    # "key of X" and "N BPM" are the forms the FS_Audio dataset builder looks for; with
    # them present it does not append its own, so the key is not stated twice.
    parts = [trigger.strip(), (style_hint or "").strip(), description.strip(),
             f"{voice} vocal" if voice else "", f"key of {key}" if key else "",
             f"{tempo} BPM" if tempo else ""]
    return ", ".join(p for p in parts if p)


def song_dir(identity_id: str, song: dict) -> Path:
    return config.DATA_DIR / "identities" / identity_id / "songs" / f"{slugify(song['title'])}-{song['id']}"


# ------------------------------------------------------------------ cue sheets
# An album ripped to one file often comes with a .cue sheet that says where each
# track starts.  The tracks are cut into the app's own folder, never beside the album:
# the corpus folder is only ever read.
CUE_TIME = re.compile(r"^(\d+):(\d{1,2}):(\d{1,2})$")


def tracks_dir(identity_id: str) -> Path:
    return config.DATA_DIR / "identities" / identity_id / "tracks"


def is_track(path: Path) -> bool:
    """A track cut from an album by the app, in some corpus's own folder."""
    try:
        rel = path.resolve().relative_to((config.DATA_DIR / "identities").resolve())
    except ValueError:
        return False
    return len(rel.parts) >= 3 and rel.parts[1] == "tracks"


def _cue_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _unquote(value: str) -> str:
    value = value.strip()
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value


def parse_cue(text: str) -> list[dict]:
    """The files a cue sheet names, each with its tracks: number, title, performer
    and start in seconds (INDEX 01; a cue frame is 1/75 s)."""
    files, album_performer, current, track = [], "", None, None
    for raw in text.splitlines():
        line = raw.strip()
        word, _, rest = line.partition(" ")
        word = word.upper()
        if word == "FILE":
            name = rest.rsplit(" ", 1)[0] if rest.rstrip().endswith(('WAVE', 'MP3', 'AIFF', 'BINARY', 'MOTOROLA')) else rest
            current = {"file": _unquote(name), "tracks": []}
            files.append(current)
            track = None
        elif word == "TRACK" and current is not None:
            number = rest.split()[0] if rest.split() else "0"
            track = {"number": int(number) if number.isdigit() else len(current["tracks"]) + 1,
                     "title": "", "performer": album_performer, "start": None}
            current["tracks"].append(track)
        elif word == "TITLE" and track is not None:
            track["title"] = _unquote(rest)
        elif word == "PERFORMER":
            if track is not None:
                track["performer"] = _unquote(rest)
            else:
                album_performer = _unquote(rest)
        elif word == "INDEX" and track is not None:
            parts = rest.split()
            found = CUE_TIME.match(parts[1]) if len(parts) == 2 else None
            if found and parts[0] == "01":
                minutes, seconds, frames = (int(g) for g in found.groups())
                track["start"] = minutes * 60 + seconds + frames / 75
    for entry in files:
        entry["tracks"] = [t for t in entry["tracks"] if t["start"] is not None]
    return [entry for entry in files if entry["tracks"]]


def cue_for(audio: Path) -> dict | None:
    """The cue sheet beside an album file that splits it into tracks, if there is one.
    A sheet often names the file it was made for with another extension (a .wav
    later converted to .flac), so the name is matched without it."""
    try:
        sheets = sorted(p for p in audio.parent.iterdir() if p.is_file() and p.suffix.lower() == ".cue")
    except OSError:
        return None
    for sheet in sheets:
        try:
            entries = parse_cue(_cue_text(sheet))
        except (OSError, ValueError):
            continue
        for entry in entries:
            named = Path(entry["file"].replace("\\", "/")).name
            if named.lower() == audio.name.lower() or Path(named).stem.lower() == audio.stem.lower():
                if len(entry["tracks"]) >= 2:
                    return {"cue": sheet.name, "tracks": entry["tracks"]}
    return None


def split_album(audio: Path, tracks: list[dict], dest: Path) -> list[dict]:
    """Cut each track out of the album into dest as FLAC, named and tagged with its
    title.  Returns each track with its file."""
    dest.mkdir(parents=True, exist_ok=True)
    made = []
    for index, track in enumerate(tracks):
        end = tracks[index + 1]["start"] if index + 1 < len(tracks) else None
        title = track["title"] or f"Track {track['number']:02d}"
        name = f"{track['number']:02d} {re.sub(r'[^A-Za-z0-9 ._()-]+', '', title).strip()[:80] or 'Track'}.flac"
        out = dest / name
        cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{track['start']:.3f}", "-i", str(audio)]
        if end is not None:
            cmd += ["-t", f"{end - track['start']:.3f}"]
        cmd += ["-map", "0:a:0", "-map_metadata", "-1", "-metadata", f"title={title}",
                "-c:a", "flac", str(out)]
        subprocess.run(cmd, capture_output=True, check=True, timeout=900)
        made.append({**track, "title": title, "path": out})
    return made


persona_dir = song_dir


def export_name(song: dict) -> str:
    return f"{slugify(song['title'])}-{song['id']}"
