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
# Where DATA_DIR is on the host, when the app runs in a container, so a folder the
# app wrote can be named the way the user will find it.  Optional.
DATA_DIR_HOST = os.environ.get("DATA_DIR_HOST", "").rstrip("/")
# Where to put songs a corpus should be built from.  The app offers this folder to
# whoever is making one, so nothing has to be mounted or browsed for: copy the files
# in, and the corpus screen shows them.
CORPUS_INBOX = Path(os.environ.get("CORPUS_INBOX", str(DATA_DIR / "corpus")))
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
# The engine's input folder, so a training set can be put where the engine can read it.
ENGINE_INPUT_DIR = Path(os.environ["ENGINE_INPUT_DIR"]) if os.environ.get("ENGINE_INPUT_DIR") else None

# The largest recording the app will take.  Two gigabytes is a long lossless source:
# an eleven minute 24/96 FLAC is around 260 MB.  The engine has its own ceiling for
# what it will accept, set to the same number in compose.yml; if this is raised, that
# wants raising with it.
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "2048"))

# Folders the app may read songs from for an identity, as paths inside the container.
# compose.yml mounts them read-only.  Nothing under them is ever written.
IMPORT_ROOTS = [p.strip() for p in os.environ.get("IMPORT_ROOTS", "/import").split(",") if p.strip()]

# Host names the app answers to.  Anything else is refused, which stops DNS
# rebinding.  "*" turns the check off.
ALLOWED_HOSTS = [h.strip().lower() for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,::1").split(",") if h.strip()]

# The models the app uses.  One YuE2 checkpoint, and Gemma for writing lyrics.
CHECKPOINT = "yue2_3b_bf16.safetensors"
LYRICS_MODEL = "gemma4_e4b_it_int8_convrot.safetensors"
# The engine's model folder, when this machine can see it.  The app only reads
# from it, and only to say what a LoRA holds; the engine is what loads them.
MODELS_DIR = Path(os.environ.get("MODELS_DIR", "/app/models"))
INSTRUMENTAL_LORA = "ar_lora_inst_v3abc_comfyui.safetensors"
REAL_AUDIO_LORA = os.environ.get("REAL_AUDIO_LORA", "nar_lora_joint_v9_comfyui.safetensors")
TOKENIZER_HEAD = os.environ.get("TOKENIZER_HEAD", "tokenizer_head_joint_v9.safetensors")

DEFAULT_STYLE = "English, warm indie rock, expressive lead vocal, drums, bass, guitars, memorable melody, 110 BPM"

# How long a job may run once the engine has started it.  Time spent waiting in the
# engine's queue does not count.
TIMEOUTS = {"transcribe": 12 * 60, "plan": 10 * 60, "render": 25 * 60, "lyrics": 15 * 60,
            "identity_score": 12 * 60, "identity_style": 10 * 60,
            "persona_score": 12 * 60, "persona_style": 10 * 60,
            # Training is measured, not guessed: 5000 steps took 44 minutes on this
            # machine.  The allowance is generous because losing an hour of work to a
            # timeout would be worse than waiting.
            "train": 150 * 60}

# ---------------------------------------------------------------- LoRA training
#
# EXPERIMENTAL, AND OFF UNLESS IT IS BUILT IN.  Training a LoRA from a corpus is
# shipped disabled, and the engine image is built without the trainer node pack it
# needs.  To turn it on, build the engine with --build-arg WITH_TRAINER=1 and set
# TRAINING_ENABLED=1 for the app.
#
# Dual-branch training uses ComfyUI-FS_Audio_Suite (FSAudioArtistTrainer):
# trains the planner LoRA (what they write) and the decoder LoRA (how they sound)
# in one joint loop, exported as one file that applies to both halves.
# Evaluated against reference convergence targets (blgr_rhodope): artist loss ~4.635,
# regularizer loss ~3.576, decoder flow loss ~1.069.
TRAINING_ENABLED = os.environ.get("TRAINING_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")

# Dual-branch training parameters.
# Rule of thumb: ~10 passes over the artist songs (steps x batch_songs x artist_fraction / songs).
TRAIN_STEPS = int(os.environ.get("TRAIN_STEPS", "600"))
TRAIN_RANK_PLANNER = int(os.environ.get("TRAIN_RANK_PLANNER", "64"))
TRAIN_RANK_DECODER = int(os.environ.get("TRAIN_RANK_DECODER", "32"))
TRAIN_RANK = TRAIN_RANK_PLANNER
# Truncating songs at 3.5 minutes ensures all corpus tracks fit within the 8,192 token
# planner context and relieves VAE/SheetSage2 staging VRAM pressure.
TRAIN_MAX_MINUTES = float(os.environ.get("TRAIN_MAX_MINUTES", "3.5"))
TRAIN_END_TOKEN_WEIGHT = float(os.environ.get("TRAIN_END_TOKEN_WEIGHT", "1.0"))
TRAIN_CLIP_SECONDS = float(os.environ.get("TRAIN_CLIP_SECONDS", "30.0"))
REGULARIZER_PACK = os.environ.get("REGULARIZER_PACK", "minted_regularizer_pack_v2.pt")
# Give up on a job when the engine has been unreachable this long.
ENGINE_LOST_AFTER = 5 * 60

