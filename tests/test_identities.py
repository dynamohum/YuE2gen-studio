"""Identities: scanning a folder (read only), flags, chunking, captions, the API."""
import numpy as np

from app import config, identities, jobs, personas
from app.db import one
from app.jobs import IDENTITY_QUEUE, PERSONA_QUEUE

from conftest import tone


def make_folder(tmp_path, monkeypatch):
    root = tmp_path / "import"
    songs = root / "Under"
    songs.mkdir(parents=True)
    monkeypatch.setattr(config, "IMPORT_ROOTS", [str(root)])
    tone(songs / "01 Modern Girl.wav", 100)
    (songs / "Modern Girl copy.wav").write_bytes((songs / "01 Modern Girl.wav").read_bytes())
    tone(songs / "02 Falling.wav", 95)
    tone(songs / "09 Falling (acoustic).wav", 96)
    tone(songs / "14. Did It Ever (Ft. Alan Williams on vocals).wav", 101)
    tone(songs / "08 It's Only Love Short.wav", 30)
    tone(songs / "did_it_ever.wav", 102)
    (songs / "cover.jpg").write_bytes(b"not audio")
    return root, songs


def test_scan_flags_copies_versions_other_singers_and_short_files(tmp_path, monkeypatch):
    _, folder = make_folder(tmp_path, monkeypatch)
    found = {s["file"]: s for s in identities.scan(folder)}
    assert "cover.jpg" not in found and len(found) == 7
    assert "names another singer" in found["did_it_ever.wav"]["flag"]
    assert found["01 Modern Girl.wav"]["include"] and found["01 Modern Girl.wav"]["title"] == "Modern Girl"
    assert "exact copy" in found["Modern Girl copy.wav"]["flag"]
    assert "another version" in found["09 Falling (acoustic).wav"]["flag"]
    assert "another singer" in found["14. Did It Ever (Ft. Alan Williams on vocals).wav"]["flag"]
    assert "shorter" in found["08 It's Only Love Short.wav"]["flag"]
    assert [s["file"] for s in found.values() if s["include"]] == ["01 Modern Girl.wav", "02 Falling.wav"]


def test_folders_outside_the_import_roots_are_refused(tmp_path, monkeypatch):
    make_folder(tmp_path, monkeypatch)
    assert not identities.allowed(tmp_path)
    # The drop folder is a root too, but it is not listed until it exists.
    assert identities.browse(None)["folders"] == [str(tmp_path / "import")]
    assert identities.browse(str(tmp_path / "import"))["folders"] == [str(tmp_path / "import" / "Under")]


def test_the_drop_folder_is_offered_and_readable(tmp_path, monkeypatch):
    """A user copies songs into one folder and needs to know nothing else."""
    make_folder(tmp_path, monkeypatch)
    config.CORPUS_INBOX.mkdir(parents=True, exist_ok=True)
    tone(config.CORPUS_INBOX / "My Song.wav", 100)

    assert identities.allowed(config.CORPUS_INBOX)
    assert str(config.CORPUS_INBOX) in identities.browse(None)["folders"]
    assert [s["file"] for s in identities.scan(config.CORPUS_INBOX)] == ["My Song.wav"]


def test_chunks_cut_at_quiet_points_and_skip_silence():
    rate = identities.CHUNK_RATE
    t = np.arange(rate * 70) / rate
    voice = 0.5 * np.sin(2 * np.pi * 220 * t)
    voice[: rate * 5] = 0                                  # 5 s of silence at the start
    voice[rate * 22: rate * 23] *= 0.001                   # a breath at 22 s
    chunks = identities.sung_chunks(voice.astype(np.float32))
    assert chunks[0][0] >= 4.9 and all(b - a <= identities.CHUNK_MAX + 0.1 for a, b in chunks)
    assert abs(chunks[0][1] - 22.0) < 1.1                  # the first cut lands on the breath


def test_key_tempo_and_caption():
    assert identities.key_and_tempo("X:1\nQ:1/4=70\nK:Dm\n") == ("D minor", 70)
    assert identities.key_and_tempo("K:Bb\n") == ("Bb major", None)
    assert identities.caption("pshields", "pop rock, guitars", "male", "D minor", 70) == "pshields, pop rock, guitars, male vocal, key of D minor, 70 BPM"


def test_score_sections_count_bars_by_time_signature():
    abc = ("X:1\nM:4/4\nV: Vocal\nV: Ins\nK:C\n% intro\nV: Vocal\n|z4|z4|\nV: Ins\n|c4|c4|\n"
           "% verse\nV: Vocal\nM:2/4\n|c2|d2|e2|f2|\n% interlude\nV: Vocal\nM:4/4\n|z4|\n% nonsense\n|z4|\n")
    assert identities.score_sections(abc) == [("intro", 2.0), ("verse", 2.0), ("interlude", 2.0)]


def test_lines_are_tagged_by_the_section_playing():
    lines = [{"start": 1, "end": 4, "text": "first verse line"}, {"start": 28, "end": 30, "text": "a chorus line"},
             {"start": 31, "end": 34, "text": "the chorus again"}, {"start": 58, "end": 59, "text": "last words"}]
    sections = [("intro", 1.0), ("verse", 2.0), ("chorus", 2.0), ("interlude", 1.0), ("outro", 0.5)]
    # 60 s over 6.5 lengths: intro 0-9.2, verse 9.2-27.7, chorus 27.7-46.2, interlude as bridge, outro 55.4-60.
    assert identities.tag_lyrics(lines, sections, 60) == (
        "[Intro]\nfirst verse line\n\n[Verse]\n\n[Chorus]\na chorus line\nthe chorus again\n\n[Bridge]\n\n[Outro]\nlast words")
    assert identities.tag_lyrics(lines, [], 60).startswith("[Verse]\nfirst verse line")
    assert identities.tag_lyrics([], sections, 60) == ""


def test_api_needs_consent_scans_and_queues(client, tmp_path, monkeypatch):
    async def hold(song_id):   # the worker is running: keep it from separating test tones
        return None
    monkeypatch.setattr(jobs, "prepare_song", hold)
    _, folder = make_folder(tmp_path, monkeypatch)
    body = {"name": "Me", "trigger_word": "P Shields!", "description": "pop rock", "voice": "Male", "folder": str(folder)}
    assert client.post("/api/identities", json=body).status_code == 400
    assert client.post("/api/identities", json={**body, "consent": True, "folder": str(tmp_path)}).status_code == 400
    made = client.post("/api/identities", json={**body, "consent": True}).json()
    assert made["trigger_word"] == "pshields" and made["summary"]["included"] == 2
    song = next(s for s in made["songs"] if s["include"])
    assert song["caption"].startswith("pshields, pop rock, male vocal")
    assert client.put(f"/api/identities/{made['id']}/songs/{song['id']}", json={"lyrics": "[Verse]\nla", "lyrics_checked": True}).status_code == 200
    client.put(f"/api/identities/{made['id']}/songs/{song['id']}", json={"description": "  stripped back,   acoustic guitar "})
    view = client.get(f"/api/identities/{made['id']}").json()
    caption = next(s["caption"] for s in view["songs"] if s["id"] == song["id"])
    assert caption.startswith("pshields, stripped back, acoustic guitar, male vocal")     # this song's own sound
    other = next(s for s in view["songs"] if s["include"] and s["id"] != song["id"])
    assert other["caption"].startswith("pshields, pop rock, male vocal")                  # the rest keep the identity's
    while not IDENTITY_QUEUE.empty():
        IDENTITY_QUEUE.get_nowait()
    assert client.post(f"/api/identities/{made['id']}/analyse").json() == {"queued": 2}
    assert one("SELECT vocals_state FROM identity_songs WHERE id = ?", (song["id"],))["vocals_state"] == "queued"
    # Backward compatibility view also works
    assert one("SELECT vocals_state FROM persona_songs WHERE id = ?", (song["id"],))["vocals_state"] == "queued"
    assert client.post(f"/api/identities/{made['id']}/analyse").json() == {"queued": 0}   # nothing twice
    while not IDENTITY_QUEUE.empty():
        IDENTITY_QUEUE.get_nowait()
    assert client.delete(f"/api/identities/{made['id']}").json() == {"deleted": True}
    assert (folder / "01 Modern Girl.wav").exists()           # the original folder is untouched


def test_a_song_unticked_while_it_waits_is_skipped(client, tmp_path, monkeypatch):
    import asyncio
    _, folder = make_folder(tmp_path, monkeypatch)
    made = client.post("/api/identities", json={"name": "Me", "trigger_word": "me", "folder": str(folder), "consent": True}).json()
    song = next(s for s in made["songs"] if s["include"])
    jobs.set_song(song["id"], include=0, vocals_state="queued", lyrics_state="queued", score_state="queued")
    asyncio.run(jobs.prepare_song(song["id"]))
    asyncio.run(jobs.run_identity_job("identity_score", song["id"]))
    row = one("SELECT * FROM identity_songs WHERE id = ?", (song["id"],))
    assert (row["vocals_state"], row["lyrics_state"], row["score_state"], row["stored_path"]) == ("none", "none", "none", None)


def test_editing_the_identity_changes_captions_and_export_names_the_host_folder(client, tmp_path, monkeypatch):
    _, folder = make_folder(tmp_path, monkeypatch)
    made = client.post("/api/identities", json={"name": "Me", "trigger_word": "me", "voice": "male", "folder": str(folder), "consent": True}).json()
    edited = client.put(f"/api/identities/{made['id']}", json={"description": "pop rock, electric guitars, bass, drums"}).json()
    assert all(s["caption"].startswith("me, pop rock, electric guitars, bass, drums, male vocal") for s in edited["songs"])
    song = next(s for s in edited["songs"] if s["include"])
    jobs.set_song(song["id"], stored_path=str(folder / "01 Modern Girl.wav"), lyrics="[Verse]\nla")
    monkeypatch.setattr(config, "DATA_DIR_HOST", "/home/me/yue2/data")
    out = client.post(f"/api/identities/{made['id']}/export").json()
    assert out["folder"] == f"/home/me/yue2/data/identities/{made['id']}/dataset" and len(out["written"]) == 1
