"""Sing again: a copy of a take with the same score and a new seed."""
import time

from app.db import execute, one

ABC = "X:1\nM:4/4\nL:1/16\nK:C\nV: Vocal\n" + "|".join(['"C"c4d4e4f4'] * 8) + "|\n"


def a_take(**extra):
    row = {"id": "orig1", "kind": "song", "title": "good1 · Tight", "style": "pop", "lyrics": "[verse]\nla",
           "abc": ABC, "mode": "full", "seed": 1747519420, "checkpoint": "x", "status": "done",
           "created_at": time.time(), "max_duration": 120, "interpretation": "tight", "variety": "calm",
           "style_lora": "paul_mccartney_lora.safetensors", "style_lora_model": 0.7, "style_lora_clip": 0.7,
           "favourite": 1, "audio_path": "/data/takes/x.flac", "loudness": -15.0}
    row.update(extra)
    cols = list(row)
    execute(f"INSERT INTO takes({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})", [row[c] for c in cols])
    return row


def test_a_new_voice_sings_the_same_score_with_a_new_seed(client, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_checkpoint", lambda: "x")
    a_take(sound_seed=999)
    made = client.post("/api/takes/orig1/revoice")
    assert made.status_code == 200, made.text
    copy = one("SELECT * FROM takes WHERE id = ?", (made.json()["id"],))
    assert copy["title"] == "good1 \u00b7 sung again"
    assert copy["abc"] == ABC, "the same score"
    assert copy["seed"] == made.json()["seed"] and copy["seed"] != 1747519420, "a new seed"
    assert copy["sound_seed"] is None, "the sound follows the new seed"
    assert copy["interpretation"] == "tight" and copy["style_lora_model"] == 0.7 and copy["max_duration"] == 120
    assert copy["status"] == "queued" and copy["audio_path"] is None and not copy["favourite"]
    assert one("SELECT seed FROM takes WHERE id = 'orig1'")["seed"] == 1747519420, "the original is untouched"


def test_rendering_with_a_new_seed_lets_the_sound_follow_it(client, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_checkpoint", lambda: "x")
    a_take(sound_seed=999)
    client.post("/api/takes/orig1/render", json={"seed": 1747519420})
    assert one("SELECT sound_seed FROM takes WHERE id = 'orig1'")["sound_seed"] == 999, "same seed keeps the voice"
    execute("UPDATE takes SET status = 'done' WHERE id = 'orig1'")
    client.post("/api/takes/orig1/render", json={"seed": 5})
    assert one("SELECT sound_seed FROM takes WHERE id = 'orig1'")["sound_seed"] is None
