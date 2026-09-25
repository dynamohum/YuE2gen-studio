"""Corpus lyrics with their sections marked by the external LLM, from the words as
heard: the lines never change, and a reply that loses one falls back."""
import asyncio
import json

import pytest

from app import jobs, llm
from app.db import execute, one

LINES = [{"start": 8.7, "end": 10.6, "text": "Good day sunshine"},
         {"start": 11.5, "end": 13.4, "text": "Good day sunshine"},
         {"start": 17.2, "end": 20.0, "text": "I need to laugh"},
         {"start": 21.0, "end": 24.6, "text": "And when the sun is out"}]


def reply_with(sections):
    return "Here you are:\n```json\n" + json.dumps(sections) + "\n```"


def test_the_reply_becomes_tagged_lines_as_heard(monkeypatch):
    async def chat(messages, **kw):
        prompt = messages[-1]["content"]
        assert "3. [17.2s, after a 3.8s pause] I need to laugh" in prompt
        assert "Good Day Sunshine" not in prompt          # the lines and times only, never the title
        # No Intro in the reply: singing from 8.7 s has one before it, so it is added.
        return reply_with([{"tag": "Chorus", "from": 1, "to": 2}, {"tag": "Verse 1", "from": 3, "to": 4}])
    monkeypatch.setattr(llm, "chat_complete", chat)
    blocks = asyncio.run(llm.tag_sections(LINES))
    assert blocks == [("Intro", []), ("Chorus", ["Good day sunshine", "Good day sunshine"]),
                      ("Verse", ["I need to laugh", "And when the sun is out"])]


@pytest.mark.parametrize("sections, why", [
    ([{"tag": "Chorus", "from": 1, "to": 2}, {"tag": "Verse", "from": 3, "to": 3}], "covered 3 of 4"),
    ([{"tag": "Chorus", "from": 1, "to": 2}, {"tag": "Verse", "from": 4, "to": 4}], "out of order"),
    ([{"tag": "Hook", "from": 1, "to": 4}], "unknown section"),
    ([{"tag": "Verse"}, {"tag": "Chorus", "from": 1, "to": 4}], "Verse with no lines"),
])
def test_a_reply_that_loses_or_reorders_a_line_is_refused(sections, why):
    with pytest.raises(ValueError, match=why):
        llm._section_reply(reply_with(sections), 4)


def corpus_song(tmp_path, lines=LINES):
    folder = tmp_path / "song"
    folder.mkdir()
    (folder / "original.flac").write_bytes(b"x")
    (folder / "whisper.json").write_text(json.dumps(lines), encoding="utf-8")
    execute("INSERT INTO identities(id, name, trigger_word, folder, consent, created_at) VALUES('c1', 'Beatles', 'b', '/x', 1, 0)")
    execute("""INSERT INTO identity_songs(id, identity_id, file, title, sha256, duration, include, vocals_state,
                                          lyrics_state, score_state, stored_path, position)
               VALUES('s1', 'c1', 'a.flac', 'Good Day Sunshine', 'x', 30, 1, 'done', 'running', 'done', ?, 0)""",
            (str(folder / "original.flac"),))


def draft_with(monkeypatch, chat):
    monkeypatch.setattr(llm, "is_external_enabled", lambda: True)
    monkeypatch.setattr(llm, "chat_complete", chat)

    async def run():
        jobs.maybe_draft("s1")
        assert one("SELECT lyrics_state FROM identity_songs WHERE id = 's1'")["lyrics_state"] == "running"
        await asyncio.gather(*jobs._DRAFTING)
    asyncio.run(run())
    return one("SELECT lyrics, lyrics_state FROM identity_songs WHERE id = 's1'")


def test_with_an_external_llm_the_draft_is_marked_from_the_words(tmp_path, monkeypatch):
    corpus_song(tmp_path)

    async def chat(messages, **kw):
        return reply_with([{"tag": "Chorus", "from": 1, "to": 2}, {"tag": "Verse", "from": 3, "to": 4}])
    row = draft_with(monkeypatch, chat)
    assert row["lyrics_state"] == "done"
    assert row["lyrics"] == "[Intro]\n\n[Chorus]\nGood day sunshine\nGood day sunshine\n\n[Verse]\nI need to laugh\nAnd when the sun is out"


def test_when_the_llm_fails_the_music_analysis_draft_is_kept(tmp_path, monkeypatch):
    corpus_song(tmp_path)

    async def chat(messages, **kw):
        raise RuntimeError("the provider is down")
    row = draft_with(monkeypatch, chat)
    assert row["lyrics_state"] == "done"
    assert row["lyrics"] == "[Verse]\nGood day sunshine\nGood day sunshine\nI need to laugh\nAnd when the sun is out"


def test_a_song_stopped_while_the_llm_works_keeps_nothing_it_returns(tmp_path, monkeypatch):
    corpus_song(tmp_path)

    async def chat(messages, **kw):
        jobs.set_song("s1", lyrics_state="none")       # stopped meanwhile
        return reply_with([{"tag": "Verse", "from": 1, "to": 4}])
    row = draft_with(monkeypatch, chat)
    assert (row["lyrics"], row["lyrics_state"]) == ("", "none")


def test_redraft_tags_the_heard_lines_again_and_replaces_checked_words(client, tmp_path, monkeypatch):
    corpus_song(tmp_path)
    execute("UPDATE identity_songs SET lyrics = 'my own words', lyrics_checked = 1, lyrics_state = 'done' WHERE id = 's1'")
    url = "/api/identities/c1/songs/s1/lyrics/redraft"
    monkeypatch.setattr(llm, "is_external_enabled", lambda: False)
    assert client.post(url).status_code == 400                      # only with the external LLM
    assert client.get("/api/identities/c1").json()["external_llm"] is False
    monkeypatch.setattr(llm, "is_external_enabled", lambda: True)

    async def chat(messages, **kw):
        return reply_with([{"tag": "Chorus", "from": 1, "to": 2}, {"tag": "Verse", "from": 3, "to": 4}])
    monkeypatch.setattr(llm, "chat_complete", chat)
    assert client.post(url).json() == {"lyrics_state": "running"}
    for _ in range(100):
        row = one("SELECT lyrics, lyrics_checked, lyrics_state FROM identity_songs WHERE id = 's1'")
        if row["lyrics_state"] == "done":
            break
        import time
        time.sleep(0.02)
    assert row["lyrics"].startswith("[Intro]\n\n[Chorus]\nGood day sunshine") and row["lyrics_checked"] == 0
    execute("UPDATE identity_songs SET lyrics_state = 'running' WHERE id = 's1'")
    assert client.post(url).status_code == 409                      # already drafting
    execute("UPDATE identity_songs SET stored_path = NULL, lyrics_state = 'done' WHERE id = 's1'")
    assert client.post(url).status_code == 400                      # nothing heard yet
