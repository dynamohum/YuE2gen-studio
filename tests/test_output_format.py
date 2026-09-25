"""One output format, set in Settings, for stems and for a take's Save.  A setting
that only repeats its default is not stored, so a better default reaches everyone."""
import subprocess

from app.db import get_setting, set_setting

from conftest import make_take, tone


def test_saving_a_default_does_not_store_it(client):
    client.put("/api/settings", json={"key": "stems.format", "value": "flac"})
    assert get_setting("stems.format") is None
    client.put("/api/settings", json={"key": "stems.format", "value": "mp3"})
    assert get_setting("stems.format") == "mp3"


def test_old_frozen_defaults_are_forgotten_at_start(client):
    from app.main import forget_frozen_defaults

    set_setting("stems.format", "wav")               # the old default, stored by a save
    set_setting("stems.model", "htdemucs")           # the default, stored by a save
    set_setting("instrumental.vocal_check", "off")   # a real choice
    assert forget_frozen_defaults() == 2
    assert get_setting("stems.format") is None and get_setting("stems.model") is None
    assert get_setting("instrumental.vocal_check") == "off"


def test_the_setting_is_named_for_takes_too(client):
    item = {s["key"]: s for s in client.get("/api/settings").json()["settings"]}["stems.format"]
    assert item["label"] == "Output audio format" and item["value"] == "flac"
    assert "takes" in item["help"]


def probe(content: bytes, tmp_path) -> str:
    path = tmp_path / "got"
    path.write_bytes(content)
    return subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
                          capture_output=True, text=True).stdout.strip()


def test_save_hands_over_a_take_in_the_chosen_format(client, tmp_path):
    take = make_take(title="Save Me", audio_path=str(tone(tmp_path / "take.flac", 1.0)))
    url = f"/api/takes/{take['id']}/audio?download=1"

    got = client.get(url)
    assert got.headers["content-type"] == "audio/flac" and "Save%20Me.flac" in got.headers["content-disposition"]
    assert probe(got.content, tmp_path) == "flac"

    set_setting("stems.format", "wav")
    got = client.get(url)
    assert got.headers["content-type"] == "audio/wav" and "Save%20Me.wav" in got.headers["content-disposition"]
    assert probe(got.content, tmp_path) == "pcm_s16le"

    set_setting("stems.format", "mp3")
    got = client.get(url)
    assert got.headers["content-type"] == "audio/mpeg" and probe(got.content, tmp_path) == "mp3"

    # Playing is always the FLAC as kept, whatever the setting.
    assert client.get(f"/api/takes/{take['id']}/audio").headers["content-type"] == "audio/flac"


def test_save_can_ask_for_a_format_over_the_setting(client, tmp_path):
    take = make_take(title="Pick", audio_path=str(tone(tmp_path / "take.flac", 1.0)))
    url = f"/api/takes/{take['id']}/audio?download=1"
    set_setting("stems.format", "mp3")

    got = client.get(url + "&format=wav")
    assert got.headers["content-type"] == "audio/wav" and "Pick.wav" in got.headers["content-disposition"]
    got = client.get(url + "&format=flac")
    assert got.headers["content-type"] == "audio/flac" and probe(got.content, tmp_path) == "flac"
    assert client.get(url + "&format=ogg").status_code == 400
