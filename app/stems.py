"""Stem separation with demucs, on CPU, inside the app container.

htdemucs runs at roughly 1.3 seconds of audio per second of wall clock on four
CPU threads, so a four-minute song takes about three minutes.  That is why stems
do not use the GPU: they would be faster there, but they would fight YuE2 for VRAM.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

# Model -> the stems it produces, and how many models it runs one after another.
# htdemucs_ft is a bag of four fine-tuned models, and each draws its own progress
# bar.  htdemucs_6s adds guitar and piano, which are noticeably weaker.
MODELS: dict[str, dict] = {
    "htdemucs": {"label": "Fast, four stems", "stems": ["vocals", "drums", "bass", "other"], "passes": 1},
    "htdemucs_ft": {"label": "Fine tuned, four stems, slower", "stems": ["vocals", "drums", "bass", "other"], "passes": 4},
    "htdemucs_6s": {"label": "Six stems (adds guitar and piano)", "stems": ["vocals", "drums", "bass", "other", "guitar", "piano"], "passes": 1},
}

FORMATS = ["wav", "flac", "mp3"]

# demucs encodes these itself.  MP3 is the only lossy choice, so it is pinned to
# 320 kbps rather than left to the encoder's default.
FORMAT_FLAGS = {
    "wav": [],
    "flac": ["--flac"],
    "mp3": ["--mp3", "--mp3-bitrate", "320"],
}

# Half the machine by default, so separation never starves the rest of it. This is
# the ceiling on torch's own threads, and it does real work: measured on a 3:45
# recording, the default already averages 6.5 cores.
DEFAULT_THREADS = int(os.environ.get("STEMS_THREADS") or max(1, (os.cpu_count() or 2) // 2))

# demucs applies its 8 second segments one at a time unless it is given -j, which
# defaults to 0. Measured on this machine, htdemucs, a 3:45 recording, nothing else
# running:
#
#   -j 0   89.2 s   2.52x realtime   6.5 cores   1.8 GB peak
#   -j 4   62.6 s   3.59x realtime  11.6 cores   3.7 GB peak
#   -j 8   63.0 s   3.57x realtime  12.6 cores   5.4 GB peak
#
# Four is the knee: it is 1.4x faster than none, and eight buys nothing for half as
# much memory again. The default scales with the machine, so a four core box asks
# for one worker rather than four: -j makes threads, not processes, so more workers
# than cores only timeshares, and each one still costs its own memory.
#
# Measured with four workers, torch threads made no difference above four:
#
#   8 threads   64.2 s      4 threads   63.4 s      2 threads   71.8 s
#
# so STEMS_THREADS stays at half the CPUs and the two do not need to be balanced.
DEFAULT_JOBS = int(os.environ.get("STEMS_JOBS") or min(4, max(1, (os.cpu_count() or 2) // 4)))

PROGRESS_RE = re.compile(rb"(\d{1,3})%\|")


def _env() -> dict:
    env = dict(os.environ)
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = str(DEFAULT_THREADS)
    env["TORCH_HOME"] = env.get("TORCH_HOME", "/data/models/torch")
    return env


class Progress:
    """Turns the percentages demucs prints into one rising figure.  A bag of models
    draws a bar per model; after the last model, demucs draws more bars while it
    writes each stem.  A bar that starts again means the next model, or, after the
    last one, the writing.  Separation maps onto 5-95 per cent, and writing is 96."""

    def __init__(self, passes: int) -> None:
        self.passes = max(1, passes)
        self.pass_index = 0
        self.last = -1
        self.writing = False

    def feed(self, pct: int) -> tuple[float, str] | None:
        if pct == self.last:
            return None
        if pct < self.last:
            if self.pass_index < self.passes - 1:
                self.pass_index += 1
            elif not self.writing:
                self.writing = True
                self.last = pct
                return 0.96, "Writing the stems"
        self.last = pct
        if self.writing:
            return None   # one bar per stem; nothing worth reporting
        done = (self.pass_index + pct / 100.0) / self.passes
        # The percentage belongs to the caller, which already has one from the
        # figure returned here.  A label that carries its own is shown twice.
        label = "Separating" if self.passes == 1 else f"Separating (model {self.pass_index + 1} of {self.passes})"
        return round(0.05 + 0.90 * max(0.0, min(1.0, done)), 4), label


async def separate(
    src: Path,
    dest_dir: Path,
    model: str,
    wanted: list[str],
    fmt: str,
    on_progress: Callable[[float, str], None] | None = None,
    work_root: Path | None = None,
) -> dict:
    """Run demucs and keep only the requested stems.  Cancelling the task kills
    demucs.  work_root should share a filesystem with dest_dir, so the finished
    stems are moved into place with a rename."""
    if model not in MODELS:
        raise ValueError(f"unknown model {model!r}")
    available = MODELS[model]["stems"]
    passes = MODELS[model]["passes"]
    keep = [s for s in wanted if s in available] or available
    fmt = fmt if fmt in FORMATS else "wav"

    if work_root:
        work_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="stems-", dir=work_root))
    started = time.time()

    def report(frac: float, stage: str) -> None:
        if on_progress:
            on_progress(max(0.0, min(1.0, frac)), stage)

    proc = None
    try:
        report(0.02, "Loading the model")
        cmd = ["demucs", "-n", model, "-o", str(work), "--filename", "{stem}.{ext}", *FORMAT_FLAGS[fmt]]
        if DEFAULT_JOBS > 0:
            cmd += ["-j", str(DEFAULT_JOBS)]
        cmd.append(str(src))
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=_env()
        )
        assert proc.stdout is not None
        # demucs draws its progress bar with carriage returns and no newlines, so
        # read raw chunks and scan for percentages rather than iterating lines.
        parser = Progress(passes)
        recent = b""
        while True:
            chunk = await proc.stdout.read(1024)
            if not chunk:
                break
            recent = (recent + chunk)[-4096:]
            for match in PROGRESS_RE.finditer(chunk):
                step = parser.feed(int(match.group(1)))
                if step:
                    report(*step)
        tail = recent.decode("utf-8", "replace").replace("\r", "\n").splitlines()[-10:]
        code = await proc.wait()
        if code != 0:
            raise RuntimeError("demucs failed: " + " / ".join(tail[-4:]))

        # demucs writes <work>/<model>/<track name>/<stem>.<ext>
        produced = {path.stem: path for path in work.rglob(f"*.{fmt}") if path.stem in available}
        if not produced:
            raise RuntimeError("demucs produced no stems: " + " / ".join(tail[-4:]))

        report(0.98, "Collecting the stems")
        dest_dir.mkdir(parents=True, exist_ok=True)
        out: dict[str, str] = {}
        for name in keep:
            source = produced.get(name)
            if source:
                target = dest_dir / f"{name}.{fmt}"
                shutil.move(str(source), str(target))
                out[name] = str(target)
        report(1.0, "Done")
        return {"stems": out, "model": model, "format": fmt, "seconds": round(time.time() - started, 1)}
    except asyncio.CancelledError:
        if proc and proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


def installed() -> bool:
    return shutil.which("demucs") is not None


# ---------------------------------------------------------------- quick look
# Demucs held in memory, for checks that must answer in seconds rather than the
# ten or so a fresh process spends loading the model. The stems feature still
# runs the command line tool: it separates whole songs, writes files, reports
# progress and can be cancelled, none of which this needs.
_warm: dict = {}


def warm():
    """Load the separator now, so a later check does not wait for it.  Safe to
    call more than once and from a thread."""
    try:
        _warm_model()
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("yue2.stems").warning("could not load the separator early: %s", exc)


def _warm_model():
    from demucs.pretrained import get_model

    if "model" not in _warm:
        model = get_model("htdemucs")
        model.eval()
        _warm["model"] = model
    return _warm["model"]


def vocal_of(src: Path) -> tuple["object", int]:
    """The vocal of a short piece of audio, separated in this process.

    Returns the samples and their rate. Held-in-memory Demucs answers in a few
    seconds where a new process takes half a minute, which is the difference
    between telling someone now and telling them after they have moved on."""
    import numpy as np
    import torch
    from demucs.apply import apply_model

    model = _warm_model()
    rate = model.samplerate
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(src), "-ac", "2", "-ar", str(rate), "-f", "f32le", "-"],
        capture_output=True, check=True, timeout=120).stdout
    wav = torch.from_numpy(np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).T.copy())
    with torch.no_grad():
        out = apply_model(model, wav[None], device="cpu", progress=False)[0]
    return out[model.sources.index("vocals")].mean(0).numpy(), rate
