"""One checkpoint, render interpretations and Variations, and lyric drafts."""
import asyncio

from app import config, jobs, lyrics
from app.db import conn, execute, one
from app.jobs import LYRICS, QUEUE

from conftest import make_take

SCORE = "X:1\nL:1/8\nK:C\nV:Vocal\n|\"C\"c4 d4|\"G\"e4 d4|\"Am\"c4 A4|\"F\"G8|\n" * 3


def drain():
    while not QUEUE.empty():
        QUEUE.get_nowait()


# --------------------------------------------------------------- one checkpoint
def test_graphs_always_use_the_bf16_checkpoint():
    old = {"id": "t", "checkpoint": "yue2_3b_int8_convrot.safetensors", "style": "s", "lyrics": "l", "abc": SCORE,
           "seed": 1, "mode": "full", "max_duration": 60}
    assert jobs.build_render_graph(old)["10"]["inputs"]["ckpt_name"] == config.CHECKPOINT
    assert jobs.build_plan_graph(old)["1"]["inputs"]["ckpt_name"] == config.CHECKPOINT


def test_a_missing_checkpoint_is_refused_once_the_engine_is_known(client, monkeypatch):
    monkeypatch.setitem(jobs.ENGINE.options, "checkpoints", ["yue2_3b_int8_convrot.safetensors"])
    monkeypatch.setattr(jobs.ENGINE, "options_loaded", True)
    refused = client.post("/api/songs", json={"lyrics": "la"})
    assert refused.status_code == 400 and config.CHECKPOINT in refused.json()["detail"]
    monkeypatch.setitem(jobs.ENGINE.options, "checkpoints", [config.CHECKPOINT])
    made = client.post("/api/songs", json={"lyrics": "la"}).json()
    assert one("SELECT checkpoint FROM takes WHERE id = ?", (made["id"],))["checkpoint"] == config.CHECKPOINT
    drain()


# ----------------------------------------------------------------- interpretations
def test_the_database_has_the_column():
    assert "interpretation" in {r["name"] for r in conn().execute("PRAGMA table_info(takes)")}


def test_each_interpretation_sets_the_render_sampler():
    take = {"id": "t", "style": "s", "lyrics": "l", "abc": SCORE, "seed": 1, "mode": "full", "max_duration": 60}
    node = lambda name: jobs.build_render_graph({**take, "interpretation": name})["11"]["inputs"]  # noqa: E731
    assert (node("standard")["temperature"], node("standard")["repetition_penalty"]) == (1.0, 1.2)
    assert node("tight")["temperature"] == 0.8 and node("loose")["temperature"] == 1.2
    assert node("settled")["repetition_penalty"] == 1.0 and node("restless")["repetition_penalty"] == 1.35
    assert (node("wide")["top_k"], node("wide")["top_p"]) == (250, 0.99)
    assert node(None) == node("standard")


def test_a_song_keeps_its_interpretation_and_render_can_change_it(client):
    made = client.post("/api/songs", json={"lyrics": "la", "interpretation": "loose"}).json()
    assert one("SELECT interpretation FROM takes WHERE id = ?", (made["id"],))["interpretation"] == "loose"
    assert client.post("/api/songs", json={"lyrics": "la", "interpretation": "odd"}).status_code == 400
    take = make_take(status="planned", abc=SCORE)
    assert client.post(f"/api/takes/{take['id']}/render", json={"interpretation": "restless"}).status_code == 200
    assert one("SELECT interpretation FROM takes WHERE id = ?", (take["id"],))["interpretation"] == "restless"
    drain()


def test_variations_copy_the_score_and_seed_in_each_interpretation(client):
    take = make_take(title="Night drive · Tight", abc=SCORE, seed=77)
    reply = client.post(f"/api/takes/{take['id']}/variations", json={"interpretations": ["loose", "wide", "loose"]})
    made = reply.json()["created"]
    assert [m["title"] for m in made] == ["Night drive · Loose", "Night drive · Wide"]
    for item in made:
        row = one("SELECT * FROM takes WHERE id = ?", (item["id"],))
        assert (row["abc"], row["seed"], row["status"], row["interpretation"]) == (SCORE, 77, "queued", item["interpretation"])
    assert [QUEUE.get_nowait()["id"] for _ in made] == [m["id"] for m in made]
    # A length cap asked for here is for the new takes only.
    capped = client.post(f"/api/takes/{take['id']}/variations",
                         json={"interpretations": ["wide"], "max_duration": 200}).json()["created"][0]
    assert one("SELECT max_duration FROM takes WHERE id = ?", (capped["id"],))["max_duration"] == 200
    assert one("SELECT max_duration FROM takes WHERE id = ?", (take["id"],))["max_duration"] == 60
    QUEUE.get_nowait()
    assert client.post(f"/api/takes/{take['id']}/variations",
                       json={"interpretations": ["wide"], "max_duration": 5}).status_code == 422
    no_score = make_take(abc="")
    assert client.post(f"/api/takes/{no_score['id']}/variations", json={"interpretations": ["tight"]}).status_code == 400
    assert client.post(f"/api/takes/{take['id']}/variations", json={"interpretations": []}).status_code == 422


def test_variations_on_other_checkpoints_of_the_style_lora(client, monkeypatch):
    from app import jobs
    names = ["fow_lora.safetensors", "fow_lora_step50.safetensors", "fow_lora_step250.safetensors"]
    monkeypatch.setitem(jobs.ENGINE.options, "loras", names)
    take = make_take(title="Night drive · step 50", abc=SCORE, seed=77)
    execute("UPDATE takes SET style_lora = 'fow_lora_step50.safetensors', interpretation = 'loose' WHERE id = ?",
            (take["id"],))
    reply = client.post(f"/api/takes/{take['id']}/variations",
                        json={"style_loras": ["fow_lora_step250.safetensors", "fow_lora.safetensors"]})
    made = reply.json()["created"]
    assert [m["title"] for m in made] == ["Night drive · step 250", "Night drive · finished"]
    for item, lora in zip(made, ["fow_lora_step250.safetensors", "fow_lora.safetensors"]):
        row = one("SELECT * FROM takes WHERE id = ?", (item["id"],))
        assert (row["abc"], row["seed"], row["style_lora"], row["interpretation"]) == (SCORE, 77, lora, "loose")
    for _ in made:
        QUEUE.get_nowait()
    url = f"/api/takes/{take['id']}/variations"
    assert client.post(url, json={"style_loras": ["gone.safetensors"]}).status_code == 400
    assert client.post(url, json={}).status_code == 400
    assert client.post(url, json={"interpretations": ["wide"], "style_loras": names}).status_code == 400


# ------------------------------------------------------------------------ lyrics
def test_the_prompt_carries_the_brief_structure_and_the_style_rule():
    prompt = lyrics.build_prompt("leaving  town", "indie pop, piano", "verse-chorus")
    assert "leaving town" in prompt and "Verse, Chorus, Verse, Chorus" in prompt
    assert "[Verse] [Chorus]" in prompt and "Do not name instruments" in prompt


def test_parse_tidies_a_reply():
    reply = ("Sure! Here are your lyrics.\n**Title: Salt Spray**\n\n**[Verse 1]**\nThe pier lights fade\n"
             "Chorus:\nOh the salt spray\n\n[Bridge]\n\n```\n")
    draft = lyrics.parse(reply)
    assert draft["title"] == "Salt Spray"
    assert draft["lyrics"] == "[Verse]\nThe pier lights fade\n\n[Chorus]\nOh the salt spray"
    assert draft["sections"] == ["Verse", "Chorus"] and draft["problems"] == []
    assert lyrics.parse("Just some words\nwith no tags")["problems"] == ["no song sections"]


def test_lyrics_graph_uses_gemma_and_the_seed():
    graph = jobs.build_lyrics_graph({"brief": "b", "style": "s", "structure": "verse-chorus", "seed": 9})
    assert graph["1"]["inputs"]["clip_name"] == config.LYRICS_MODEL
    assert graph["2"]["class_type"] == "TextGenerate" and graph["2"]["inputs"]["sampling_mode.seed"] == 9


def test_lyrics_api_queues_reports_and_cancels(client, monkeypatch):
    monkeypatch.setitem(jobs.ENGINE.options, "lyrics", False)
    monkeypatch.setattr(jobs.ENGINE, "options_loaded", True)
    assert client.post("/api/lyrics", json={"brief": "rain"}).status_code == 400
    monkeypatch.setitem(jobs.ENGINE.options, "lyrics", True)
    assert client.post("/api/lyrics", json={"brief": "rain", "structure": "odd"}).status_code == 400
    draft = client.post("/api/lyrics", json={"brief": "rain on a tin roof", "style": "reggae"}).json()
    assert draft["status"] == "queued" and QUEUE.get_nowait() == {"kind": "lyrics", "id": draft["id"]}
    assert client.get(f"/api/lyrics/{draft['id']}").json()["brief"] == "rain on a tin roof"
    assert client.post(f"/api/lyrics/{draft['id']}/cancel").json() == {"cancelled": True}
    assert client.get(f"/api/lyrics/{draft['id']}").json()["error"] == "cancelled"
    assert client.get("/api/lyrics/nope").status_code == 404


def test_a_lyrics_job_lands_in_the_draft(monkeypatch):
    class Engine:
        last_contact = 1e18

        async def submit(self, graph):
            self.graph = graph
            return "pid"

        async def history(self, prompt_id):
            text = "Title: Tin Roof\n[Verse]\nRain on the roof\n\n[Chorus]\nWe are rich tonight"
            return {"status": {"status_str": "success", "completed": True}, "outputs": {"3": {"text": [text]}},
                    "prompt": [0, "pid", {"3": {"class_type": "PreviewAny"}}]}

        def has_started(self, prompt_id):
            return True

        def forget(self, prompt_id):
            pass

    monkeypatch.setattr(jobs, "ENGINE", Engine())
    real_sleep = asyncio.sleep
    monkeypatch.setattr(jobs.asyncio, "sleep", lambda s: real_sleep(0))
    LYRICS["d1"] = {"id": "d1", "status": "queued", "brief": "b", "style": "s", "structure": "verse-chorus",
                    "seed": 1, "created_at": 0, "title": None, "lyrics": None, "error": None}
    asyncio.run(jobs.run_job("lyrics", "d1"))
    assert LYRICS["d1"]["status"] == "done" and LYRICS["d1"]["title"] == "Tin Roof"
    assert LYRICS["d1"]["lyrics"].startswith("[Verse]\nRain on the roof")
    jobs.forget_old_lyrics(now=10_000)
    assert "d1" not in LYRICS
