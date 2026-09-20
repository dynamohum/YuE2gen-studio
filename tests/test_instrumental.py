"""Instrumentals: the structure, the LoRA in both graphs, and the score check."""
import subprocess
import pytest

from app import config, instrumental, jobs, score
from app.db import one
from app.jobs import QUEUE

from conftest import make_take

TAKE = {"id": "t", "kind": "instrumental", "style": "surf rock", "lyrics": "[instrumental]", "abc": "X:1",
        "seed": 1, "mode": "melody", "max_duration": 60}
# What the LoRA writes: a Vocal voice of rests carrying the chords, the melody in Ins.
PLAN = ("X:1\nM:4/4\nL:1/16\nV: Vocal\nV: Ins\nK:Bb\n% intro\nV: Vocal\n"
        '"Gm"z16|"Eb"z16|"Bb"z16|"F"z16|\nV: Ins\nB4B4B4Bcd2|G4G4G4GAB2|F4F4F4FED2|C4C4C4C2D2|\n')
INS_ONLY = PLAN.replace("V: Vocal\n\"Gm\"z16|\"Eb\"z16|\"Bb\"z16|\"F\"z16|\n", "").replace("B4B4", '"Gm"B4B4', 1)


def drain():
    while not QUEUE.empty():
        QUEUE.get_nowait()


def test_structures_are_normalised():
    assert instrumental.normalise("") == "[instrumental]"
    assert instrumental.normalise("[Instrumental]") == "[instrumental]"
    assert instrumental.normalise("[Intro] [verse]\n[CHORUS]") == "[intro]\n[verse]\n[chorus]"
    assert instrumental.normalise("[intro 0:00-0:15]\n[verse 0:15-0:45]") == "[intro 0:00-0:15]\n[verse 0:15-0:45]"
    assert instrumental.seconds("[intro 0:00-0:15]\n[verse 0:15-1:05]") == 65


@pytest.mark.parametrize("bad", ["[solo]", "hello", "[intro 0:00-0:15]\n[verse]", "[intro 0:00-0:15]\n[verse 0:20-0:45]",
                                 "[intro 0:15-0:10]"])
def test_bad_structures_are_refused(bad):
    with pytest.raises(ValueError):
        instrumental.normalise(bad)


def test_the_lora_goes_on_the_text_side_of_both_graphs():
    plan = jobs.build_plan_graph(TAKE)
    assert plan["20"]["class_type"] == "LoraLoader" and plan["20"]["inputs"]["lora_name"] == config.INSTRUMENTAL_LORA
    assert plan["20"]["inputs"]["strength_model"] == 0.0 and plan["2"]["inputs"]["clip"] == ["20", 1]
    render = jobs.build_render_graph(TAKE)
    assert render["11"]["inputs"]["clip"] == ["20", 1] and render["14"]["inputs"]["model"] == ["10", 0]
    assert render["11"]["inputs"]["mode"] == "full"
    song = jobs.build_render_graph({**TAKE, "kind": "song"})
    assert "20" not in song and song["11"]["inputs"]["clip"] == ["10", 1]


def test_harmony_plans_get_the_lora_too():
    plan = jobs.build_plan_graph({**TAKE, "harmony": 3})
    assert plan["2"]["class_type"] == jobs.HARMONY_NODE and plan["2"]["inputs"]["clip"] == ["20", 1]


def test_instrumental_scores_pass_on_either_voice():
    assert score.problems(PLAN, instrumental=True) == []
    assert score.problems(INS_ONLY, instrumental=True) == []
    assert "no vocal part" in score.problems(INS_ONLY)


def test_the_api_creates_an_instrumental(client, monkeypatch):
    monkeypatch.setitem(jobs.ENGINE.options, "instrumental", False)
    monkeypatch.setattr(jobs.ENGINE, "options_loaded", True)
    monkeypatch.setitem(jobs.ENGINE.options, "checkpoints", [config.CHECKPOINT])
    assert client.post("/api/instrumentals", json={}).status_code == 400
    monkeypatch.setitem(jobs.ENGINE.options, "instrumental", True)
    assert client.post("/api/instrumentals", json={"structure": "[solo]"}).status_code == 400
    made = client.post("/api/instrumentals", json={"style": "surf rock", "structure": "[Intro] [Verse]",
                                                   "interpretation": "wide"}).json()
    row = one("SELECT * FROM takes WHERE id = ?", (made["id"],))
    assert (row["kind"], row["lyrics"], row["title"], row["interpretation"]) == ("instrumental", "[intro]\n[verse]", "Untitled instrumental", "wide")
    assert QUEUE.get_nowait() == {"kind": "plan", "id": made["id"]}
    drain()


def test_variations_of_an_instrumental_stay_instrumental(client):
    take = make_take(kind="instrumental", title="Coastal drive", lyrics="[instrumental]", abc=PLAN)
    made = client.post(f"/api/takes/{take['id']}/variations", json={"interpretations": ["loose"]}).json()["created"]
    assert one("SELECT kind FROM takes WHERE id = ?", (made[0]["id"],))["kind"] == "instrumental"
    drain()


def test_feel_sets_the_lora_strength_in_both_graphs():
    steady = jobs.build_plan_graph(TAKE)["20"]["inputs"]["strength_clip"]
    varied_plan = jobs.build_plan_graph({**TAKE, "feel": "varied"})["20"]["inputs"]["strength_clip"]
    varied_render = jobs.build_render_graph({**TAKE, "feel": "varied"})["20"]["inputs"]["strength_clip"]
    loose = instrumental.FEELS["varied"]
    assert (steady, varied_plan, varied_render) == (1.0, loose, loose)
    assert loose < 1.0   # it does loosen something, whatever the value is


def test_the_api_keeps_the_feel_and_variations_copy_it(client, monkeypatch):
    monkeypatch.setitem(jobs.ENGINE.options, "instrumental", True)
    monkeypatch.setattr(jobs.ENGINE, "options_loaded", True)
    monkeypatch.setitem(jobs.ENGINE.options, "checkpoints", [config.CHECKPOINT])
    assert client.post("/api/instrumentals", json={"feel": "wobbly"}).status_code == 400
    made = client.post("/api/instrumentals", json={"feel": "varied"}).json()
    assert one("SELECT feel FROM takes WHERE id = ?", (made["id"],))["feel"] == "varied"
    drain()
    take = make_take(kind="instrumental", title="Lemon", lyrics="[instrumental]", abc=PLAN)
    from app.db import execute
    execute("UPDATE takes SET feel = 'varied' WHERE id = ?", (take["id"],))
    copy = client.post(f"/api/takes/{take['id']}/variations", json={"interpretations": ["tight"]}).json()["created"][0]
    assert one("SELECT feel FROM takes WHERE id = ?", (copy["id"],))["feel"] == "varied"
    drain()


def test_varied_is_clear_of_the_strength_that_let_the_vocal_back_in():
    """0.8 sang on some seeds; every strength from 0.85 up was clean, including on
    the seed that failed.  Varied sits at 0.9: loose, and clear of it."""
    assert instrumental.FEELS["steady"] == 1.0
    assert instrumental.FEELS["varied"] == 0.9
    assert instrumental.FEELS["varied"] > 0.8


def test_a_silent_vocal_stem_is_not_called_singing(tmp_path):
    silence = tmp_path / "quiet.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                    "-t", "8", str(silence)], check=True)
    assert instrumental.sung_share(silence) == 0.0


def test_a_loud_vocal_stem_is_called_singing(tmp_path):
    tone = tmp_path / "loud.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=330:r=16000",
                    "-t", "8", str(tone)], check=True)
    assert instrumental.sung_share(tone) > instrumental.SUNG


def test_a_short_piece_is_checked_whole(tmp_path):
    short = tmp_path / "short.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:r=16000",
                    "-t", "5", str(short)], check=True)
    out = instrumental.excerpt(short, tmp_path / "out.wav")
    assert out.exists()
    assert abs(instrumental.duration_of(out) - 5) < 0.5


def test_a_long_piece_is_sampled_not_read_whole(tmp_path):
    long = tmp_path / "long.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:r=16000",
                    "-t", "120", str(long)], check=True)
    out = instrumental.excerpt(long, tmp_path / "out.wav")
    assert 25 < instrumental.duration_of(out) < 35
