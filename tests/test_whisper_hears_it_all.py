"""Whisper listens to the whole vocal.  Its voice detector, built for speech, threw
most singing away before listening; with it off, against real lyrics, Modern Girl
went from 10.7% of words wrong to 1.5% and Silly Love Songs from 56% to 25%."""
from types import SimpleNamespace

import pytest

from app import identities


class FakeWhisper:
    """Stands in for faster-whisper: records what it was asked, returns set segments."""
    def __init__(self, texts):
        self.texts, self.asked = texts, None

    def transcribe(self, path, **kwargs):
        self.asked = kwargs
        segs = [SimpleNamespace(start=10.0 * i, end=10.0 * i + 4.0, text=t) for i, t in enumerate(self.texts)]
        return iter(segs), None


@pytest.fixture
def whisper(monkeypatch):
    def use(texts):
        fake = FakeWhisper(texts)
        monkeypatch.setattr(identities, "_whisper", fake)
        return fake
    return use


def test_the_voice_detector_is_off(whisper, tmp_path):
    fake = whisper(["I walked into a trap I set myself"])
    identities.transcribe(tmp_path / "vocals.flac")
    assert fake.asked["vad_filter"] is False, "it threw away most of a sung vocal"


def test_what_is_invented_over_silence_is_guarded_against(whisper, tmp_path):
    """The detector used to hide the silences; without it the guard has to."""
    fake = whisper(["Modern girl"])
    identities.transcribe(tmp_path / "vocals.flac")
    assert fake.asked["hallucination_silence_threshold"] == 2.0
    assert fake.asked["word_timestamps"] is True, "the silence guard needs word times"


def test_whispers_stock_lines_are_dropped(whisper, tmp_path):
    whisper(["I walked into a trap I set myself", "Thank you.", "Thanks for watching!", "Modern girl"])
    lines = identities.transcribe(tmp_path / "vocals.flac")
    assert [l["text"] for l in lines] == ["I walked into a trap I set myself", "Modern girl"]


def test_a_real_line_that_starts_the_same_way_is_kept(whisper, tmp_path):
    whisper(["Thank you for loving me", "Thank you, baby"])
    lines = identities.transcribe(tmp_path / "vocals.flac")
    assert [l["text"] for l in lines] == ["Thank you for loving me", "Thank you, baby"]


def test_a_dropped_line_keeps_the_others_timing(whisper, tmp_path):
    """Two sentences in one segment share its time; dropping one must not shift the other."""
    whisper(["Thank you. Modern girl."])
    lines = identities.transcribe(tmp_path / "vocals.flac")
    assert len(lines) == 1 and lines[0]["text"] == "Modern girl"
    assert lines[0]["start"] > 0.0, "it keeps its place after the dropped line"
