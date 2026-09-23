"""A recording's separated vocal is kept, so hearing its lyrics again skips the
separation, which is most of the job's time.  The vocal depends only on the
recording and the model, and neither changes."""
import asyncio
import time

import pytest

import app.jobs as jobs
from app import config, instrumental, library, stems
from app.db import execute, one

LINES = [{"start": 1.0, "end": 2.0, "text": "Modern girl"}]


@pytest.fixture(autouse=True)
def pause_stems_worker(monkeypatch):
    event = asyncio.Event()
    async def idle():
        await event.wait()
    monkeypatch.setattr(jobs, "stems_worker", idle)
    yield
    event.set()


@pytest.fixture
def listening(monkeypatch):
    """Everything after the separation, faked: this is about the separation."""
    monkeypatch.setattr(instrumental, "duration_of", lambda path: 60.0)
    async def hear(vocal, seconds=0.0, on_progress=None, on_stage=None, title=""):
        return list(LINES), "Whisper"
    monkeypatch.setattr(jobs, "hear", hear)


@pytest.fixture
def separations(monkeypatch):
    """Counts separations, and writes the vocal where the separator would."""
    calls = []
    async def separate(src, dest, model, wanted, fmt, on_progress=None, work_root=None):
        calls.append((model, wanted, fmt))
        dest.mkdir(parents=True, exist_ok=True)
        (dest / f"vocals.{fmt}").write_bytes(b"fLaC" + b"\0" * 32)
    monkeypatch.setattr(stems, "separate", separate)
    return calls


def a_recording(client):
    path = config.SOURCES_DIR / "0123456789abcdef-modern-girl.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF" + b"\0" * 64)
    execute("""INSERT INTO sources(id, title, filename, stored_path, sha256, created_at, abc, lyrics_state)
               VALUES('src1', 'Modern Girl', 'mg.wav', ?, 'x', ?, '% verse\n', 'queued')""",
            (str(path), time.time()))
    return path


def run():
    asyncio.run(jobs.run_cover_lyrics("src1"))
    return one("SELECT lyrics_state, lyrics FROM sources WHERE id = 'src1'")


def test_the_vocal_is_named_beside_its_recording():
    rec = config.SOURCES_DIR / "0123456789abcdef-modern-girl.wav"
    assert library.vocal_path(rec).name == "0123456789abcdef-modern-girl.vocals.flac"


def test_the_first_run_separates_and_keeps_the_vocal(client, listening, separations):
    rec = a_recording(client)
    assert run()["lyrics_state"] == "done"
    assert separations == [("htdemucs", ["vocals"], "flac")]
    assert library.vocal_path(rec).exists(), "kept beside the recording"


def test_a_second_run_reuses_it_and_does_not_separate(client, listening, separations):
    rec = a_recording(client)
    library.vocal_path(rec).write_bytes(b"fLaC" + b"\0" * 32)
    result = run()
    assert result["lyrics_state"] == "done" and "Modern girl" in result["lyrics"]
    assert separations == [], "separating again would give the same file"


def test_a_failed_separation_keeps_nothing(client, listening, monkeypatch):
    """Nothing half-written is left to be reused as though it were the vocal."""
    async def separate(src, dest, *args, **kwargs):
        dest.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(stems, "separate", separate)
    rec = a_recording(client)
    assert run()["lyrics_state"] == "failed"
    assert not library.vocal_path(rec).exists()


def test_deleting_a_recording_takes_what_was_kept_beside_it(client):
    rec = a_recording(client)
    library.vocal_path(rec).write_bytes(b"fLaC")
    library.peaks_path(rec).write_text("{}")
    assert client.delete("/api/sources/src1").status_code == 200
    assert not rec.exists()
    assert not library.vocal_path(rec).exists()
    assert not library.peaks_path(rec).exists()
