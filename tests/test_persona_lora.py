"""Tests for Vocal Persona and Voice LoRA integration."""
import pytest

from app import config, jobs
from app.db import one
from app.jobs import QUEUE, build_render_graph, with_persona_lora, with_realaudio_lora

from conftest import make_take


def drain():
    while not QUEUE.empty():
        QUEUE.get_nowait()


def test_with_persona_lora_wires_into_model_only():
    graph = {
        "10": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
        "11": {"class_type": "YuE2GenerateMusic", "inputs": {"clip": ["10", 1]}},
        "14": {"class_type": "KSampler", "inputs": {"model": ["10", 0]}},
    }
    with_persona_lora(graph, lora="paulshields_best.safetensors", strength=1.0)
    assert graph["26"]["class_type"] == "LoraLoader"
    assert graph["26"]["inputs"]["lora_name"] == "paulshields_best.safetensors"
    assert graph["26"]["inputs"]["strength_model"] == 1.0
    assert graph["26"]["inputs"]["strength_clip"] == 0.0
    assert graph["14"]["inputs"]["model"] == ["26", 0]
    assert graph["11"]["inputs"]["clip"] == ["10", 1]


def test_persona_lora_chains_with_realaudio():
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
        "persona_id": "p123",
        "voice_lora": "paulshields_best.safetensors",
        "voice_lora_strength": 1.0,
    }
    graph = build_render_graph(take)
    # Realaudio attaches to model output of 10
    assert "25" in graph
    assert graph["25"]["inputs"]["lora_name"] == config.REAL_AUDIO_LORA
    assert graph["25"]["inputs"]["model"] == ["10", 0]

    # Persona LoRA chains onto output of 25
    assert "26" in graph
    assert graph["26"]["inputs"]["lora_name"] == "paulshields_best.safetensors"
    assert graph["26"]["inputs"]["model"] == ["25", 0]

    # KSampler takes the chained model from 26
    assert graph["14"]["inputs"]["model"] == ["26", 0]

    # YuE2GenerateMusic CLIP input remains untouched
    assert graph["11"]["inputs"]["clip"] == ["10", 1]


def test_persona_lora_alone_in_render_graph():
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
        "persona_id": "p123",
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


def test_api_creates_song_with_persona(client, monkeypatch):
    drain()
    body = {
        "title": "Voice Test",
        "style": "paulshields, indie rock",
        "lyrics": "singing with my own voice",
        "persona_id": "p_paul",
        "voice_lora": "paulshields_best.safetensors",
        "voice_lora_strength": 1.0,
    }
    res = client.post("/api/songs", json=body)
    assert res.status_code == 200, res.text
    take_id = res.json()["id"]

    row = one("SELECT persona_id, voice_lora, voice_lora_strength FROM takes WHERE id = ?", (take_id,))
    assert row["persona_id"] == "p_paul"
    assert row["voice_lora"] == "paulshields_best.safetensors"
    assert row["voice_lora_strength"] == 1.0


VALID_SCORE = "X:1\nL:1/8\nK:C\nV:Vocal\n|\"C\"c4 d4|\"G\"e4 d4|\"Am\"c4 A4|\"F\"G8|\n" * 3


def test_api_render_take_updates_persona_lora(client):
    drain()
    take = make_take(abc=VALID_SCORE, status="planned")
    res = client.post(f"/api/takes/{take['id']}/render", json={
        "persona_id": "p_paul",
        "voice_lora": "paulshields_step200.safetensors",
    })
    assert res.status_code == 200
    row = one("SELECT persona_id, voice_lora FROM takes WHERE id = ?", (take["id"],))
    assert row["persona_id"] == "p_paul"
    assert row["voice_lora"] == "paulshields_step200.safetensors"


def test_variations_inherit_persona_and_lora(client):
    drain()
    take = make_take(abc=VALID_SCORE, status="planned")
    from app.db import execute
    execute("UPDATE takes SET persona_id = 'p_paul', voice_lora = 'paulshields_best.safetensors', voice_lora_strength = 1.0 WHERE id = ?", (take["id"],))
    res = client.post(f"/api/takes/{take['id']}/variations", json={
        "interpretations": ["tight"],
    })
    assert res.status_code == 200
    created_id = res.json()["created"][0]["id"]
    row = one("SELECT persona_id, voice_lora, voice_lora_strength FROM takes WHERE id = ?", (created_id,))
    assert row["persona_id"] == "p_paul"
    assert row["voice_lora"] == "paulshields_best.safetensors"
    assert row["voice_lora_strength"] == 1.0
