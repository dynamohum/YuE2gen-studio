"""The Harmony control in the app: step mapping, storage, validation, replan."""
from app import config, jobs
from app.db import conn, one

from conftest import make_take


def test_familiar_uses_the_stock_planner():
    graph = jobs.build_plan_graph({"checkpoint": "ck", "style": "s", "lyrics": "l", "seed": 1, "harmony": 0})
    assert graph["2"]["class_type"] == "YuE2GenerateABC"
    assert "chord_strength" not in graph["2"]["inputs"]


def test_each_step_maps_to_the_measured_setting():
    expected = {1: ("spelling", 8.0, 0.0), 2: ("spelling", 16.0, 0.0), 3: ("root", 32.0, 0.0), 4: ("root", 32.0, 3.0)}
    for step, (identity, strength, bonus) in expected.items():
        graph = jobs.build_plan_graph({"checkpoint": "ck", "style": "s", "lyrics": "l", "seed": 1, "harmony": step, "variety": "bold"})
        node = graph["2"]["inputs"]
        assert graph["2"]["class_type"] == jobs.HARMONY_NODE
        assert (node["chord_identity"], node["chord_strength"], node["outside_bonus"]) == (identity, strength, bonus)
        assert node["hold_limit"] == 8 and node["chord_window"] == 16 and node["outside_limit"] == 0.25
        assert node["temperature"] == jobs.PLAN_VARIETY["bold"]["temperature"]   # variety still applies


def test_the_database_has_the_column():
    assert "harmony" in {r["name"] for r in conn().execute("PRAGMA table_info(takes)")}


def test_song_stores_harmony_and_rejects_out_of_range(client, monkeypatch):
    monkeypatch.setitem(jobs.ENGINE.options, "checkpoints", [config.CHECKPOINT])
    monkeypatch.setitem(jobs.ENGINE.options, "harmony", True)
    monkeypatch.setattr(jobs.ENGINE, "options_loaded", True)
    made = client.post("/api/songs", json={"lyrics": "la", "harmony": 3}).json()
    assert one("SELECT harmony FROM takes WHERE id = ?", (made["id"],))["harmony"] == 3
    assert client.post("/api/songs", json={"lyrics": "la", "harmony": 5}).status_code == 422


def test_harmony_is_refused_when_the_engine_lacks_the_node(client, monkeypatch):
    monkeypatch.setitem(jobs.ENGINE.options, "checkpoints", [config.CHECKPOINT])
    monkeypatch.setitem(jobs.ENGINE.options, "harmony", False)
    monkeypatch.setattr(jobs.ENGINE, "options_loaded", True)
    refused = client.post("/api/songs", json={"lyrics": "la", "harmony": 2})
    assert refused.status_code == 400 and "harmony node" in refused.json()["detail"]
    assert client.post("/api/songs", json={"lyrics": "la", "harmony": 0}).status_code == 200


def test_replan_can_change_harmony_or_keep_it(client, monkeypatch):
    monkeypatch.setitem(jobs.ENGINE.options, "harmony", True)
    take = make_take(status="planned", abc="X:1" * 30)
    assert client.post(f"/api/takes/{take['id']}/replan", json={"harmony": 4, "variety": "calm"}).status_code == 200
    row = one("SELECT harmony, variety, status FROM takes WHERE id = ?", (take["id"],))
    assert (row["harmony"], row["variety"], row["status"]) == (4, "calm", "queued")
    conn().execute("UPDATE takes SET status = 'planned' WHERE id = ?", (take["id"],)); conn().commit()
    assert client.post(f"/api/takes/{take['id']}/replan").status_code == 200   # no body keeps both
    row = one("SELECT harmony, variety FROM takes WHERE id = ?", (take["id"],))
    assert (row["harmony"], row["variety"]) == (4, "calm")
