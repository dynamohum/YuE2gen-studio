import asyncio
import io
import time
import zipfile

from app import config
from app.db import execute, one

from conftest import make_take, tone


def test_starts_with_the_engine_offline(client):
    state = client.get("/api/state").json()
    assert state["engine"]["online"] is False
    assert "{{VERSION}}" not in client.get("/").text


def test_unknown_host_is_refused(client):
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 421


def test_cross_site_write_is_refused(client):
    take = make_take()
    url = f"/api/takes/{take['id']}/favourite"
    assert client.post(url, headers={"origin": "http://evil.example"}).status_code == 403
    assert client.post(url, headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert client.post(url, headers={"origin": "http://localhost"}).status_code == 200
    assert client.post("/api/takes/nope/favourite").status_code == 404


def test_upload_dedupes_and_limits_size(client):
    first = client.post("/api/sources", files={"file": ("My Song.wav", b"RIFF" + b"1" * 1000)}).json()
    assert first["duplicate"] is False and first["engine_file"] is None
    again = client.post("/api/sources", files={"file": ("copy.wav", b"RIFF" + b"1" * 1000)}).json()
    assert again["duplicate"] is True and again["id"] == first["id"]
    big = client.post("/api/sources", files={"file": ("big.wav", b"0" * (2 * 1024 * 1024))})
    assert big.status_code == 413
    assert not list(config.WORK_DIR.glob("upload-*"))


def test_transcribe_refuses_a_second_run(client):
    source = client.post("/api/sources", files={"file": ("s.wav", b"abc")}).json()
    execute("UPDATE sources SET transcribe_state = 'running' WHERE id = ?", (source["id"],))
    assert client.post(f"/api/sources/{source['id']}/transcribe").status_code == 409


def test_render_and_replan_refuse_a_busy_take(client):
    take = make_take(status="queued", abc="X:1" * 30)
    assert client.post(f"/api/takes/{take['id']}/render").status_code == 409
    assert client.post(f"/api/takes/{take['id']}/replan").status_code == 409


def test_cancel_a_queued_take(client):
    take = make_take(status="queued")
    assert client.post(f"/api/takes/{take['id']}/cancel").json()["cancelled"] is True
    row = one("SELECT * FROM takes WHERE id = ?", (take["id"],))
    assert row["status"] == "failed" and row["error"] == "cancelled"


def test_request_limits(client):
    assert client.post("/api/songs", json={"lyrics": "la", "max_duration": 5}).status_code == 422
    assert client.post("/api/songs", json={"lyrics": "la", "seed": -1}).status_code == 422
    assert client.put("/api/settings", json={"key": "stems.folder", "value": "/etc"}).status_code == 400


def _take_with_stems(data_dir):
    take = make_take(title="Has Stems")
    audio = tone(config.TAKES_DIR / f"has-stems-{take['id']}" / "has-stems.flac", 0.5)
    execute("UPDATE takes SET audio_path = ? WHERE id = ?", (str(audio), take["id"]))
    folder = config.STEMS_DIR / f"has-stems-st1"
    tone(folder / "vocals.wav", 0.3)
    tone(folder / "drums.wav", 0.3)
    execute("""INSERT INTO stem_sets(id, take_id, title, model, wanted, fmt, status, created_at, folder)
               VALUES('st1', ?, 'Has Stems', 'htdemucs', 'vocals,drums', 'wav', 'done', ?, ?)""",
            (take["id"], time.time(), str(folder)))
    return take, audio, folder


def test_delete_take_removes_rows_and_folders(client, data_dir):
    take, audio, folder = _take_with_stems(data_dir)
    assert client.delete(f"/api/takes/{take['id']}").status_code == 200
    assert not audio.parent.exists() and not folder.exists()
    assert one("SELECT id FROM stem_sets WHERE id = 'st1'") is None


def test_delete_take_whose_folder_is_already_gone(client):
    take = make_take(audio_path="/data/takes/nothing-here/x.flac")
    assert client.delete(f"/api/takes/{take['id']}").status_code == 200


def test_stem_files_only_serve_what_the_set_holds(client, data_dir):
    _take_with_stems(data_dir)
    assert client.get("/api/stem-sets/st1/vocals.wav").status_code == 200
    assert client.get("/api/stem-sets/st1/%2E%2E").status_code == 404
    assert client.get("/api/stem-sets/st1/other.wav").status_code == 404
    assert len(client.get("/api/stem-sets/st1/vocals.wav/peaks").json()["peaks"]) == 1024


def test_zip_is_built_on_disk_and_removed(client, data_dir):
    _take_with_stems(data_dir)
    response = client.get("/api/stem-sets/st1/zip")
    assert sorted(zipfile.ZipFile(io.BytesIO(response.content)).namelist()) == ["drums.wav", "vocals.wav"]
    assert not list(config.WORK_DIR.glob("zip-*"))


def test_takes_list_etag_filter_and_limit(client, data_dir):
    _take_with_stems(data_dir)
    make_take(title="Starred")
    execute("UPDATE takes SET favourite = 1 WHERE title = 'Starred'")
    first = client.get("/api/takes")
    assert first.headers["x-total-count"] == "2"
    assert client.get("/api/takes", headers={"if-none-match": first.headers["etag"]}).status_code == 304
    with_stems = [t for t in first.json() if t["title"] == "Has Stems"][0]
    assert with_stems["has_audio"] and [f["name"] for f in with_stems["stem_sets"][0]["files"]] == ["drums", "vocals"]
    starred = client.get("/api/takes?favourite=true").json()
    assert [t["title"] for t in starred] == ["Starred"]
    assert len(client.get("/api/takes?limit=1").json()) == 1


def test_delete_source(client, data_dir):
    source = client.post("/api/sources", files={"file": ("gone.wav", b"xyz")}).json()
    assert client.delete(f"/api/sources/{source['id']}").status_code == 200
    assert not list(config.SOURCES_DIR.glob("*gone*"))
    assert one("SELECT id FROM sources WHERE id = ?", (source["id"],)) is None


def test_waiting_jobs_are_queued_again_on_start(data_dir):
    from fastapi.testclient import TestClient
    from app import jobs
    from app.main import app
    planned = make_take(status="queued", abc="")
    rendering = make_take(status="queued", abc="X:1" * 30)
    running = make_take(status="running")
    while not jobs.QUEUE.empty():
        jobs.QUEUE.get_nowait()
    # The worker would start taking jobs, so hold it back and read the queue.
    original = jobs.worker
    jobs.worker = lambda: asyncio.sleep(3600)
    try:
        with TestClient(app, base_url="http://localhost"):
            queued = []
            while not jobs.QUEUE.empty():
                queued.append(jobs.QUEUE.get_nowait())
    finally:
        jobs.worker = original
    assert {"kind": "plan", "id": planned["id"]} in queued
    assert {"kind": "render", "id": rendering["id"]} in queued
    assert one("SELECT status FROM takes WHERE id = ?", (running["id"],))["status"] == "failed"
