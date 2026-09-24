"""What reaches the log: crashes, refusals, browser errors and hand-edited scores, and
never anything shaped like a key."""
import logging
import time

from app import logging_setup
from app.db import execute


def logged(fragment):
    return [e["message"] for e in logging_setup.LOG_BUFFER if fragment in e["message"]]


def test_keys_never_reach_a_log_line():
    log = logging.getLogger("yue2.test")
    # Built at run time, so this file holds nothing shaped like a key for a scanner to find.
    log.warning("calling https://example.com/v1?key=" + "AQ." + "x" * 40 + "&alt=json")
    log.warning("header Authorization: Bearer " + "sk-" + "y" * 30)
    log.warning("pasted AIza" + "B" * 35 + " into a field")
    joined = " ".join(e["message"] for e in list(logging_setup.LOG_BUFFER)[-3:])
    assert "x" * 40 not in joined and "y" * 30 not in joined and "B" * 35 not in joined
    assert "key=***" in joined and "Bearer ***" in joined


def test_a_crash_in_a_route_reaches_the_panel():
    """uvicorn logs a crash to uvicorn.error, whose parent does not propagate."""
    try:
        raise RuntimeError("boom in a route")
    except RuntimeError:
        logging.getLogger("uvicorn.error").exception("Exception in ASGI application")
    assert logged("Exception in ASGI application")


def test_a_refused_action_is_logged_and_a_poll_is_not(client):
    client.post("/api/takes/nosuchtake/render", json={})
    assert logged("Refused POST /api/takes/nosuchtake/render (404)")
    client.get("/api/takes/nosuchtake/peaks")
    assert not logged("Refused GET")


def test_an_invalid_request_is_logged_without_its_values(client):
    client.put("/api/settings", json={"key": "llm.api_key"})   # value missing
    lines = logged("Rejected PUT /api/settings")
    assert lines and "llm.api_key" not in " ".join(lines)


def test_a_browser_error_is_logged_and_capped(client):
    got = client.post("/api/logs/client", json={"message": "TypeError: x is null", "source": "app.js", "line": 12,
                                                "column": 4, "stack": "TypeError\n at paint (app.js:12:4)", "page": "/"})
    assert got.json()["logged"] and logged("Browser error on /: TypeError: x is null (app.js:12:4)")
    for _ in range(40):
        client.post("/api/logs/client", json={"message": "flood"})
    assert len(logged("flood")) <= 30


def test_a_score_edited_by_hand_is_logged_once(client):
    execute("""INSERT INTO takes(id, kind, title, style, lyrics, mode, seed, checkpoint, status, abc, created_at)
               VALUES('t1', 'song', 'Harbour', 'folk', '', 'full', 1, 'x', 'planned', 'X:1', ?)""", (time.time(),))
    client.put("/api/takes/t1/score", json={"abc": "X:1"})
    assert not logged("Score of take 'Harbour'"), "saving it unchanged, as a render does, says nothing"
    client.put("/api/takes/t1/score", json={"abc": "X:1\nK:C"})
    assert logged("Score of take 'Harbour' (t1) edited by hand (7 characters)")


def test_a_browser_dropping_a_connection_on_windows_is_not_logged_as_an_error():
    import logging

    from app.logging_setup import WindowsDisconnectNoise

    noise = WindowsDisconnectNoise()
    try:
        raise ConnectionResetError(10054, "An existing connection was forcibly closed by the remote host")
    except ConnectionResetError:
        import sys
        dropped = logging.LogRecord("asyncio", logging.ERROR, "", 0,
                                    "Exception in callback _ProactorBasePipeTransport._call_connection_lost()",
                                    None, sys.exc_info())
    other = logging.LogRecord("asyncio", logging.ERROR, "", 0, "Task exception was never retrieved", None, None)
    assert not noise.filter(dropped) and noise.filter(other)
