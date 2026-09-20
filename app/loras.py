"""What is in a LoRA file, so the app can say what a LoRA will do.

A YuE2 LoRA holds one half of the model, or both.  The planner half sits under
`text_encoders.` and decides what is written: form, harmony, phrasing.  The
decoder half sits under `diffusion_model.` and decides how it sounds: timbre,
production.  ComfyUI's LoraLoader applies them through two separate strengths,
and a strength for a half the file does not contain does nothing at all.

The app's own two LoRAs are one half each, which is why each is applied with the
other strength at zero.  A style LoRA from elsewhere is usually both, and wants
both strengths, so the picker has to know which it is holding.

Reading that costs almost nothing: a safetensors file starts with the length of
its header, then the header itself as JSON, and the tensor names are in there.
"""
from __future__ import annotations

import json
import logging
import struct
from pathlib import Path

from . import config

log = logging.getLogger("yue2studio.loras")

PLANNER = "text_encoders"
DECODER = "diffusion_model"

# The two the app applies itself.  They are listed by the engine like any other,
# but choosing one as a style LoRA would fight the setting that already applies it.
RESERVED = {config.INSTRUMENTAL_LORA, config.REAL_AUDIO_LORA}

# A header longer than this is not a LoRA we can make sense of, and reading it
# would be a way to spend memory on a malformed file.
MAX_HEADER = 32 * 1024 * 1024


def names_in(path: Path) -> list[str]:
    """The tensor names in a safetensors file, read without loading a tensor."""
    with path.open("rb") as handle:
        raw = handle.read(8)
        if len(raw) < 8:
            raise ValueError("too short to be a safetensors file")
        length = struct.unpack("<Q", raw)[0]
        if not 0 < length <= MAX_HEADER:
            raise ValueError("header length out of range")
        header = json.loads(handle.read(length).decode("utf-8"))
    return [key for key in header if key != "__metadata__"]


def kind_of(names: list[str]) -> str:
    """planner, decoder, both, or other for a file this engine cannot chain."""
    planner = any(name.startswith(PLANNER + ".") for name in names)
    decoder = any(name.startswith(DECODER + ".") for name in names)
    if planner and decoder:
        return "both"
    if planner:
        return "planner"
    if decoder:
        return "decoder"
    return "other"


def folder() -> Path | None:
    """Where the LoRA files are, when this machine can see them.  With the app
    and the engine on different machines it cannot, and the catalogue then says
    only what the engine reported."""
    path = Path(config.MODELS_DIR) / "loras"
    return path if path.is_dir() else None


def describe(name: str, root: Path | None) -> dict:
    """One entry for the picker: what the file is, and whether it can be read."""
    entry = {"name": name, "kind": "unknown", "reserved": name in RESERVED}
    if not root:
        return entry
    path = root / name
    if not path.is_file():
        return entry
    try:
        entry["kind"] = kind_of(names_in(path))
    except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as err:
        # A file the engine lists but this side cannot parse is still offered:
        # the engine is the one that has to load it.
        log.warning("could not read %s: %s", name, err)
    return entry


def catalogue(listed: list[str]) -> list[dict]:
    """Everything the engine can load, with what each one holds.  The engine's
    list is the authority on what exists; the files only add detail."""
    root = folder()
    return [describe(name, root) for name in listed]


def usable(entry: dict) -> bool:
    """A style LoRA has to hold a half this app knows how to chain, and must not
    be one the app already applies for another reason."""
    return not entry["reserved"] and entry["kind"] in ("planner", "decoder", "both", "unknown")
