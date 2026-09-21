"""Every test gets a fresh data folder.  The engine URL points at a closed port, so
the app starts with the engine offline, which is also a test of that path."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_BOOT = tempfile.mkdtemp(prefix="yue2-test-")
os.environ.update({
    "DATA_DIR": _BOOT,
    "VERSION_FILE": str(ROOT / "VERSION"),
    "ENGINE_URL": "http://127.0.0.1:9",
    "ALLOWED_HOSTS": "localhost,127.0.0.1,testserver",
    "MAX_UPLOAD_MB": "1",
})
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "yue2.sqlite")
    monkeypatch.setattr(config, "STEMS_DIR", tmp_path / "stems")
    monkeypatch.setattr(config, "TAKES_DIR", tmp_path / "takes")
    monkeypatch.setattr(config, "SOURCES_DIR", tmp_path / "sources")
    monkeypatch.setattr(config, "WORK_DIR", tmp_path / "tmp")
    monkeypatch.setattr(config, "CORPUS_INBOX", tmp_path / "corpus")
    from app import db
    db._settings_cache.clear()
    db.migrate()
    yield tmp_path


@pytest.fixture
def client(data_dir):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, base_url="http://localhost") as test_client:
        yield test_client


def make_take(**fields):
    import time
    import uuid
    from app.db import execute
    take = {
        "id": uuid.uuid4().hex[:12], "kind": "song", "source_id": None, "title": "Test song",
        "style": "rock", "lyrics": "[Verse]\nla la", "abc": "", "mode": "full", "seed": 1,
        "checkpoint": "yue2_3b_bf16.safetensors", "max_duration": 60, "status": "done",
        "created_at": time.time(), "audio_path": None,
    }
    take.update(fields)
    execute(
        """INSERT INTO takes(id, kind, source_id, title, style, lyrics, abc, mode, seed, checkpoint,
                             max_duration, status, created_at, audio_path)
           VALUES(:id, :kind, :source_id, :title, :style, :lyrics, :abc, :mode, :seed, :checkpoint,
                  :max_duration, :status, :created_at, :audio_path)""",
        take,
    )
    return take


def tone(path: Path, seconds: float = 2.0) -> Path:
    import subprocess
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    "-ar", "44100", str(path)], check=True)
    return path
