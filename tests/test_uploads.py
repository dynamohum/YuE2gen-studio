"""The engine's input folder is a copy the app can make again, so it is swept."""
import os
import time

from app import config, main


def test_finished_uploads_are_removed_and_the_cache_is_kept(tmp_path, monkeypatch):
    root = tmp_path / "engine-input"
    root.mkdir()
    old = root / "a-source.mp3"
    old.write_bytes(b"x")
    os.utime(old, (time.time() - 48 * 3600, time.time() - 48 * 3600))

    fresh = root / "just-sent.mp3"
    fresh.write_bytes(b"x")

    # A training run's encoded latents live in a folder here, and rebuilding them
    # costs twenty five seconds per corpus, so folders are left alone.
    cache = root / "lora-cache"
    cache.mkdir()
    (cache / "latents.npy").write_bytes(b"x")

    monkeypatch.setattr(config, "ENGINE_INPUT_DIR", root)
    main.sweep_engine_input()

    assert not old.exists(), "a day old upload goes"
    assert fresh.exists(), "one just sent stays"
    assert (cache / "latents.npy").exists(), "a folder is not touched"


def test_sweeping_without_an_engine_folder_is_harmless(monkeypatch):
    monkeypatch.setattr(config, "ENGINE_INPUT_DIR", None)
    main.sweep_engine_input()
