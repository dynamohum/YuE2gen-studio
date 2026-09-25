"""Training a LoRA: it holds the GPU, so the app keeps everything else off it.

Training is on by default and can be switched off.  The tests pin it on, so they do
not depend on the environment; the ones for it switched off are at the bottom.
"""
import time
from pathlib import Path

import pytest

from app import config
from app.db import execute, one


@pytest.fixture(autouse=True)
def training_built_in(monkeypatch):
    """Everything above the "switched off" tests assumes the feature is on."""
    monkeypatch.setattr(config, "TRAINING_ENABLED", True)


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


def test_a_finished_run_is_named_after_the_corpus_and_keeps_its_snapshots(client, monkeypatch, tmp_path):
    """The best goes under the plain name and its copy is dropped.  The snapshots stay,
    each named for its step, because a published LoRA is a checkpoint picked by ear,
    but in a group of their own so they do not read as more finished LoRAs."""
    import asyncio
    from app import jobs, loras

    root = tmp_path / "loras"
    root.mkdir()
    monkeypatch.setattr(config, "ENGINE_INPUT_DIR", tmp_path / "engine-input")
    monkeypatch.setattr(loras, "folder", lambda: root)

    async def trained(kind, run_id, graph):
        for name in ("alicia_lora_best", "alicia_lora_step50", "alicia_lora_step100"):
            (root / f"{name}.safetensors").write_bytes(name.encode())
        (root / "alicia_lora_log.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(jobs, "_run_graph", trained)

    a_corpus()
    execute("""INSERT INTO lora_runs(id, identity_id, lora_name, steps, rank, state)
               VALUES('run1', 'corpus1', 'alicia_lora', 100, 16, 'queued')""")
    asyncio.run(jobs.run_lora_train("run1"))

    assert one("SELECT state FROM lora_runs WHERE id = 'run1'")["state"] == "done"
    assert sorted(path.name for path in root.glob("*.safetensors")) == [
        "alicia_lora.safetensors", "alicia_lora_step100.safetensors", "alicia_lora_step50.safetensors"]
    assert (root / "alicia_lora.safetensors").read_bytes() == b"alicia_lora_best"
    assert (root / "alicia_lora.txt").read_text(encoding="utf-8").split("\n")[0] == "Alicia"
    assert (root / "alicia_lora_step50.txt").read_text(encoding="utf-8").split("\n")[0] == "Alicia · step 50"
    assert loras.families(root) == {"alicia_lora": "Your corpora", "alicia_lora_step50": "Training checkpoints",
                                    "alicia_lora_step100": "Training checkpoints"}
    assert "\n\n" not in (root / "families.txt").read_text(encoding="utf-8")
    assert one("SELECT lora FROM identities WHERE id = 'corpus1'")["lora"] == "alicia_lora.safetensors"


def test_steps_follow_the_size_of_the_corpus(monkeypatch):
    """About ten passes over each song, the trainer's rule of thumb, rounded up to a
    checkpoint.  600 for every corpus was 18 passes for 17 songs and 30 for 10."""
    monkeypatch.setattr(config, "TRAIN_STEPS", None)
    assert config.train_steps(17) == 200
    assert config.train_steps(10) == 100
    assert config.train_steps(1) == 100, "never fewer than two checkpoints"
    assert config.train_steps(40) == 400
    monkeypatch.setattr(config, "TRAIN_STEPS", 600)
    assert config.train_steps(17) == 600, "an explicit setting wins"


def test_the_trainer_gets_the_published_recipe():
    from app import jobs

    inputs = jobs.train_graph("in", "set", "alicia_lora", 200)["5"]["inputs"]
    assert inputs["steps"] == 200
    assert inputs["batch_songs"] == 2
    assert inputs["decoder_steps"] == 1000
    assert inputs["score_first_fraction"] == 0
    assert inputs["checkpoint_every"] == 50


def test_a_queued_run_can_be_cancelled(client):
    execute("""INSERT INTO lora_runs(id, identity_id, lora_name, steps, rank, state)
               VALUES('run2', 'corpus1', 'alicia_lora', 5000, 16, 'queued')""")
    answer = client.post("/api/lora-runs/run2/cancel")
    assert answer.status_code == 200
    assert one("SELECT state FROM lora_runs WHERE id = 'run2'")["state"] == "cancelled"
    assert client.get("/api/state").json()["training"] is None


# ------------------------------------------------------------------ switched off

def test_training_is_on_by_default():
    """Both switches default to on: the app's setting, and the engine image's."""
    root = Path(__file__).resolve().parent.parent
    assert 'os.environ.get("TRAINING_ENABLED", "1")' in (root / "app" / "config.py").read_text()
    assert "ARG WITH_TRAINER=1" in (root / "engine" / "Dockerfile").read_text()
    compose = (root / "compose.yml").read_text()
    assert 'WITH_TRAINER: "1"' in compose and 'TRAINING_ENABLED: "1"' in compose


def test_switched_off_it_says_so(client, monkeypatch):
    """It answers 501 with the reason, not 404, so a caller can tell the difference
    between a feature switched off and a URL that is wrong."""
    monkeypatch.setattr(config, "TRAINING_ENABLED", False)
    corpus = a_corpus()
    answer = client.post(f"/api/identities/{corpus['id']}/train")
    assert answer.status_code == 501
    detail = answer.json()["detail"]
    assert "switched off" in detail and "TRAINING_ENABLED=1" in detail


def test_the_gate_comes_before_anything_else(client, monkeypatch):
    """A corpus with no export still reports the feature, not the missing export: the
    user cannot act on advice about exporting if the button will never appear."""
    monkeypatch.setattr(config, "TRAINING_ENABLED", False)
    corpus = a_corpus(with_export=False)
    assert client.post(f"/api/identities/{corpus['id']}/train").status_code == 501


def test_the_page_is_told_so_it_can_hide_the_button(client, monkeypatch):
    monkeypatch.setattr(config, "TRAINING_ENABLED", False)
    assert client.get("/api/state").json()["options"]["training_available"] is False


def test_it_still_needs_the_engine_node_when_the_flag_is_on(client, monkeypatch):
    """Both halves are required: the flag alone, on an image built without the pack,
    must not offer the button."""
    monkeypatch.setattr(config, "TRAINING_ENABLED", True)
    from app.main import ENGINE
    monkeypatch.setitem(ENGINE.options, "trainer", False)
    assert client.get("/api/state").json()["options"]["training_available"] is False
    monkeypatch.setitem(ENGINE.options, "trainer", True)
    assert client.get("/api/state").json()["options"]["training_available"] is True


def test_exporting_is_gated_with_everything_else(client, monkeypatch):
    """Exporting a set was once left open, on the argument that it feeds a trainer
    elsewhere. It closes with the rest: a set nobody can train here is an hour of CPU
    spent on a folder, and the wall should come before the work, not after it."""
    monkeypatch.setattr(config, "TRAINING_ENABLED", True)
    corpus = a_corpus()
    monkeypatch.setattr(config, "TRAINING_ENABLED", False)
    assert client.post(f"/api/identities/{corpus['id']}/export").status_code == 501


# ------------------------------------- the whole workflow, not just the button

def test_the_corpus_routes_are_closed_too(client, monkeypatch):
    """Preparing a corpus costs a vocal separation and a transcription for every song.
    With no way to train at the end of it that work buys nothing, so the way in closes
    with the training step rather than after it."""
    monkeypatch.setattr(config, "TRAINING_ENABLED", False)
    for method, path in (
        ("get", "/api/identities"),
        ("post", "/api/identities"),
        ("get", "/api/personas"),
        ("get", "/api/import/browse"),
        ("post", "/api/lora-runs/whatever/cancel"),
    ):
        answer = getattr(client, method)(path)
        assert answer.status_code == 501, f"{method} {path} answered {answer.status_code}"


def test_a_corpus_that_exists_is_left_alone(client, monkeypatch):
    """Closing the way in must not touch what is already on disk or in the database."""
    monkeypatch.setattr(config, "TRAINING_ENABLED", True)
    corpus = a_corpus()
    monkeypatch.setattr(config, "TRAINING_ENABLED", False)
    assert client.get(f"/api/identities/{corpus['id']}").status_code == 501
    assert one("SELECT * FROM identities WHERE id = ?", (corpus["id"],)) is not None


def test_the_rest_of_the_app_is_untouched(client, monkeypatch):
    """The gate is a prefix match, so this is the test that catches it growing teeth."""
    monkeypatch.setattr(config, "TRAINING_ENABLED", False)
    for path in ("/api/state", "/api/takes", "/api/sources", "/api/spaces", "/api/settings"):
        assert client.get(path).status_code == 200, path


def test_a_learned_style_is_the_caption_the_lora_was_trained_on(client):
    """A LoRA learns a sound with the words it was captioned with.  A chip that left
    out the corpus description asked it for something it never saw, and a Lennon
    LoRA trained on "British accent, raspy baritone" sang like stock YuE2."""
    from app import main

    execute("""INSERT INTO identities(id, name, trigger_word, description, voice, folder, consent, created_at, lora)
               VALUES('c1', 'John Lennon', 'johnlennon', 'British accent, raspy baritone', 'male', '/m', 1, ?,
                      'john_lennon_lora.safetensors')""", (time.time(),))
    for position, (title, hint, own) in enumerate((("It's So Hard", "blues rock", ""),
                                                    ("Imagine", "", ""),
                                                    ("Oh Yoko!", "folk rock", "bright piano"))):
        execute("""INSERT INTO identity_songs(id, identity_id, file, title, sha256, include, key, tempo, style_hint,
                                              description, position)
                   VALUES(?, 'c1', ?, ?, ?, 1, 'A major', 86, ?, ?, ?)""",
                (f"s{position}", f"{title}.flac", title, f"sha{position}", hint, own, position))

    chips = main._lora_corpus_styles()["john_lennon_lora.safetensors"]
    captions = {song["title"]: song["caption"] for song in main._identity_view(one("SELECT * FROM identities WHERE id = 'c1'"))["songs"]}

    assert len(chips) == 3, "a song with no style suggestion still has a caption, so it gets a chip"
    for chip in chips:
        # The page puts the trigger in front and the tempo after, as the caption has them.
        assert f"johnlennon, {chip['prompt']}, {chip['tempo']} BPM" == captions[chip["title"]]
    assert "British accent" in chips[0]["prompt"] and "male vocal" in chips[0]["prompt"]
    assert "bright piano" in chips[2]["prompt"] and "British accent" not in chips[2]["prompt"], \
        "a song's own description replaces the corpus one, as it does in the export"


def test_a_lora_this_app_cannot_read_fails_the_run_with_the_fix(client, monkeypatch, tmp_path):
    """An engine image older than the trainer patch leaves its files readable by root
    only.  The run says so and how to fix it, rather than leaving a LoRA half finished."""
    import asyncio
    from app import jobs, loras

    root = tmp_path / "loras"
    root.mkdir()
    monkeypatch.setattr(config, "ENGINE_INPUT_DIR", tmp_path / "engine-input")
    monkeypatch.setattr(loras, "folder", lambda: root)

    async def trained(kind, run_id, graph):
        (root / "alicia_lora_best.safetensors").write_bytes(b"x")
    monkeypatch.setattr(jobs, "_run_graph", trained)
    real_access = jobs.os.access
    monkeypatch.setattr(jobs.os, "access", lambda path, mode: False if str(path).endswith("_best.safetensors") else real_access(path, mode))

    a_corpus()
    execute("""INSERT INTO lora_runs(id, identity_id, lora_name, steps, rank, state)
               VALUES('run1', 'corpus1', 'alicia_lora', 100, 16, 'queued')""")
    asyncio.run(jobs.run_lora_train("run1"))
    run = one("SELECT state, error FROM lora_runs WHERE id = 'run1'")
    assert run["state"] == "failed" and "readable by root only" in run["error"] and "chmod" in run["error"]
