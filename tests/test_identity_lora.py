"""Tests for Vocal Identity and Voice LoRA integration."""
import pytest

from app import config, jobs
from app.db import one
from app.jobs import QUEUE, build_render_graph, with_identity_lora, with_persona_lora, with_realaudio_lora

from conftest import make_take


def drain():
    while not QUEUE.empty():
        QUEUE.get_nowait()


def test_with_identity_lora_wires_into_model_only():
    graph = {
        "10": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
        "11": {"class_type": "YuE2GenerateMusic", "inputs": {"clip": ["10", 1]}},
        "14": {"class_type": "KSampler", "inputs": {"model": ["10", 0]}},
    }
    with_identity_lora(graph, lora="paulshields_best.safetensors", strength=1.0)
    assert graph["26"]["class_type"] == "LoraLoader"
    assert graph["26"]["inputs"]["lora_name"] == "paulshields_best.safetensors"
    assert graph["26"]["inputs"]["strength_model"] == 1.0
    assert graph["26"]["inputs"]["strength_clip"] == 0.0
    assert graph["14"]["inputs"]["model"] == ["26", 0]
    assert graph["11"]["inputs"]["clip"] == ["10", 1]


def test_with_persona_lora_alias_works():
    graph = {
        "10": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
        "11": {"class_type": "YuE2GenerateMusic", "inputs": {"clip": ["10", 1]}},
        "14": {"class_type": "KSampler", "inputs": {"model": ["10", 0]}},
    }
    with_persona_lora(graph, lora="paulshields_best.safetensors", strength=1.0)
    assert graph["26"]["inputs"]["lora_name"] == "paulshields_best.safetensors"


def test_identity_lora_chains_with_realaudio():
    take = {
        "id": "t_combo",
        "kind": "song",
        "style": "paulshields, indie rock",
        "lyrics": "hello world",
        "abc": "X:1\nM:4/4\nK:C\n|c4|",
        "seed": 42,
        "mode": "full",
        "max_duration": 60,
        "realaudio": 1,
        "identity_id": "p123",
        "voice_lora": "paulshields_best.safetensors",
        "voice_lora_strength": 1.0,
    }
    graph = build_render_graph(take)
    # Realaudio attaches to model output of 10
    assert "25" in graph
    assert graph["25"]["inputs"]["lora_name"] == config.REAL_AUDIO_LORA
    assert graph["25"]["inputs"]["model"] == ["10", 0]

    # Identity LoRA chains onto output of 25
    assert "26" in graph
    assert graph["26"]["inputs"]["lora_name"] == "paulshields_best.safetensors"
    assert graph["26"]["inputs"]["model"] == ["25", 0]

    # KSampler takes the chained model from 26
    assert graph["14"]["inputs"]["model"] == ["26", 0]

    # YuE2GenerateMusic CLIP input remains untouched
    assert graph["11"]["inputs"]["clip"] == ["10", 1]


def test_identity_lora_alone_in_render_graph():
    take = {
        "id": "t_voice_only",
        "kind": "song",
        "style": "paulshields, indie rock",
        "lyrics": "hello world",
        "abc": "X:1\nM:4/4\nK:C\n|c4|",
        "seed": 42,
        "mode": "full",
        "max_duration": 60,
        "realaudio": 0,
        "identity_id": "p123",
        "voice_lora": "paulshields_step150.safetensors",
        "voice_lora_strength": 0.9,
    }
    graph = build_render_graph(take)
    assert "25" not in graph
    assert "26" in graph
    assert graph["26"]["inputs"]["lora_name"] == "paulshields_step150.safetensors"
    assert graph["26"]["inputs"]["model"] == ["10", 0]
    assert graph["26"]["inputs"]["strength_model"] == 0.9
    assert graph["14"]["inputs"]["model"] == ["26", 0]


def test_api_creates_song_with_identity(client, monkeypatch):
    drain()
    body = {
        "title": "Voice Test",
        "style": "paulshields, indie rock",
        "lyrics": "singing with my own voice",
        "identity_id": "p_paul",
        "voice_lora": "paulshields_best.safetensors",
        "voice_lora_strength": 1.0,
    }
    res = client.post("/api/songs", json=body)
    assert res.status_code == 200, res.text
    take_id = res.json()["id"]

    row = one("SELECT identity_id, persona_id, voice_lora, voice_lora_strength FROM takes WHERE id = ?", (take_id,))
    assert row["identity_id"] == "p_paul"
    assert row["persona_id"] == "p_paul"
    assert row["voice_lora"] == "paulshields_best.safetensors"
    assert row["voice_lora_strength"] == 1.0


def test_api_creates_song_with_persona_backward_compat(client, monkeypatch):
    drain()
    body = {
        "title": "Voice Test Compat",
        "style": "paulshields, indie rock",
        "lyrics": "singing with my own voice",
        "persona_id": "p_paul_compat",
        "voice_lora": "paulshields_best.safetensors",
        "voice_lora_strength": 1.0,
    }
    res = client.post("/api/songs", json=body)
    assert res.status_code == 200, res.text
    take_id = res.json()["id"]

    row = one("SELECT identity_id, persona_id FROM takes WHERE id = ?", (take_id,))
    assert row["identity_id"] == "p_paul_compat"
    assert row["persona_id"] == "p_paul_compat"


VALID_SCORE = "X:1\nL:1/8\nK:C\nV:Vocal\n|\"C\"c4 d4|\"G\"e4 d4|\"Am\"c4 A4|\"F\"G8|\n" * 3


def test_api_render_take_updates_identity_lora(client):
    drain()
    take = make_take(abc=VALID_SCORE, status="planned")
    res = client.post(f"/api/takes/{take['id']}/render", json={
        "identity_id": "p_paul",
        "voice_lora": "paulshields_step200.safetensors",
    })
    assert res.status_code == 200
    row = one("SELECT identity_id, persona_id, voice_lora FROM takes WHERE id = ?", (take["id"],))
    assert row["identity_id"] == "p_paul"
    assert row["persona_id"] == "p_paul"
    assert row["voice_lora"] == "paulshields_step200.safetensors"


def test_variations_inherit_identity_and_lora(client):
    drain()
    take = make_take(abc=VALID_SCORE, status="planned")
    from app.db import execute
    execute("UPDATE takes SET identity_id = 'p_paul', persona_id = 'p_paul', voice_lora = 'paulshields_best.safetensors', voice_lora_strength = 1.0 WHERE id = ?", (take["id"],))
    res = client.post(f"/api/takes/{take['id']}/variations", json={
        "interpretations": ["tight"],
    })
    assert res.status_code == 200
    created_id = res.json()["created"][0]["id"]
    row = one("SELECT identity_id, persona_id, voice_lora, voice_lora_strength FROM takes WHERE id = ?", (created_id,))
    assert row["identity_id"] == "p_paul"
    assert row["persona_id"] == "p_paul"
    assert row["voice_lora"] == "paulshields_best.safetensors"
    assert row["voice_lora_strength"] == 1.0


def test_an_identity_lora_can_write_as_well_as_sing():
    """The planner half was always loaded and always off. It is a control now,
    and still off unless asked for."""
    graph = {
        "10": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
        "11": {"class_type": "YuE2GenerateMusic", "inputs": {"clip": ["10", 1]}},
        "14": {"class_type": "KSampler", "inputs": {"model": ["10", 0]}},
    }
    with_identity_lora(graph, lora="paulshields_best.safetensors", strength=1.0, strength_clip=0.7)
    assert graph["26"]["inputs"]["strength_model"] == 1.0
    assert graph["26"]["inputs"]["strength_clip"] == 0.7
    assert graph["11"]["inputs"]["clip"] == ["26", 1], "asked for, it reaches the render too"


def test_the_planner_half_is_off_by_default():
    graph = {
        "10": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
        "11": {"class_type": "YuE2GenerateMusic", "inputs": {"clip": ["10", 1]}},
        "14": {"class_type": "KSampler", "inputs": {"model": ["10", 0]}},
    }
    with_identity_lora(graph, lora="paulshields_best.safetensors", strength=1.0)
    assert graph["26"]["inputs"]["strength_clip"] == 0.0


def test_an_identitys_planner_half_reaches_the_plan_when_it_is_asked_for():
    take = dict(make_take(kind="song", abc="X:1\n", status="planned"))
    take.update(voice_lora="paulshields_best.safetensors", voice_lora_strength=1.0,
                voice_lora_clip=0.7)
    plan = jobs.build_plan_graph(take)
    assert plan["22"]["inputs"]["lora_name"] == "paulshields_best.safetensors"
    assert plan["22"]["inputs"]["strength_clip"] == 0.7


def test_a_plan_is_untouched_when_the_planner_half_is_off():
    take = dict(make_take(kind="song", abc="X:1\n", status="planned"))
    take.update(voice_lora="paulshields_best.safetensors", voice_lora_strength=1.0,
                voice_lora_clip=0.0)
    assert "22" not in jobs.build_plan_graph(take)
