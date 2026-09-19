"""Tests for Realaudio production add-on integration."""
import pytest

from app import config, jobs
from app.db import one
from app.jobs import QUEUE, build_render_graph, with_realaudio_lora

from conftest import make_take


def drain():
    while not QUEUE.empty():
        QUEUE.get_nowait()


def test_with_realaudio_lora_wires_into_model_only():
    graph = {
        "10": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
        "11": {"class_type": "YuE2GenerateMusic", "inputs": {"clip": ["10", 1]}},
        "14": {"class_type": "KSampler", "inputs": {"model": ["10", 0]}},
    }
    with_realaudio_lora(graph, loader="10", lora="test_nar.safetensors", strength=1.0)
    assert graph["25"]["class_type"] == "LoraLoader"
    assert graph["25"]["inputs"]["lora_name"] == "test_nar.safetensors"
    assert graph["25"]["inputs"]["strength_model"] == 1.0
    assert graph["25"]["inputs"]["strength_clip"] == 0.0
    assert graph["14"]["inputs"]["model"] == ["25", 0]
    assert graph["11"]["inputs"]["clip"] == ["10", 1]


def test_render_graph_respects_realaudio_setting():
    take_off = {"id": "t1", "kind": "song", "style": "rock", "lyrics": "la", "abc": "X:1",
                "seed": 1, "mode": "full", "max_duration": 60, "realaudio": 0}
    take_on = {"id": "t2", "kind": "song", "style": "rock", "lyrics": "la", "abc": "X:1",
               "seed": 1, "mode": "full", "max_duration": 60, "realaudio": 1}

    graph_off = build_render_graph(take_off)
    assert "25" not in graph_off
    assert graph_off["14"]["inputs"]["model"] == ["10", 0]

    graph_on = build_render_graph(take_on)
    assert "25" in graph_on
    assert graph_on["25"]["inputs"]["lora_name"] == config.REAL_AUDIO_LORA
    assert graph_on["14"]["inputs"]["model"] == ["25", 0]
    assert graph_on["11"]["inputs"]["clip"] == ["10", 1]


def test_realaudio_and_instrumental_coexist_in_render_graph():
    take = {"id": "t3", "kind": "instrumental", "style": "rock", "lyrics": "[instrumental]", "abc": "X:1",
            "seed": 1, "mode": "full", "max_duration": 60, "realaudio": 1, "feel": "steady"}
    graph = build_render_graph(take)
    # Realaudio LoRA attaches to KSampler (model)
    assert "25" in graph
    assert graph["25"]["inputs"]["lora_name"] == config.REAL_AUDIO_LORA
    assert graph["14"]["inputs"]["model"] == ["25", 0]
    # Instrumental LoRA attaches to YuE2GenerateMusic (clip)
    assert "20" in graph
    assert graph["20"]["inputs"]["lora_name"] == config.INSTRUMENTAL_LORA
    assert graph["11"]["inputs"]["clip"] == ["20", 1]


def test_api_creates_song_with_realaudio(client):
    made = client.post("/api/songs", json={"style": "rock", "lyrics": "[Verse]\nHello world", "realaudio": True}).json()
    row = one("SELECT * FROM takes WHERE id = ?", (made["id"],))
    assert row["realaudio"] == 1
    drain()

    made_off = client.post("/api/songs", json={"style": "rock", "lyrics": "[Verse]\nHello world", "realaudio": False}).json()
    row_off = one("SELECT * FROM takes WHERE id = ?", (made_off["id"],))
    assert row_off["realaudio"] == 0
    drain()


VALID_SCORE = "X:1\nL:1/8\nK:C\nV:Vocal\n|\"C\"c4 d4|\"G\"e4 d4|\"Am\"c4 A4|\"F\"G8|\n" * 3


def test_api_render_preserves_and_updates_realaudio(client):
    take1 = make_take(kind="song", title="Audio Test 1", status="planned", lyrics="[Verse]\nTest", abc=VALID_SCORE)
    # Render without specifying realaudio keeps take's own
    client.post(f"/api/takes/{take1['id']}/render")
    assert one("SELECT realaudio FROM takes WHERE id = ?", (take1["id"],))["realaudio"] == 0
    drain()

    # Render with realaudio=True updates take to 1
    take2 = make_take(kind="song", title="Audio Test 2", status="planned", lyrics="[Verse]\nTest", abc=VALID_SCORE)
    resp = client.post(f"/api/takes/{take2['id']}/render", json={"realaudio": True})
    assert resp.status_code == 200
    assert one("SELECT realaudio FROM takes WHERE id = ?", (take2["id"],))["realaudio"] == 1
    drain()



def test_api_variations_inherit_realaudio(client):
    take = make_take(kind="song", title="Var Test", status="planned", lyrics="[Verse]\nTest", abc=VALID_SCORE)
    from app.db import execute
    execute("UPDATE takes SET realaudio = 1 WHERE id = ?", (take["id"],))
    resp = client.post(f"/api/takes/{take['id']}/variations", json={"interpretations": ["tight", "loose"]})
    assert resp.status_code == 200
    made = resp.json()["created"]
    for item in made:
        row = one("SELECT realaudio FROM takes WHERE id = ?", (item["id"],))
        assert row["realaudio"] == 1
    drain()


def test_api_creates_instrumental_with_realaudio(client, monkeypatch):
    monkeypatch.setitem(jobs.ENGINE.options, "instrumental", True)
    made = client.post("/api/instrumentals", json={"style": "ambient", "structure": "[Intro] [Verse]", "realaudio": True}).json()
    row = one("SELECT * FROM takes WHERE id = ?", (made["id"],))
    assert row["realaudio"] == 1
    drain()

    made_off = client.post("/api/instrumentals", json={"style": "ambient", "structure": "[Intro] [Verse]", "realaudio": False}).json()
    row_off = one("SELECT * FROM takes WHERE id = ?", (made_off["id"],))
    assert row_off["realaudio"] == 0
    drain()


