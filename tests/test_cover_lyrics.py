"""Hearing the words in a recording: the job, its state, and stopping it."""
import app.jobs as jobs
from app.db import execute, one


def a_source(client, tmp_path):
    path = tmp_path / "song.wav"
    path.write_bytes(b"RIFF" + b"\0" * 64)
    execute("""INSERT INTO sources(id, title, filename, stored_path, sha256, created_at, abc)
               VALUES('src1', 'Song', 'song.wav', ?, 'abc', 1.0, '% intro\n% verse\n')""", (str(path),))
    return "src1"


def test_asking_for_lyrics_queues_a_cpu_job(client, tmp_path):
    source_id = a_source(client, tmp_path)
    r = client.post(f"/api/sources/{source_id}/lyrics")
    assert r.status_code == 200
    assert r.json()["state"] == "queued"
    assert one("SELECT lyrics_state FROM sources WHERE id = ?", (source_id,))["lyrics_state"] == "queued"
    # It goes to the CPU lane, so it cannot hold up a render.
    job = jobs.STEM_QUEUE.get_nowait()
    assert job == {"kind": "lyrics", "id": source_id}


def test_asking_twice_does_not_queue_twice(client, tmp_path):
    source_id = a_source(client, tmp_path)
    client.post(f"/api/sources/{source_id}/lyrics")
    jobs.STEM_QUEUE.get_nowait()
    again = client.post(f"/api/sources/{source_id}/lyrics")
    assert again.json()["state"] == "queued"
    assert jobs.STEM_QUEUE.empty()


def test_the_state_reads_back(client, tmp_path):
    source_id = a_source(client, tmp_path)
    execute("UPDATE sources SET lyrics_state = 'running', lyrics_progress = 0.4,"
            " lyrics_stage = 'Listening for words' WHERE id = ?", (source_id,))
    body = client.get(f"/api/sources/{source_id}/lyrics").json()
    assert (body["state"], body["progress"], body["stage"]) == ("running", 0.4, "Listening for words")


def test_a_queued_job_can_be_stopped(client, tmp_path):
    source_id = a_source(client, tmp_path)
    client.post(f"/api/sources/{source_id}/lyrics")
    jobs.STEM_QUEUE.get_nowait()
    client.delete(f"/api/sources/{source_id}/lyrics")
    row = one("SELECT lyrics_state, lyrics_error FROM sources WHERE id = ?", (source_id,))
    assert (row["lyrics_state"], row["lyrics_error"]) == ("failed", "cancelled")


def test_a_recording_with_no_file_is_refused(client, tmp_path):
    execute("""INSERT INTO sources(id, title, filename, stored_path, sha256, created_at)
               VALUES('gone', 'Gone', 'g.wav', '/nowhere/g.wav', 'x', 1.0)""")
    assert client.post("/api/sources/gone/lyrics").status_code == 400


def test_the_list_says_whether_words_were_heard(client, tmp_path):
    source_id = a_source(client, tmp_path)
    assert client.get("/api/sources").json()[0]["has_lyrics"] == 0
    execute("UPDATE sources SET lyrics = '[Verse]\nwords' WHERE id = ?", (source_id,))
    assert client.get("/api/sources").json()[0]["has_lyrics"] == 1
