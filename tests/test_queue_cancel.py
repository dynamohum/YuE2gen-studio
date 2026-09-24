"""A job waiting in Up next can be taken back before it starts.  An analysis or a
transcription goes back to what it was, so cancelling a re-run keeps the old result."""
import pytest

from app.db import execute, one
from app.jobs import CURRENT, QUEUE

from conftest import make_take


@pytest.fixture(autouse=True)
def empty_queue():
    CURRENT.clear()
    while not QUEUE.empty():
        QUEUE.get_nowait()
    yield
    while not QUEUE.empty():
        QUEUE.get_nowait()


def corpus_song(**fields):
    song = {"id": "song-1", "title": "No More Lonely Nights", "style_hint": None, "key": None, "tempo": None,
            "score_state": "none", "style_state": "none"}
    song.update(fields)
    execute("INSERT INTO identities(id, name, trigger_word, folder, created_at) VALUES('id-1', 'Paul McCartney', 'macca', '/tmp/m', 1.0)")
    execute("""INSERT INTO identity_songs(id, identity_id, file, title, sha256, key, tempo, style_hint, score_state, style_state)
               VALUES(:id, 'id-1', 'song.flac', :title, 'x', :key, :tempo, :style_hint, :score_state, :style_state)""", song)
    return song


def test_cancelling_a_style_rerun_keeps_the_earlier_style(client):
    corpus_song(style_hint="melodic pop, piano ballad", style_state="done")
    client.post("/api/identities/id-1/songs/song-1/style")
    queue = client.get("/api/state").json()["queue"]
    assert [(q["kind"], q["title"]) for q in queue] == [("identity_style", "Style: No More Lonely Nights")]

    assert client.post("/api/queue/identity_style/song-1/cancel").json() == {"cancelled": True}
    song = one("SELECT style_state, style_hint FROM identity_songs WHERE id = 'song-1'")
    assert (song["style_state"], song["style_hint"]) == ("done", "melodic pop, piano ballad")
    assert client.get("/api/state").json()["queue"] == []


def test_cancelling_a_first_analysis_leaves_it_undone(client):
    corpus_song(score_state="queued")
    assert client.post("/api/queue/identity_score/song-1/cancel").json() == {"cancelled": True}
    assert one("SELECT score_state FROM identity_songs WHERE id = 'song-1'")["score_state"] == "none"


def test_a_running_analysis_is_not_cancelled_from_the_queue(client):
    corpus_song(style_state="running")
    assert client.post("/api/queue/identity_style/song-1/cancel").json() == {"cancelled": False}
    assert one("SELECT style_state FROM identity_songs WHERE id = 'song-1'")["style_state"] == "running"


def test_cancelling_a_transcription_keeps_the_score_it_had(client):
    execute("""INSERT INTO sources(id, title, filename, stored_path, sha256, created_at, abc, transcribe_state)
               VALUES('src1', 'Song', 'song.wav', '/tmp/song.wav', 'abc', 1.0, 'X:1', 'queued')""")
    assert client.post("/api/queue/transcribe/src1/cancel").json() == {"cancelled": True}
    assert one("SELECT transcribe_state FROM sources WHERE id = 'src1'")["transcribe_state"] == "done"


def test_cancelling_a_waiting_take(client):
    take = make_take(status="queued")
    QUEUE.put_nowait({"kind": "render", "id": take["id"]})
    assert client.post(f"/api/queue/render/{take['id']}/cancel").json() == {"cancelled": True}
    assert one("SELECT status, error FROM takes WHERE id = ?", (take["id"],)) == {"status": "failed", "error": "cancelled"}
    assert client.get("/api/state").json()["queue"] == []


def test_an_unknown_kind_is_not_cancelled(client):
    assert client.post("/api/queue/train/whatever/cancel").json() == {"cancelled": False}
