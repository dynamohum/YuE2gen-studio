"""The queue the page shows: the engine's own queue, including jobs sent by
something other than the app, then the app's jobs not yet sent."""
from app.engine import job_kind, queue_items
from app.jobs import CURRENT, ENGINE, QUEUE

from conftest import make_take

RENDER = {"10": {"class_type": "CheckpointLoaderSimple"}, "11": {"class_type": "YuE2GenerateMusic"}}
PLAN = {"2": {"class_type": "YuE2GenerateABCHarmony"}}
TEXT = {"2": {"class_type": "TextGenerate"}}


def test_kinds_from_the_nodes():
    assert job_kind({"YuE2GenerateMusic"}) == "render"
    assert job_kind({"YuE2GenerateABC"}) == "plan"
    assert job_kind({"SheetSage2AudioToABC"}) == "transcribe"
    assert job_kind({"TextGenerate"}) == "text"
    assert job_kind({"KSampler"}) == "other"


def test_queue_items_order_owner_and_running_time():
    raw = {"queue_running": [[7, "a", RENDER, {"client_id": "performance-test", "create_time": 1000_000}]],
           "queue_pending": [[9, "c", TEXT, {"client_id": "lyrics-test"}],
                             [8, "b", PLAN, {"client_id": "yue2-studio-1234abcd", "create_time": 2000_000}]]}
    since = {"gone": 1.0}
    items = queue_items(raw, since, now=50.0)
    assert [(i["prompt_id"], i["state"], i["kind"], i["mine"]) for i in items] == [
        ("a", "running", "render", False), ("b", "pending", "plan", True), ("c", "pending", "text", False)]
    assert items[0]["running_since"] == 50.0 and items[1]["queued_at"] == 2000.0
    assert since == {"a": 50.0}
    assert queue_items(raw, since, now=90.0)[0]["running_since"] == 50.0   # remembered, not reset


def test_state_lists_outside_jobs_the_current_job_and_waiting_takes(client, monkeypatch):
    running = make_take(title="Harbour light", status="running")
    waiting = make_take(title="Next up", status="queued")
    cancelled = make_take(title="Cancelled", status="failed")
    async def quiet():   # the keeper must not replace the queue mid-test
        return None
    monkeypatch.setattr(ENGINE, "refresh_status", quiet)
    monkeypatch.setattr(ENGINE, "client_id", "yue2-studio-feedf00d")
    monkeypatch.setattr(ENGINE, "queue", [
        {"prompt_id": "x", "state": "running", "kind": "render", "client": "performance-test", "mine": False,
         "queued_at": None, "running_since": 1.0},
        {"prompt_id": "p", "state": "pending", "kind": "render", "client": "yue2-studio-feedf00d", "mine": True,
         "queued_at": 2.0, "running_since": None},
        {"prompt_id": "old", "state": "pending", "kind": "plan", "client": "yue2-studio-00000000", "mine": True,
         "queued_at": 3.0, "running_since": None},
    ])
    CURRENT.clear()
    CURRENT.update({"kind": "render", "id": running["id"], "prompt_id": "p", "started": 0})
    while not QUEUE.empty():
        QUEUE.get_nowait()
    for take in (cancelled, waiting):
        QUEUE.put_nowait({"kind": "render", "id": take["id"]})
    try:
        queue = client.get("/api/state").json()["queue"]
    finally:
        CURRENT.clear()
        while not QUEUE.empty():
            QUEUE.get_nowait()
    assert [(q["state"], q["kind"], q["outside"], q.get("title"), q["client"]) for q in queue] == [
        ("running", "render", True, None, "performance-test"),
        ("pending", "render", False, "Harbour light", None),
        ("pending", "plan", False, None, None),
        ("waiting", "render", False, "Next up", None),
    ]
    assert queue[2]["note"] == "sent before the app restarted"
    assert queue[0]["seconds"] > 0 and queue[3]["seconds"] is None


def test_a_long_brief_is_cut_at_a_word_and_says_so():
    """A line that stops mid-word reads like the prompt was truncated; it was not."""
    from app.main import _shorten

    brief = ("a man cursed to live for a 1000 years wanders his ancient castle "
             "waiting for the love of his life to return")
    short = _shorten(brief, 60)
    assert short == "a man cursed to live for a 1000 years wanders his ancient…"
    assert len(short) <= 61 and not short[:-1].endswith(" ")
    assert _shorten("a sad song about rain", 60) == "a sad song about rain"
    assert _shorten("  spaced   out  words ", 60) == "spaced out words"
