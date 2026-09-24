"""A quiet take can be brought up to the usual loudness when asked, and put back.
Nothing is normalised without being asked."""
import subprocess
from pathlib import Path

from app import config
from app.db import one
from app.library import loudness, original_path

from conftest import make_take


def quiet_tone(path):
    """A 44.1 kHz stereo tone far below the usual level, like a weak render."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "quiet", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                    "-af", "volume=0.15", "-ac", "2", "-ar", "44100", str(path)], check=True)
    return path


def rate_of(path):
    return subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "stream=sample_rate", "-of", "csv=p=0", str(path)],
                          capture_output=True, text=True, check=True).stdout.strip()


def test_normalising_lifts_a_weak_take_and_keeps_the_rendered_file(client, tmp_path):
    audio = quiet_tone(tmp_path / "takes" / "t1" / "song.flac")
    before = loudness(audio)
    take = make_take(audio_path=str(audio))
    assert before < config.WEAK_RENDER_DB

    answer = client.post(f"/api/takes/{take['id']}/normalise").json()
    assert answer["normalised"] and answer["loudness"] > config.WEAK_RENDER_DB
    assert original_path(audio).exists() and loudness(original_path(audio)) == before
    assert rate_of(audio) == "44100", "loudnorm works at 192 kHz; the take comes back at its own rate"
    row = one("SELECT normalised, loudness FROM takes WHERE id = ?", (take["id"],))
    assert row["normalised"] == 1 and row["loudness"] == answer["loudness"]

    # Twice gives the same: it always starts from the file as rendered.
    again = client.post(f"/api/takes/{take['id']}/normalise").json()
    assert abs(again["loudness"] - answer["loudness"]) < 0.2


def test_undo_puts_back_the_rendered_level(client, tmp_path):
    audio = quiet_tone(tmp_path / "takes" / "t2" / "song.flac")
    before = loudness(audio)
    take = make_take(audio_path=str(audio))
    client.post(f"/api/takes/{take['id']}/normalise")

    answer = client.post(f"/api/takes/{take['id']}/normalise?undo=true").json()
    assert answer == {"normalised": False, "loudness": before}
    assert not original_path(audio).exists()
    assert one("SELECT normalised FROM takes WHERE id = ?", (take["id"],))["normalised"] == 0
    assert client.post(f"/api/takes/{take['id']}/normalise?undo=true").status_code == 409


def test_a_take_is_left_as_rendered_unless_asked(client, tmp_path):
    audio = quiet_tone(tmp_path / "takes" / "t3" / "song.flac")
    make_take(audio_path=str(audio))
    listed = client.get("/api/takes").json()[0]
    assert listed["normalise"] == 0 and listed["normalised"] == 0 and not original_path(audio).exists()


def test_a_take_without_audio_cannot_be_normalised(client):
    take = make_take()
    assert client.post(f"/api/takes/{take['id']}/normalise").status_code == 404


def test_a_take_asked_to_be_normalised_is_when_its_render_finishes(monkeypatch, data_dir):
    import asyncio

    from app import jobs
    from app.db import execute
    from test_jobs import ABC, FakeEngine, render_history, use

    rendered = quiet_tone(data_dir / "engine" / "take_00001_.flac")
    monkeypatch.setattr(config, "ENGINE_OUTPUT_DIR", data_dir / "engine-output")
    take = make_take(status="queued", abc=ABC, title="Quiet")
    execute("UPDATE takes SET normalise = 1 WHERE id = ?", (take["id"],))
    use(monkeypatch, FakeEngine([render_history()], audio=rendered))
    asyncio.run(jobs.run_job("render", take["id"]))
    row = one("SELECT * FROM takes WHERE id = ?", (take["id"],))
    assert row["status"] == "done" and row["normalised"] == 1 and row["loudness"] > config.WEAK_RENDER_DB
    assert original_path(Path(row["audio_path"])).exists()


def test_the_form_choice_is_kept_on_the_take(client):
    made = client.post("/api/songs", json={"lyrics": "[Verse]\nla la", "normalise": True}).json()
    assert one("SELECT normalise FROM takes WHERE id = ?", (made["id"],))["normalise"] == 1
    plain = client.post("/api/songs", json={"lyrics": "[Verse]\nla la"}).json()
    assert one("SELECT normalise FROM takes WHERE id = ?", (plain["id"],))["normalise"] == 0
