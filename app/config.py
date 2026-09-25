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
# On by default.  TRAINING_ENABLED=0 takes Corpora and training out of the app, and an
# engine built with --build-arg WITH_TRAINER=0 leaves out the trainer node pack; the
# app offers training only when both are in.
#
# Dual-branch training uses ComfyUI-FS_Audio_Suite (FSAudioArtistTrainer):
# trains the planner LoRA (what they write) and the decoder LoRA (how they sound)
# in one joint loop, exported as one file that applies to both halves.
# Evaluated against reference convergence targets (blgr_rhodope): artist loss ~4.635,
# regularizer loss ~3.576, decoder flow loss ~1.069.
TRAINING_ENABLED = os.environ.get("TRAINING_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")

# Dual-branch training parameters, following the trainer's own guidance and the
# published LoRAs made with it (blgr, mltnt, cnzn, chnsn, qwwl, drksf).  Those ran
# 300-500 planner steps over two songs a step, with the score never put in front,
# and their authors picked a checkpoint by ear.  A fixed 600 steps of one song a step,
# whatever the corpus, means many passes over a small one: the planner memorises, and
# the decoder -- conditioned on that drifting planner, with one update a step -- gets
# worse throughout.
#
# Planner steps come from the corpus size: TRAIN_PASSES over each song, the rule of
# thumb in the trainer (steps x batch_songs x artist_fraction / songs), rounded up to
# a checkpoint, and never fewer than TRAIN_MIN_STEPS.  TRAIN_STEPS, when set,
# overrides it for every run.
#
# The floor is there because the passes alone starve a small corpus: its planner is
# still learning fast when they run out.  The checkpoints are kept, so a run that goes
# on too long can be heard back to an earlier step with Checkpoints.
# A take whose average level is below this is flagged as probably spoiled. Across the
# library the median is about -18 dB; the three renders heard as badly distorted
# came out at -28 to -34, all of them covers through a corpus LoRA.
WEAK_RENDER_DB = float(os.environ.get("WEAK_RENDER_DB", "-24"))

TRAIN_PASSES = float(os.environ.get("TRAIN_PASSES", "10"))
TRAIN_STEPS = int(os.environ["TRAIN_STEPS"]) if os.environ.get("TRAIN_STEPS") else None
TRAIN_BATCH_SONGS = int(os.environ.get("TRAIN_BATCH_SONGS", "2"))
TRAIN_ARTIST_FRACTION = float(os.environ.get("TRAIN_ARTIST_FRACTION", "0.5"))
# Spread across the planner steps; the trainer says it converges in about 1000.
TRAIN_DECODER_STEPS = int(os.environ.get("TRAIN_DECODER_STEPS", "1000"))
# How often the score is put in front of the music.  None of the published files
# did; the planner still learns to write a score either way.
TRAIN_SCORE_FIRST = float(os.environ.get("TRAIN_SCORE_FIRST", "0"))
TRAIN_CHECKPOINT_EVERY = int(os.environ.get("TRAIN_CHECKPOINT_EVERY", "50"))
TRAIN_MIN_STEPS = int(os.environ.get("TRAIN_MIN_STEPS", "500"))


def train_steps(songs: int) -> int:
    """Planner steps for a corpus of this many songs."""
    if TRAIN_STEPS:
        return TRAIN_STEPS
    raw = TRAIN_PASSES * max(1, songs) / (TRAIN_BATCH_SONGS * TRAIN_ARTIST_FRACTION)
    every = TRAIN_CHECKPOINT_EVERY
    return max(TRAIN_MIN_STEPS, 2 * every, int(-(-raw // every)) * every)


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

