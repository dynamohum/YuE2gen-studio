import json

from app import config
from app.library import audio_duration, compute_peaks, ensure_peaks, inside, peaks_path, slugify, source_path

from conftest import tone


def test_slugify():
    assert slugify("Modern Girl (demo)!") == "modern-girl-demo"
    assert slugify("") == "untitled"
    assert len(slugify("x" * 100)) == 40


def test_source_path_keeps_the_name_after_the_hash():
    path = source_path("f72ac22518a9ea05ffff", "Modern Girl.wav", "fallback", ".wav")
    assert path == config.SOURCES_DIR / "f72ac22518a9ea05-modern-girl.wav"


def test_inside():
    assert inside(config.DATA_DIR / "stems" / "a", config.DATA_DIR)
    assert not inside(config.DATA_DIR / ".." / "elsewhere", config.DATA_DIR)


def test_duration_of_flac_from_the_header_and_mp3_from_ffprobe(data_dir):
    assert abs(audio_duration(tone(data_dir / "a.flac", 2.0)) - 2.0) < 0.05
    assert abs(audio_duration(tone(data_dir / "a.mp3", 3.0)) - 3.0) < 0.1


def test_peaks_are_normalised_and_cached(data_dir):
    audio = tone(data_dir / "a.flac", 1.5)
    result = compute_peaks(audio)
    assert result["columns"] == len(result["peaks"]) == len(result["rms"]) == 1024
    assert max(result["peaks"]) == 1.0 and min(result["peaks"]) >= 0
    cached = ensure_peaks(audio)
    assert json.loads(peaks_path(audio).read_text()) == cached


def test_peaks_of_a_very_short_file(data_dir):
    result = compute_peaks(tone(data_dir / "short.wav", 0.05))
    assert len(result["peaks"]) == 1024
