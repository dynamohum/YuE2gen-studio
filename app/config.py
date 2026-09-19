"""Settings that come from the environment, read once at import."""
from __future__ import annotations

import os
from pathlib import Path

# compose.yml sets this to the engine service name.  The fallback suits running the
# app outside Docker against an engine on the same machine.
ENGINE_URL = os.environ.get("ENGINE_URL", "http://127.0.0.1:8188")

# The version lives in ./VERSION at the repo root, copied into the image by the
# Dockerfile.  It is shown in the header so a running container can be identified.
VERSION_FILE = Path(os.environ.get("VERSION_FILE", "/app/VERSION"))
try:
    VERSION = VERSION_FILE.read_text(encoding="utf-8").strip()
except OSError:
    VERSION = "unknown"

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
PORT = int(os.environ.get("PORT", "8090"))
DB_PATH = DATA_DIR / "yue2.sqlite"
STEMS_DIR = DATA_DIR / "stems"
TAKES_DIR = DATA_DIR / "takes"
SOURCES_DIR = DATA_DIR / "sources"
# Scratch space on the same filesystem as the library, so finished work is moved
# into place with a rename rather than a copy.  Emptied on every start.
WORK_DIR = DATA_DIR / "tmp"

# The engine's output folder, when the app can see it (compose.yml mounts it).  A
# rendered file is deleted from there once the app has its own copy.  Unset in the
# split setup, where the folder lives on another machine.
ENGINE_OUTPUT_DIR = Path(os.environ["ENGINE_OUTPUT_DIR"]) if os.environ.get("ENGINE_OUTPUT_DIR") else None

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "300"))

# Host names the app answers to.  Anything else is refused, which stops DNS
# rebinding.  "*" turns the check off.
ALLOWED_HOSTS = [h.strip().lower() for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,::1").split(",") if h.strip()]

# The models the app uses.  One YuE2 checkpoint, and Gemma for writing lyrics.
CHECKPOINT = "yue2_3b_bf16.safetensors"
LYRICS_MODEL = "gemma4_e4b_it_int8_convrot.safetensors"

DEFAULT_STYLE = "English, warm indie rock, expressive lead vocal, drums, bass, guitars, memorable melody, 110 BPM"

# How long a job may run once the engine has started it.  Time spent waiting in the
# engine's queue does not count.
TIMEOUTS = {"transcribe": 12 * 60, "plan": 10 * 60, "render": 25 * 60, "lyrics": 15 * 60}
# Give up on a job when the engine has been unreachable this long.
ENGINE_LOST_AFTER = 5 * 60
