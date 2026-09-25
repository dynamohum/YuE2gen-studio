"""run_job and the stem lane against a fake engine: success, engine errors, the
timeout that starts only once the engine runs the job, cancelling, and a take
deleted while its audio downloads."""
import asyncio
import json
import shutil
import time

import pytest

from app import config, jobs
from app.db import execute, one
from app.library import peaks_path

from conftest import make_take, tone

REAL_SLEEP = asyncio.sleep


class FakeEngine:
    def __init__(self, histories, started=True, state="running", audio=None):
        self.histories = list(histories)
        self.started = started
        self.state = state
        self.audio = audio
        self.last_contact = time.time()
        self.cancelled, self.submitted, self.uploads = [], [], []
        self.on_download = None

    async def submit(self, graph):
        self.submitted.append(graph)
        return "pid"

    async def history(self, prompt_id):
        self.last_contact = time.time()
        return self.histories.pop(0) if self.histories else None

    def has_started(self, prompt_id):
        return self.started

    async def prompt_state(self, prompt_id):
        return self.state

    async def cancel(self, prompt_id):
        self.cancelled.append(prompt_id)

    def forget(self, prompt_id):
        pass

    async def upload(self, name, data):
        self.uploads.append(name)
        return {"name": name}

    async def download(self, item, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.audio, dest)
        if self.on_download:
            self.on_download()
        return dest


def done(outputs, graph, status="success"):
    return {"status": {"status_str": status, "completed": status == "success", "messages": [["x", {}]]},
            "prompt": [0, "pid", graph], "outputs": outputs}


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(jobs.asyncio, "sleep", lambda _s: REAL_SLEEP(0))
    jobs.CANCELLED.clear()
    jobs.CURRENT.clear()


def use(monkeypatch, engine):
    monkeypatch.setattr(jobs, "ENGINE", engine)
    return engine


PLAN_GRAPH = {"3": {"class_type": "PreviewAny"}}
# A plan that passes the score check: a key, a Vocal part with chords, enough bars.
ABC = ('X:1\nM:4/4\nL:1/8\nQ:1/4=100\nV: Vocal clef=treble name="Vocal Melody" snm="Vocal"\nK:C\n'
       '% verse\nV: Vocal\n' + '"C"c4|"Am"A4|"F"F4|"G"G4|' * 4 + '\n')


def test_plan_lands(monkeypatch):
    take = make_take(status="queued")
    engine = use(monkeypatch, FakeEngine([None, done({"3": {"text": [ABC]}}, PLAN_GRAPH)]))
    asyncio.run(jobs.run_job("plan", take["id"]))
    row = one("SELECT * FROM takes WHERE id = ?", (take["id"],))
    assert row["status"] == "planned" and row["abc"] == ABC
    assert not engine.cancelled and not jobs.CURRENT


def test_an_engine_error_fails_at_once_not_after_the_timeout(monkeypatch):
    take = make_take(status="queued")
    use(monkeypatch, FakeEngine([done({}, PLAN_GRAPH, status="error")]))
    started = time.time()
    asyncio.run(jobs.run_job("plan", take["id"]))
    row = one("SELECT * FROM takes WHERE id = ?", (take["id"],))
    assert row["status"] == "failed" and "engine reported error" in row["error"]
    assert time.time() - started < 2


def test_timeout_cancels_the_prompt_on_the_engine(monkeypatch):
    monkeypatch.setitem(config.TIMEOUTS, "plan", 0.05)
    take = make_take(status="queued")
    engine = use(monkeypatch, FakeEngine([]))

    async def run():
        async def slow(_s):
            await REAL_SLEEP(0.02)
        monkeypatch.setattr(jobs.asyncio, "sleep", slow)
        await jobs.run_job("plan", take["id"])
    asyncio.run(run())
    row = one("SELECT * FROM takes WHERE id = ?", (take["id"],))
    assert row["status"] == "failed" and "timed out" in row["error"]
    assert engine.cancelled == ["pid"]


def test_waiting_in_the_engine_queue_does_not_count(monkeypatch):
    monkeypatch.setitem(config.TIMEOUTS, "plan", 0.01)
    take = make_take(status="queued")
    histories = [None] * 20 + [done({"3": {"text": [ABC]}}, PLAN_GRAPH)]
    use(monkeypatch, FakeEngine(histories, started=False, state="pending"))

    async def run():
        async def slow(_s):
            await REAL_SLEEP(0.005)
        monkeypatch.setattr(jobs.asyncio, "sleep", slow)
        await jobs.run_job("plan", take["id"])
    asyncio.run(run())
    assert one("SELECT status FROM takes WHERE id = ?", (take["id"],))["status"] == "planned"


def test_cancel_while_running(monkeypatch):
    take = make_take(status="queued")
    engine = use(monkeypatch, FakeEngine([]))
    jobs.CANCELLED.add(take["id"])
    asyncio.run(jobs.run_job("plan", take["id"]))
    row = one("SELECT * FROM takes WHERE id = ?", (take["id"],))
    assert row["status"] == "failed" and row["error"] == "cancelled"
    assert engine.cancelled == ["pid"] and take["id"] not in jobs.CANCELLED


def test_a_take_that_is_not_queued_is_skipped(monkeypatch):
    take = make_take(status="failed")
    engine = use(monkeypatch, FakeEngine([]))
    asyncio.run(jobs.run_job("render", take["id"]))
    assert not engine.submitted


RENDER_GRAPH = {"16": {"class_type": "SaveAudioAdvanced"}}


def render_history():
    return done({"16": {"audio": [{"filename": "take_00001_.flac", "subfolder": "yue2studio", "type": "output"}]}}, RENDER_GRAPH)


def test_render_saves_audio_note_peaks_and_drops_the_engine_copy(monkeypatch, data_dir):
    engine_out = data_dir / "engine-output"
    engine_copy = tone(engine_out / "yue2studio" / "take_00001_.flac", 1.0)
    monkeypatch.setattr(config, "ENGINE_OUTPUT_DIR", engine_out)
    take = make_take(status="queued", abc=ABC, title="Render Me")
    use(monkeypatch, FakeEngine([render_history()], audio=engine_copy))
    asyncio.run(jobs.run_job("render", take["id"]))
    row = one("SELECT * FROM takes WHERE id = ?", (take["id"],))
    assert row["status"] == "done" and abs(row["duration"] - 1.0) < 0.05
    audio = config.TAKES_DIR / f"render-me-{take['id']}" / "render-me.flac"
    assert row["audio_path"] == str(audio) and audio.exists()
    assert json.loads((audio.parent / "take.json").read_text())["seed"] == 1
    assert peaks_path(audio).exists()
    assert not engine_copy.exists()


def test_a_take_deleted_during_download_leaves_no_folder(monkeypatch, data_dir):
    source_audio = tone(data_dir / "src.flac", 0.5)
    take = make_take(status="queued", abc=ABC, title="Gone")
    engine = use(monkeypatch, FakeEngine([render_history()], audio=source_audio))
    engine.on_download = lambda: execute("DELETE FROM takes WHERE id = ?", (take["id"],))
    asyncio.run(jobs.run_job("render", take["id"]))
    assert not (config.TAKES_DIR / f"gone-{take['id']}").exists()


def test_transcribe_uploads_the_recording_when_it_runs(monkeypatch, data_dir):
    path = tone(config.SOURCES_DIR / "abc-song.wav", 0.5)
    execute("""INSERT INTO sources(id, title, filename, stored_path, sha256, created_at, transcribe_state)
               VALUES('s1', 'Song', 'song.wav', ?, 'abc', 1, 'queued')""", (str(path),))
    graph = {"4": {"class_type": "PreviewAny"}}
    engine = use(monkeypatch, FakeEngine([done({"4": {"text": [ABC]}}, graph)]))
    asyncio.run(jobs.run_job("transcribe", "s1"))
    row = one("SELECT * FROM sources WHERE id = 's1'")
    # Sent as a FLAC with a clean ending, whatever it was uploaded as.
    assert engine.uploads == ["s1.flac"] and row["engine_file"] == "s1.flac"
    assert row["transcribe_state"] == "done" and row["abc"] == ABC
    assert engine.submitted[0]["1"]["inputs"]["audio"] == "s1.flac"


def test_cancelling_a_running_stem_job(monkeypatch, data_dir):
    audio = tone(data_dir / "a.flac", 0.5)
    take = make_take(audio_path=str(audio))
    execute("""INSERT INTO stem_sets(id, take_id, title, model, wanted, fmt, status, created_at, folder)
               VALUES('st1', ?, 't', 'htdemucs', 'vocals', 'wav', 'queued', 1, ?)""", (take["id"], str(data_dir / "stems" / "x")))
    killed = {}

    async def separate(*args, **kwargs):
        try:
            await REAL_SLEEP(30)
        except asyncio.CancelledError:
            killed["yes"] = True
            raise
    monkeypatch.setattr(jobs.stems, "separate", separate)

    async def run():
        worker = asyncio.create_task(jobs.stems_worker())
        await jobs.STEM_QUEUE.put({"id": "st1"})
        for _ in range(200):
            if jobs.CURRENT_STEMS.get("id") == "st1" and one("SELECT status FROM stem_sets WHERE id='st1'")["status"] == "running":
                break
            await REAL_SLEEP(0.01)
        jobs.cancel_stems(one("SELECT * FROM stem_sets WHERE id = 'st1'"))
        for _ in range(200):
            if not jobs.CURRENT_STEMS:
                break
            await REAL_SLEEP(0.01)
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
    asyncio.run(run())
    row = one("SELECT * FROM stem_sets WHERE id = 'st1'")
    assert killed and row["status"] == "failed" and row["error"] == "cancelled"
