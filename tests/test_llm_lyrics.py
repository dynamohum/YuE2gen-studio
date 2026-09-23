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
    return asyncio.run(jobs.hear(Path("/nowhere/vocals.wav"), 40.0, title="Silly Love Songs"))


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


# ------------------------------------------------------------ what the log says

def first_line(caplog):
    return next(r.getMessage() for r in caplog.records if r.getMessage().startswith("Lyrics for"))


def test_the_log_says_up_front_when_the_llm_will_listen(whisper, monkeypatch, caplog):
    """Whisper's own lines appear either way, so the method is stated before them."""
    async def heard(vocal):
        return list(HEARD)
    monkeypatch.setattr(llm, "hear_lyrics", heard)
    external()
    set_setting("lyrics.transcriber", "llm")
    caplog.set_level("INFO")
    hear()
    assert first_line(caplog) == ("Lyrics for 'Silly Love Songs': the external LLM (gemini-3.8-flash) "
                                  "will hear the words; Whisper runs first to time the lines")
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "sending the vocal to gemini-3.8-flash" in said
    assert "gemini-3.8-flash heard 3 lines, where Whisper heard 2" in said


def test_the_log_says_when_whisper_is_the_setting(whisper, monkeypatch, caplog):
    monkeypatch.setattr(llm, "hear_lyrics", refuse)
    external()
    caplog.set_level("INFO")
    hear()
    assert first_line(caplog) == "Lyrics for 'Silly Love Songs': Whisper, as set in Settings"


def test_the_log_says_why_the_llm_setting_was_not_used(whisper, monkeypatch, caplog):
    monkeypatch.setattr(llm, "hear_lyrics", refuse)
    set_setting("llm.provider", "local")
    set_setting("lyrics.transcriber", "llm")
    caplog.set_level("INFO")
    hear()
    assert "provider is not External LLM" in first_line(caplog)


# ------------------------------------------------- a reply that is not the whole song

def test_a_trailing_line_is_not_a_held_back_reply():
    assert llm.held_back(["Hold on…", "Modern girl"]) is None


def test_lines_cut_short_are_held_back():
    """What the Gemini app did with a well-known song: every section cut to "..."."""
    assert llm.held_back(["You'd think that people would've had enough...", "I love you..."]) == "cut lines short"


def test_a_notice_about_lyrics_is_held_back():
    note = ("You can view the complete, licensed lyrics by searching for the song on Google "
            "or visiting major lyric databases like Genius or LyricFind.")
    assert llm.held_back(["I love you", note]) == "wrote a notice instead of the full lyrics"
    assert llm.held_back(["I cannot provide the lyrics to this song"]) is not None


def test_sung_words_that_look_like_a_notice_are_not():
    assert llm.held_back(["Love is a genius thing", "Complete me, baby",
                          "I wrote you the lyrics of my heart", "Search your soul"]) is None


def test_a_held_back_reply_falls_back_and_says_why(whisper, monkeypatch):
    """The agreement check would pass it: every word it does give is in the song."""
    async def cut(vocal):
        return ["I walked into a trap...", "Modern girl..."]
    monkeypatch.setattr(llm, "hear_lyrics", cut)
    external()
    set_setting("lyrics.transcriber", "llm")
    lines, method = hear()
    assert lines == WHISPER
    assert method == "Whisper (gemini-3.8-flash cut lines short)"


def test_far_fewer_words_than_whisper_heard_falls_back(whisper, monkeypatch):
    async def short(vocal):
        return ["Modern girl"]
    monkeypatch.setattr(llm, "hear_lyrics", short)
    external()
    set_setting("lyrics.transcriber", "llm")
    lines, method = hear()
    assert lines == WHISPER
    assert "returned 2 words where Whisper heard 10" in method
