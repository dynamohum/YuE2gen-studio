"""Hearing a recording's lyrics with an external LLM, and Whisper keeping the time.

Measured on Modern Girl against its real lyrics: Whisper 8.8% of words wrong,
nearly all of them lines it missed; Gemini 1.5%, the same in three runs. These
pin how the two are combined and every way back to Whisper.
"""
import asyncio
import time
from pathlib import Path

import pytest

from app import identities, jobs, llm
from app.db import execute, one, set_setting

WHISPER = [
    {"start": 10.0, "end": 14.0, "text": "I walked into a trap I set myself"},
    # "Always the last to know" is sung here, and Whisper misses it.
    {"start": 30.0, "end": 33.0, "text": "Modern girl"},
]
HEARD = ["I walked into a trap I set myself", "Always the last to know", "Modern girl"]


def test_matched_lines_take_whispers_times():
    timed = identities.time_lines(WHISPER, HEARD)
    assert timed[0]["text"] == "I walked into a trap I set myself"
    assert 10.0 <= timed[0]["start"] <= timed[0]["end"] <= 14.0
    assert 30.0 <= timed[2]["start"] <= 33.0


def test_a_line_whisper_missed_is_placed_between_its_neighbours():
    """The whole point: the lines an LLM recovers are the ones with no time."""
    timed = identities.time_lines(WHISPER, HEARD)
    missed = timed[1]
    assert missed["text"] == "Always the last to know"
    assert timed[0]["end"] < missed["start"] < timed[2]["start"]


def test_words_that_are_not_this_recording_are_refused():
    """A famous song written out from memory barely matches what was sung."""
    other = ["Yesterday all my troubles seemed so far away", "Now it looks as though they're here to stay"]
    assert identities.time_lines(WHISPER, other) is None


def test_the_reply_loses_labels_fences_and_markup():
    reply = "```\n[Verse]\n**I walked into a trap**\nModern girl\n(instrumental)\n\n```"
    assert llm._hear_lines(reply) == ["I walked into a trap", "Modern girl"]


# ------------------------------------------------------------ choosing a method

@pytest.fixture
def whisper(monkeypatch):
    monkeypatch.setattr(identities, "transcribe", lambda vocal, on_progress=None, duration=0.0: list(WHISPER))


def hear():
    return asyncio.run(jobs.hear(Path("/nowhere/vocals.wav"), 40.0))


def refuse(*args, **kwargs):
    raise AssertionError("the LLM should not have been asked")


def external(model="gemini-3.8-flash", url="https://generativelanguage.googleapis.com"):
    set_setting("llm.provider", "external")
    set_setting("llm.model", model)
    set_setting("llm.api_url", url)


def test_whisper_is_the_default(whisper, monkeypatch):
    monkeypatch.setattr(llm, "hear_lyrics", refuse)
    external()
    lines, method = hear()
    assert method == "Whisper" and lines == WHISPER


def test_the_setting_does_nothing_without_an_external_provider(whisper, monkeypatch):
    monkeypatch.setattr(llm, "hear_lyrics", refuse)
    set_setting("llm.provider", "local")
    set_setting("lyrics.transcriber", "llm")
    assert hear()[1] == "Whisper"


def test_the_llm_hears_and_whisper_times(whisper, monkeypatch):
    async def heard(vocal):
        return list(HEARD)
    monkeypatch.setattr(llm, "hear_lyrics", heard)
    external()
    set_setting("lyrics.transcriber", "llm")
    lines, method = hear()
    assert [l["text"] for l in lines] == HEARD
    assert method == "gemini-3.8-flash, timed by Whisper"


def test_a_model_that_cannot_take_audio_falls_back_and_says_why(whisper, monkeypatch):
    async def fails(vocal):
        raise RuntimeError("External LLM HTTP 400: audio input is not supported")
    monkeypatch.setattr(llm, "hear_lyrics", fails)
    external("gpt-4o-mini", "https://api.openai.com/v1")
    set_setting("lyrics.transcriber", "llm")
    lines, method = hear()
    assert lines == WHISPER
    assert method.startswith("Whisper (gpt-4o-mini could not take the audio")
    assert "not supported" in method


def test_words_that_do_not_match_fall_back_and_say_so(whisper, monkeypatch):
    async def other(vocal):
        return ["Yesterday all my troubles seemed so far away"]
    monkeypatch.setattr(llm, "hear_lyrics", other)
    external()
    set_setting("lyrics.transcriber", "llm")
    lines, method = hear()
    assert lines == WHISPER and "did not match" in method


# ---------------------------------------------------------- the setting and the API

def test_the_setting_needs_an_external_provider(client):
    spec = {item["key"]: item for item in client.get("/api/settings").json()["settings"]}
    item = spec["lyrics.transcriber"]
    assert item["value"] == "whisper"
    assert item["requires"] == {"llm.provider": "external"}
    assert item["requires_note"]


def test_the_setting_takes_only_its_own_values(client):
    assert client.put("/api/settings", json={"key": "lyrics.transcriber", "value": "llm"}).status_code == 200
    assert client.put("/api/settings", json={"key": "lyrics.transcriber", "value": "gemini"}).status_code == 400


def test_the_lyrics_endpoint_says_who_heard_them(client):
    execute("""INSERT INTO sources (id, title, filename, stored_path, sha256, created_at, lyrics,
               lyrics_state, lyrics_method) VALUES ('s1', 'Modern Girl', 'mg.flac', '/data/mg.flac',
               '0', ?, '[Verse]\nModern girl', 'done', 'gemini-3.8-flash, timed by Whisper')""", (time.time(),))
    got = client.get("/api/sources/s1/lyrics").json()
    assert got["method"] == "gemini-3.8-flash, timed by Whisper"
