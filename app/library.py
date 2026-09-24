"""Where files live in the data folder, and what the app reads from them: names,
the take.json sidecar, durations and waveform peaks."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import config
from .db import execute, rows

log = logging.getLogger("yue2.library")


def slugify(text: str, limit: int = 40) -> str:
    """A short name a person can read, for use in a folder or file name."""
    text = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower())
    return re.sub(r"-{2,}", "-", text).strip("-")[:limit].strip("-") or "untitled"


def take_folder(take_id: str, title: str) -> Path:
    """takes/<title>-<id>/ so the folder says what it holds and stays unique."""
    return config.TAKES_DIR / f"{slugify(title)}-{take_id}"


def take_audio_path(take_id: str, title: str) -> Path:
    return take_folder(take_id, title) / f"{slugify(title)}.flac"


def source_path(digest: str, filename: str, fallback: str, ext: str) -> Path:
    """sources/<hash>-<original name><ext>, so the file still says what it was."""
    name = slugify(Path(filename).stem if filename else fallback, 40)
    return config.SOURCES_DIR / f"{digest[:16]}-{name}{ext}"


def remove_tree(path: Path | None) -> None:
    """Delete a folder and everything in it.  A folder that is already gone is fine."""
    if path is None:
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def write_take_note(take: dict, audio: Path) -> None:
    """A sidecar, so a folder copied out of the library explains itself."""
    note = {
        "id": take["id"],
        "title": take["title"],
        "kind": take["kind"],
        "style": take.get("style"),
        "lyrics": take.get("lyrics"),
        "seed": take.get("seed"),
        "mode": take.get("mode"),
        "variety": take.get("variety"),
        "harmony": take.get("harmony"),
        "interpretation": take.get("interpretation"),
        "feel": take.get("feel") if take.get("kind") == "instrumental" else None,
        "checkpoint": take.get("checkpoint"),
        "duration": take.get("duration"),
        "created_at": take.get("created_at"),
        "source_id": take.get("source_id"),
        "audio": audio.name,
        "score": take.get("abc"),
        "app": "YuE2 Studio",
        "version": config.VERSION,
    }
    try:
        (audio.parent / "take.json").write_text(json.dumps(note, indent=2), encoding="utf-8")
    except OSError as exc:
        log.warning("could not write the take note: %s", exc)


def relayout() -> None:
    """Rename stored files after the thing they hold.  Runs on every start and does
    nothing once the names are right.  Titles never change after a take is created,
    so a name computed here stays valid.  A take.json is only written when missing."""
    moved = 0

    for take in rows("SELECT * FROM takes"):
        have = Path(take["audio_path"]) if take["audio_path"] else None
        if not have or not have.exists():
            continue
        want = take_audio_path(take["id"], take["title"])
        if is_normalised_file(have):
            want = normalised_path(want)
        if have != want:
            try:
                want.parent.mkdir(parents=True, exist_ok=True)
                if not want.exists():
                    shutil.move(str(have), str(want))
                    moved += 1
                try:
                    have.parent.rmdir()   # the old id-only folder, now empty
                except OSError:
                    pass
                execute("UPDATE takes SET audio_path = ? WHERE id = ?", (str(want), take["id"]))
            except OSError as exc:
                log.warning("could not rename take %s: %s", take["id"], exc)
                continue
        if want.exists() and not (want.parent / "take.json").exists():
            take["audio_path"] = str(want)
            write_take_note(take, want)

    for source in rows("SELECT * FROM sources"):
        have = Path(source["stored_path"])
        if not have.exists():
            continue
        want = source_path(source["sha256"], source["filename"], source["title"], have.suffix)
        if have == want:
            continue
        try:
            want.parent.mkdir(parents=True, exist_ok=True)
            if not want.exists():
                shutil.move(str(have), str(want))
                moved += 1
            execute("UPDATE sources SET stored_path = ? WHERE id = ?", (str(want), source["id"]))
        except OSError as exc:
            log.warning("could not rename source %s: %s", source["id"], exc)

    for item in rows("SELECT * FROM stem_sets WHERE folder IS NOT NULL"):
        have = Path(item["folder"])
        if not have.exists():
            continue
        want = have.parent / f"{slugify(item['title'])}-{item['id']}"
        if have == want:
            continue
        try:
            if not want.exists():
                shutil.move(str(have), str(want))
                moved += 1
            execute("UPDATE stem_sets SET folder = ? WHERE id = ?", (str(want), item["id"]))
        except OSError as exc:
            log.warning("could not rename stem set %s: %s", item["id"], exc)

    if moved:
        log.info("library relaid out, %d items renamed", moved)


# ------------------------------------------------------------------- audio info
def loudness(path: Path) -> float | None:
    """The average level of a file in dB, from ffmpeg's volumedetect.  A fifth of a
    second for a two minute take."""
    try:
        out = subprocess.run(["ffmpeg", "-v", "info", "-nostats", "-i", str(path), "-af", "volumedetect",
                              "-f", "null", "-"], capture_output=True, text=True, timeout=120).stderr
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("could not read the level of %s: %s", path.name, exc)
        return None
    found = re.search(r"mean_volume:\s*(-?[\d.]+|-inf) dB", out)
    if not found:
        return None
    return -120.0 if found.group(1) == "-inf" else round(float(found.group(1)), 1)


def fill_loudness() -> int:
    """Read the level of finished takes made before it was recorded.  It is the level
    as rendered, so a normalised take is read from the file kept from before."""
    done = 0
    for row in rows("SELECT id, audio_path FROM takes WHERE status = 'done' AND loudness IS NULL AND audio_path IS NOT NULL"):
        path = rendered_path(Path(row["audio_path"]))
        level = loudness(path) if path.exists() else None
        if level is not None:
            execute("UPDATE takes SET loudness = ? WHERE id = ?", (level, row["id"]))
            done += 1
    return done


# What a quiet take is brought up to.  Streaming services play at -14 LUFS, and a
# render that has not lost its footing lands about there.  The peak ceiling keeps
# the raised take from clipping.
NORMAL_LUFS = -14.0
NORMAL_PEAK = -1.0


def replace_file(src: Path, dest: Path, tries: int = 10) -> None:
    """os.replace, waiting a moment when another program has the file open.  Windows
    refuses to replace an open file; a player or an editor usually lets go soon."""
    for attempt in range(tries):
        try:
            os.replace(src, dest)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(0.3)


# A normalised take points at a louder copy beside the file as rendered, which is never
# changed.  Nothing is replaced while it may be open: Windows refuses to replace a file
# that a player, another tab or an editor is reading.
NORMALISED = ".normalised"


def normalised_path(rendered: Path) -> Path:
    return rendered.with_name(f"{rendered.stem}{NORMALISED}{rendered.suffix}")


def is_normalised_file(audio: Path) -> bool:
    return audio.stem.endswith(NORMALISED)


def rendered_path(audio: Path) -> Path:
    """The file as rendered, whichever of the two a take points at."""
    return audio.with_name(audio.stem[:-len(NORMALISED)] + audio.suffix) if is_normalised_file(audio) else audio


def original_path(audio: Path) -> Path:
    """Where the first version of normalising kept the file as rendered, when it
    normalised a take in place.  Read only to convert such takes."""
    return audio.with_name(f"{audio.stem}.original{audio.suffix}")


def convert_old_normalised() -> int:
    """Takes normalised in place (song.flac louder, song.original.flac as rendered) get
    the present layout (song.flac as rendered, song.normalised.flac louder).  Runs at
    start, when nothing has the files open."""
    done = 0
    for take in rows("SELECT id, audio_path FROM takes WHERE normalised = 1 AND audio_path IS NOT NULL"):
        audio = Path(take["audio_path"])
        kept = original_path(audio)
        if is_normalised_file(audio) or not kept.exists() or not audio.exists():
            continue
        try:
            os.replace(audio, normalised_path(audio))
            os.replace(kept, audio)
        except OSError as exc:
            log.warning("could not convert normalised take %s: %s", take["id"], exc)
            continue
        execute("UPDATE takes SET audio_path = ? WHERE id = ?", (str(normalised_path(audio)), take["id"]))
        done += 1
    return done


def normalise(rendered: Path) -> Path:
    """Write a copy of a take at the usual loudness beside the file as rendered, and
    return it.  The rendered file is only read, so doing it twice gives the same result.

    Two passes: the first measures, the second applies one gain to the whole take, so
    its quiet and loud parts keep their distance.  Only when that gain would push a
    peak past the ceiling does ffmpeg fall back to shaping the level as it goes."""
    target = f"I={NORMAL_LUFS}:TP={NORMAL_PEAK}:LRA=11"
    keep = rendered
    audio = normalised_path(rendered)
    first = subprocess.run(["ffmpeg", "-v", "info", "-nostats", "-i", str(keep), "-af",
                            f"loudnorm={target}:print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=300).stderr
    found = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", first)
    if not found:
        raise RuntimeError("ffmpeg could not measure the take's loudness")
    measured = json.loads(found.group(0))
    rate = "48000"
    with keep.open("rb") as fh:
        head = fh.read(26)
    if head[:4] == b"fLaC" and len(head) >= 26:
        rate = str(int.from_bytes(head[18:26], "big") >> 44 or 48000)
    staged = rendered.with_name(f"{rendered.stem}.normalising{rendered.suffix}")
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(keep), "-af",
                        f"loudnorm={target}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
                        f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
                        f":offset={measured['target_offset']}:linear=true",
                        "-ar", rate, "-c:a", "flac", str(staged)],
                       capture_output=True, text=True, timeout=300, check=True)
        replace_file(staged, audio)
    finally:
        staged.unlink(missing_ok=True)
    return audio


def audio_duration(path: Path) -> float | None:
    """FLAC carries its length in the header, which is instant.  Anything else, or a
    FLAC that does not say, goes to ffprobe."""
    try:
        with path.open("rb") as fh:
            head = fh.read(26)
        if head[:4] == b"fLaC" and len(head) >= 26:
            packed = int.from_bytes(head[18:26], "big")
            sample_rate = packed >> 44
            total_samples = packed & ((1 << 36) - 1)
            if sample_rate and total_samples:
                return round(total_samples / sample_rate, 2)
    except OSError as exc:
        log.warning("duration read failed for %s: %s", path, exc)
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip()
        return round(float(out), 2)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        log.warning("ffprobe could not read %s: %s", path, exc)
        return None


# The waveform the player draws.  Computed once on the server from an 8 kHz mono
# decode, instead of the browser decoding the whole file to float PCM on every play.
PEAK_COLUMNS = 1024
PEAK_RATE = 8000


def peaks_path(audio: Path) -> Path:
    return audio.with_name(audio.stem + ".peaks.json")


def vocal_path(recording: Path) -> Path:
    """A recording's separated vocal, kept beside it once lyrics have been heard.

    The vocal depends only on the recording, which never changes, and the
    separation model, which the lyrics job fixes, so separating it a second time
    gives the same file and costs most of the job's time.  FLAC: lossless, as the
    listening needs, and about half the size of the WAV the separator writes."""
    return recording.with_name(recording.stem + ".vocals.flac")


def kept_beside(recording: Path) -> list[Path]:
    """What the app keeps beside a recording, to go when the recording does."""
    return [peaks_path(recording), vocal_path(recording)]


def compute_peaks(audio: Path) -> dict:
    import numpy as np

    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(audio), "-ac", "1", "-ar", str(PEAK_RATE), "-f", "f32le", "-"],
        capture_output=True, timeout=300, check=True,
    ).stdout
    data = np.abs(np.frombuffer(raw, dtype=np.float32))
    if data.size < PEAK_COLUMNS:
        data = np.pad(data, (0, PEAK_COLUMNS - data.size))
    per = data.size // PEAK_COLUMNS
    frames = data[: per * PEAK_COLUMNS].reshape(PEAK_COLUMNS, per)
    peaks = frames.max(axis=1)
    rms = np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1))

    def norm(values):
        top = float(values.max()) or 1.0
        return [round(float(v) / top, 3) for v in values]

    return {"columns": PEAK_COLUMNS, "peaks": norm(peaks), "rms": norm(rms)}


def ensure_peaks(audio: Path) -> dict | None:
    """Read the cached peaks for a file, computing them the first time."""
    cache = peaks_path(audio)
    try:
        if cache.exists() and cache.stat().st_mtime >= audio.stat().st_mtime:
            return json.loads(cache.read_text(encoding="utf-8"))
        result = compute_peaks(audio)
        cache.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
        return result
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        log.warning("peaks failed for %s: %s", audio, exc)
        return None
