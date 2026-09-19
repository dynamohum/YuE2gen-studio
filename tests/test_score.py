"""Telling a usable score from a broken one, and what the app does with a broken one."""
import asyncio

from app import jobs, score
from app.db import execute, one

from conftest import make_take

# The plan Plan variety "wild" wrote for "test1": garbled voice headers, no vocal part.
BROKEN = ('X:1\nT:\nM:4/4\nL:1/32\nQ:1/4=97\nV Vocal cle"treble name="Vocal Melody" snm="Vocal"\n'
          'Vocal=treble name="Ins Melody" snm="Inst."\nK:F#\n% intro\n'
          'V: Insus2"A6A6F8z8E,2F,2|"Bmaj7/D#"C6D,8-D,,2-"G#dim"G,,16-|\n% verse\n')
GOOD = ('X:1\nT:\nM:4/4\nL:1/32\nQ:1/4=97\nV: Vocal clef=treble name="Vocal Melody" snm="Vocal"\n'
        'V: Ins clef=treble name="Ins Melody" snm="Inst."\nK:Dm\n% intro\nV: Vocal\n'
        'z24z4"Dm"z4|"Dm"z32|"Dm"z32|"Bbmaj7"z32|\nV: Ins\nZ|D2F2E2F2|D,4D,4|B,,4A,4|\n'
        'V: Vocal\n"Gm"z32|"Bm7b5"z32|"C7/Bb"z16"Bm7"z16|"Bm7"z32|\n')
NO_CHORDS = GOOD.replace('"Dm"', '').replace('"Bbmaj7"', '').replace('"Gm"', '').replace('"Bm7b5"', '') \
                .replace('"C7/Bb"', '').replace('"Bm7"', '')


def test_problems():
    assert score.problems(GOOD) == []
    assert score.problems(BROKEN) == ["no vocal part"]
    assert score.problems(NO_CHORDS) == ["no chord symbols"]
    assert score.problems(NO_CHORDS, need_chords=False) == []
    assert score.problems('X:1\nV: Vocal\n"C"z8|\n') == ["no key", "only 1 bar"]
    assert len(score.vocal_bars(GOOD)) == 8   # header voice lines are not bars


class PlanEngine:
    def __init__(self, abc):
        self.abc = abc
        self.last_contact = __import__("time").time()

    async def submit(self, graph):
        return "pid"

    async def history(self, pid):
        return {"status": {"status_str": "success", "completed": True},
                "prompt": [0, "pid", {"3": {"class_type": "PreviewAny"}}], "outputs": {"3": {"text": [self.abc]}}}

    def has_started(self, pid):
        return True

    async def cancel(self, pid):
        pass

    def forget(self, pid):
        pass


def test_an_unreadable_plan_fails_instead_of_landing(monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(jobs.asyncio, "sleep", lambda _s: real_sleep(0))
    monkeypatch.setattr(jobs, "ENGINE", PlanEngine(BROKEN))
    while not jobs.QUEUE.empty():   # left over from API tests
        jobs.QUEUE.get_nowait()
    take = make_take(status="queued")
    execute("UPDATE takes SET variety = 'wild', auto_render = 1 WHERE id = ?", (take["id"],))
    asyncio.run(jobs.run_job("plan", take["id"]))
    row = one("SELECT status, error, abc FROM takes WHERE id = ?", (take["id"],))
    assert row["status"] == "failed" and not row["abc"]
    assert "unreadable (no vocal part)" in row["error"] and "calmer Plan variety" in row["error"]
    assert jobs.QUEUE.empty()   # auto-render did not queue a render


def test_a_broken_score_is_not_rendered(client):
    take = make_take(status="done", abc=BROKEN)
    refused = client.post(f"/api/takes/{take['id']}/render")
    assert refused.status_code == 400 and "no vocal part" in refused.json()["detail"]
    fine = make_take(status="done", abc=GOOD)
    assert client.post(f"/api/takes/{fine['id']}/render").status_code == 200
