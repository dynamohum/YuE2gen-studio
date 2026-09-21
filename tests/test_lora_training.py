"""Training a LoRA: it holds the GPU, so the app keeps everything else off it."""
import time

from app import config
from app.db import execute, one


def a_corpus(with_export: bool = True, tmp_path=None) -> dict:
    identity_id = "corpus1"
    execute("""INSERT INTO identities(id, name, trigger_word, description, voice, folder, consent, created_at)
               VALUES(?, 'Alicia', 'alicia', 'Soulful R&B', 'female', '/music', 1, ?)""",
            (identity_id, time.time()))
    if with_export:
        dataset = config.DATA_DIR / "identities" / identity_id / "dataset"
        dataset.mkdir(parents=True)
        (dataset / "one.flac").write_bytes(b"not really audio")
    return {"id": identity_id}


def test_training_needs_an_export_first(client):
    corpus = a_corpus(with_export=False)
    answer = client.post(f"/api/identities/{corpus['id']}/train")
    assert answer.status_code == 400
    assert "Export" in answer.json()["detail"]


def test_training_queues_a_run_and_reports_it(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ENGINE_INPUT_DIR", tmp_path / "engine-input")
    corpus = a_corpus()
    answer = client.post(f"/api/identities/{corpus['id']}/train", json={"steps": 50, "rank": 8})
    assert answer.status_code == 200
    run = answer.json()
    assert run["lora_name"] == "alicia_lora" and run["steps"] == 50

    state = client.get("/api/state").json()
    assert state["training"]["id"] == run["id"]
    assert state["training"]["state"] == "queued"


def test_a_running_loRA_keeps_the_engine_to_itself(client, monkeypatch, tmp_path):
    """Measured at 12.5 GB of 16: a render on top of training would fail, so it is
    refused rather than started."""
    monkeypatch.setattr(config, "ENGINE_INPUT_DIR", tmp_path / "engine-input")
    a_corpus()
    execute("""INSERT INTO lora_runs(id, identity_id, lora_name, steps, rank, state, started_at)
               VALUES('run1', 'corpus1', 'alicia_lora', 5000, 16, 'running', ?)""", (time.time(),))

    refused = client.post("/api/songs", json={"title": "x", "style": "pop", "lyrics": "[Verse]\none"})
    assert refused.status_code == 409
    assert "GPU" in refused.json()["detail"]

    # and a second training run is refused too
    again = client.post("/api/identities/corpus1/train")
    assert again.status_code == 409


def test_a_queued_run_can_be_cancelled(client):
    execute("""INSERT INTO lora_runs(id, identity_id, lora_name, steps, rank, state)
               VALUES('run2', 'corpus1', 'alicia_lora', 5000, 16, 'queued')""")
    answer = client.post("/api/lora-runs/run2/cancel")
    assert answer.status_code == 200
    assert one("SELECT state FROM lora_runs WHERE id = 'run2'")["state"] == "cancelled"
    assert client.get("/api/state").json()["training"] is None
