"""A render that loses its footing comes out quiet from end to end, thin and noisy.
Its level is recorded, and a take far below the rest is flagged."""
import subprocess
import time

from app import config
from app.db import execute, one
from app.library import fill_loudness, loudness


def tone(path, volume):
    """ffmpeg's sine is generated at an eighth of full scale, so volume 3 is a normal level."""
    subprocess.run(["ffmpeg", "-v", "quiet", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                    "-af", f"volume={volume}", "-ac", "2", str(path)], check=True)
    return path


def test_a_quiet_render_reads_below_the_line_and_a_normal_one_above(tmp_path):
    normal = loudness(tone(tmp_path / "normal.flac", 3))
    weak = loudness(tone(tmp_path / "weak.flac", 0.15))
    assert normal > config.WEAK_RENDER_DB > weak


def test_silence_is_the_quietest_there_is(tmp_path):
    silent = tmp_path / "silent.flac"
    subprocess.run(["ffmpeg", "-v", "quiet", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "2",
                    str(silent)], check=True)
    assert loudness(silent) <= -90


def test_a_file_that_is_not_audio_has_no_level(tmp_path):
    junk = tmp_path / "junk.flac"
    junk.write_bytes(b"not audio")
    assert loudness(junk) is None


def test_takes_made_before_the_check_are_filled_in(client, tmp_path):
    audio = tone(tmp_path / "old.flac", 0.15)
    execute("""INSERT INTO takes(id, kind, title, style, lyrics, mode, seed, checkpoint, status, audio_path, created_at)
               VALUES('old1', 'song', 'old', 'pop', '', 'full', 1, 'yue2.safetensors', 'done', ?, ?)""", (str(audio), time.time()))
    assert fill_loudness() == 1
    assert one("SELECT loudness FROM takes WHERE id = 'old1'")["loudness"] < config.WEAK_RENDER_DB
    assert fill_loudness() == 0, "a take is read once"


def test_the_page_is_told_where_the_line_is(client):
    assert client.get("/api/state").json()["options"]["weak_render_db"] == config.WEAK_RENDER_DB
