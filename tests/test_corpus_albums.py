"""A whole album in one file: too long to analyse, split by its cue sheet; and
stopping a corpus's analysis, which runs on two lanes."""
import asyncio
from pathlib import Path

import pytest

from app import config, identities, jobs, stems
from app.db import execute, one

from conftest import tone

CUE = '''REM GENRE Rock
PERFORMER "The Band"
TITLE "The Album"
FILE "Album.wav" WAVE
  TRACK 01 AUDIO
    TITLE "First Song"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Second Song"
    PERFORMER "Someone Else"
    INDEX 00 03:18:00
    INDEX 01 03:20:00
  TRACK 03 AUDIO
    TITLE "Third Song"
    INDEX 01 06:40:37
'''


@pytest.fixture(autouse=True)
def corpora_built_in(monkeypatch):
    monkeypatch.setattr(config, "TRAINING_ENABLED", True)


def album_folder(tmp_path, monkeypatch):
    root = tmp_path / "import"
    folder = root / "Albums"
    folder.mkdir(parents=True)
    monkeypatch.setattr(config, "IMPORT_ROOTS", [str(root)])
    tone(folder / "Album.flac", 610)
    (folder / "Album.cue").write_text(CUE, encoding="utf-8")
    tone(folder / "A Single.flac", 100)
    return folder


def test_a_cue_sheet_is_read_for_its_tracks():
    [entry] = identities.parse_cue(CUE)
    assert entry["file"] == "Album.wav"
    assert [t["title"] for t in entry["tracks"]] == ["First Song", "Second Song", "Third Song"]
    assert [round(t["start"], 2) for t in entry["tracks"]] == [0.0, 200.0, 400.49]    # INDEX 01; 37/75 s
    assert [t["performer"] for t in entry["tracks"]] == ["The Band", "Someone Else", "The Band"]


def test_a_recording_longer_than_ten_minutes_is_flagged_and_its_cue_found(tmp_path, monkeypatch):
    folder = album_folder(tmp_path, monkeypatch)
    found = {s["file"]: s for s in identities.scan(folder)}
    assert (found["Album.flac"]["include"], found["Album.flac"]["flag"]) == (False, "longer than 10 minutes")
    assert found["A Single.flac"]["include"]
    # The sheet names Album.wav: an album converted to FLAC after it was ripped.
    assert len(identities.cue_for(folder / "Album.flac")["tracks"]) == 3
    assert identities.cue_for(folder / "A Single.flac") is None


def test_an_album_is_split_into_songs_in_its_place(client, tmp_path, monkeypatch):
    async def hold(song_id):
        return None
    monkeypatch.setattr(jobs, "prepare_song", hold)
    folder = album_folder(tmp_path, monkeypatch)
    made = client.post("/api/identities", json={"name": "Band", "trigger_word": "band", "folder": str(folder),
                                                "consent": True}).json()
    album = next(s for s in made["songs"] if s["file"] == "Album.flac")
    assert album["too_long"] and album["cue"] == {"file": "Album.cue", "tracks": 3}
    url = f"/api/identities/{made['id']}/songs/{album['id']}"
    assert client.put(url, json={"include": True}).status_code == 400          # split it first
    assert client.post(f"/api/identities/{made['id']}/analyse").json() == {"queued": 1}   # only the single

    view = client.post(url + "/split").json()
    titles = [s["title"] for s in view["songs"]]
    assert titles == ["A Single", "First Song", "Second Song", "Third Song"]     # in the album's place
    tracks = [s for s in view["songs"] if s["title"] != "A Single"]
    assert [round(s["duration"]) for s in tracks] == [200, 200, 210]
    assert all(s["include"] and not s["too_long"] for s in tracks)
    for track in tracks:
        path = Path(track["file"])
        assert identities.is_track(path) and path.is_file()
    # Each track names its performer, from the sheet.
    assert [identities.probe(Path(t["file"]))["artist"] for t in tracks] == ["The Band", "Someone Else", "The Band"]
    assert sorted(p.name for p in folder.iterdir()) == ["A Single.flac", "Album.cue", "Album.flac"]   # only read
    assert one("SELECT id FROM identity_songs WHERE id = ?", (album["id"],)) is None
    assert client.post(url + "/split").status_code == 404


def test_a_too_long_song_is_never_separated(tmp_path, monkeypatch):
    folder = album_folder(tmp_path, monkeypatch)
    execute("""INSERT INTO identities(id, name, trigger_word, folder, consent, created_at)
               VALUES('c1', 'Band', 'band', ?, 1, 0)""", (str(folder),))
    execute("""INSERT INTO identity_songs(id, identity_id, file, title, sha256, duration, include, vocals_state, lyrics_state, position)
               VALUES('s1', 'c1', 'Album.flac', 'Album', 'x', 610, 1, 'queued', 'queued', 0)""")
    asyncio.run(jobs.prepare_song("s1"))
    row = one("SELECT * FROM identity_songs WHERE id = 's1'")
    assert (row["vocals_state"], row["lyrics_state"], row["stored_path"]) == ("none", "none", None)
    assert "split it into tracks" in row["error"]


def test_stop_ends_the_separation_and_leaves_nothing_looking_busy(tmp_path, monkeypatch):
    folder = album_folder(tmp_path, monkeypatch)
    execute("""INSERT INTO identities(id, name, trigger_word, folder, consent, created_at)
               VALUES('c1', 'Band', 'band', ?, 1, 0)""", (str(folder),))
    execute("""INSERT INTO identity_songs(id, identity_id, file, title, sha256, duration, include, vocals_state, lyrics_state, position)
               VALUES('s1', 'c1', 'A Single.flac', 'A Single', 'x', 100, 1, 'queued', 'queued', 0)""")
    execute("""INSERT INTO identity_songs(id, identity_id, file, title, sha256, duration, include, vocals_state, lyrics_state, position)
               VALUES('s2', 'c1', 'A Single.flac', 'Waiting', 'y', 100, 1, 'queued', 'queued', 1)""")
    killed = {}

    async def separate(src, dest, model, wanted, fmt, on_progress=None, work_root=None):
        on_progress(0.4, "")
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            killed["yes"] = True
            raise
    monkeypatch.setattr(stems, "separate", separate)

    async def run():
        # A queue of this loop's own: an earlier test's app may have used the shared one.
        monkeypatch.setattr(jobs, "IDENTITY_QUEUE", asyncio.Queue())
        worker = asyncio.create_task(jobs.identity_worker())
        await jobs.IDENTITY_QUEUE.put({"id": "s1"})
        await jobs.IDENTITY_QUEUE.put({"id": "s2"})
        for _ in range(200):
            if jobs.CURRENT_IDENTITY.get("progress") == 0.4:
                break
            await asyncio.sleep(0.01)
        working = jobs.identity_working({"s1", "s2"})
        assert working["song"] == "A Single" and working["stage"].startswith("Separating the vocal")
        assert working["progress"] == 0.4
        # The GPU step queued beside it goes too.
        jobs.set_song("s1", score_state="queued")
        assert await jobs.stop_identity_analysis("c1") == 2
        for _ in range(200):
            if not jobs.CURRENT_IDENTITY and jobs.IDENTITY_QUEUE.empty():
                break
            await asyncio.sleep(0.01)
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker
    asyncio.run(run())
    assert killed.get("yes")
    for sid in ("s1", "s2"):
        row = one("SELECT * FROM identity_songs WHERE id = ?", (sid,))
        assert (row["vocals_state"], row["lyrics_state"], row["score_state"], row["error"]) == ("none", "none", "none", "stopped")
    while not jobs.QUEUE.empty():
        jobs.QUEUE.get_nowait()


def test_a_cancelled_score_does_not_leave_the_lyrics_waiting(tmp_path):
    folder = tmp_path / "song"
    folder.mkdir()
    (folder / "original.flac").write_bytes(b"x")
    execute("""INSERT INTO identity_songs(id, identity_id, file, title, sha256, duration, include, vocals_state,
                                          lyrics_state, score_state, stored_path, position)
               VALUES('s1', 'c1', 'a.flac', 'A', 'x', 100, 1, 'none', 'none', 'failed', ?, 0)""",
            (str(folder / "original.flac"),))
    jobs.maybe_draft("s1")      # Whisper never ran: nothing to wait for
    assert one("SELECT lyrics_state FROM identity_songs WHERE id = 's1'")["lyrics_state"] == "none"


def test_a_stopped_gpu_step_goes_back_to_not_started(monkeypatch):
    execute("""INSERT INTO identity_songs(id, identity_id, file, title, sha256, duration, include, score_state,
                                          stored_path, position)
               VALUES('s1', 'c1', 'a.flac', 'A', 'x', 100, 1, 'queued', '/nowhere/a.flac', 0)""")

    async def run():
        async def engine_job(*args):
            await jobs.stop_song_analysis("s1")      # pressed while the engine works on it
            raise RuntimeError("cancelled")
        monkeypatch.setattr(jobs, "_run_graph", engine_job)
        monkeypatch.setattr(jobs, "_without_tags", lambda source, folder: source)
        async def upload(path, name):
            return name
        monkeypatch.setattr(jobs, "_upload", upload)
        monkeypatch.setitem(jobs.CURRENT, "kind", "identity_score")
        monkeypatch.setitem(jobs.CURRENT, "id", "s1")
        await jobs.run_identity_job("identity_score", "s1")
    asyncio.run(run())
    row = one("SELECT score_state, error FROM identity_songs WHERE id = 's1'")
    assert (row["score_state"], row["error"]) == ("none", "stopped")


def test_a_track_is_linked_into_its_song_not_copied(tmp_path):
    track = tone(identities.tracks_dir("c1") / "album-a1" / "01 First.flac", 3)
    stored = tmp_path / "songs" / "first" / "original.flac"
    stored.parent.mkdir(parents=True)
    jobs._store_original(track, stored)
    assert stored.stat().st_ino == track.stat().st_ino and track.stat().st_nlink == 2
    # A song from the user's own folder is still copied: that folder may change.
    own = tone(tmp_path / "import" / "Song.flac", 3)
    kept = tmp_path / "songs" / "song" / "original.flac"
    kept.parent.mkdir(parents=True)
    jobs._store_original(own, kept)
    assert kept.stat().st_ino != own.stat().st_ino and own.stat().st_nlink == 1


def test_style_analysis_sends_the_title_and_words_never_an_artist(tmp_path, monkeypatch):
    """The corpus name is whatever the folder was called: 'pepper' had Sgt. Pepper
    described as reggae rock, after the band Pepper.  A file's artist tag is not sent
    either."""
    import subprocess
    from app import llm
    song = tmp_path / "song.flac"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=duration=2", "-metadata", "artist=Pepper",
                    str(song)], check=True)
    execute("INSERT INTO identities(id, name, trigger_word, folder, consent, created_at) VALUES('c1', 'pepper', 'pepper', '/x', 1, 0)")
    execute("""INSERT INTO identity_songs(id, identity_id, file, title, sha256, duration, include, style_state, stored_path,
                                          lyrics, position)
               VALUES('s1', 'c1', 'a.flac', 'Lovely Rita', 'x', 100, 1, 'queued', ?, 'Lovely Rita, meter maid', 0)""", (str(song),))
    asked = {}

    async def describe(**kwargs):
        asked.update(kwargs)
        return "music hall, piano"
    monkeypatch.setattr(llm, "is_external_enabled", lambda: True)
    monkeypatch.setattr(llm, "describe_song_style", describe)
    asyncio.run(jobs.run_identity_job("identity_style", "s1"))
    assert asked == {"title": "Lovely Rita", "lyrics_text": "Lovely Rita, meter maid"}
    assert one("SELECT style_state FROM identity_songs WHERE id = 's1'")["style_state"] == "done"


def test_an_engine_error_names_the_node_and_its_exception_not_its_inputs():
    job = {"status": {"status_str": "error", "messages": [
        ["execution_start", {"prompt_id": "p"}],
        ["execution_error", {"node_type": "SheetSage2AudioToABC", "exception_type": "comfy.audio_encoders.sheetsage2_abc.MelodyVoiceError",
                             "exception_message": "Vocal: note pitch=71 at 315.513000-315.533000 cannot be represented\non the decoded subbeat grid",
                             "current_inputs": {"audio": ["0.0010, 0.0006, " * 500]}}]]}}
    assert jobs._engine_error(job) == ("SheetSage2AudioToABC: MelodyVoiceError: Vocal: note pitch=71 at 315.513000-315.533000 "
                                       "cannot be represented on the decoded subbeat grid")


def test_a_failed_transcription_is_tried_again_with_a_clean_ending(tmp_path, monkeypatch):
    """Faded and padded with silence, so no note is sounding when the audio ends;
    then melody-only, then the first four minutes, each ended the same way."""
    folder = tmp_path / "song"
    original = tone(folder / "original.flac", 250)
    execute("""INSERT INTO identity_songs(id, identity_id, file, title, sha256, duration, include, score_state, stored_path, position)
               VALUES('s1', 'c1', 'a.flac', 'A Day In The Life', 'x', 250, 1, 'queued', ?, 0)""", (str(original),))
    tried = []

    async def upload(path, name):
        return str(path)

    async def engine(kind, ref_id, graph):
        mode, sent = graph["3"]["inputs"]["mode"], Path(graph["1"]["inputs"]["audio"])
        tried.append((mode, round(identities.probe(sent)["duration"])))
        if len(tried) < 4:
            raise RuntimeError("engine error: SheetSage2AudioToABC: MelodyVoiceError: cannot be represented")
        return {"outputs": {"4": {"text": ["X:1\nK:E\nQ:1/4=80\n|E|F|G|A|B|"]}}}
    monkeypatch.setattr(jobs, "_upload", upload)
    monkeypatch.setattr(jobs, "_run_graph", engine)
    monkeypatch.setattr(jobs, "extract_text_output", lambda job, *types: job["outputs"]["4"]["text"][0])
    asyncio.run(jobs.run_identity_job("identity_score", "s1"))
    assert tried == [("full", 250), ("full", 255), ("melody", 255), ("full", 245)]     # four minutes and five of silence
    row = one("SELECT score_state, key FROM identity_songs WHERE id = 's1'")
    assert (row["score_state"], row["key"]) == ("done", "E major")


def test_a_stopped_transcription_is_not_tried_again(tmp_path, monkeypatch):
    folder = tmp_path / "song"
    original = tone(folder / "original.flac", 5)
    execute("""INSERT INTO identity_songs(id, identity_id, file, title, sha256, duration, include, score_state, stored_path, position)
               VALUES('s1', 'c1', 'a.flac', 'A', 'x', 5, 1, 'queued', ?, 0)""", (str(original),))
    calls = []

    async def upload(path, name):
        return str(path)

    async def engine(kind, ref_id, graph):
        calls.append(1)
        raise RuntimeError("cancelled")
    monkeypatch.setattr(jobs, "_upload", upload)
    monkeypatch.setattr(jobs, "_run_graph", engine)
    asyncio.run(jobs.run_identity_job("identity_score", "s1"))
    assert calls == [1]
    assert one("SELECT score_state FROM identity_songs WHERE id = 's1'")["score_state"] == "failed"
