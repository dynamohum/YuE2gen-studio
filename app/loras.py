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
import re
import shutil
import struct
import time
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


def note_for(path: Path) -> dict:
    """A LoRA's own notes, from a text file beside it.

    A file name is not a description. `mltnt_roots.safetensors` says nothing
    about what it does, and the people who publish these write a paragraph that
    is left behind on a web page. So a `.txt` of the same name is read if it is
    there: the first line names it, the rest describes it.

    Nothing has to have one, and anything can: a LoRA of your own gets a note by
    writing one beside it."""
    sidecar = path.with_suffix(".txt")
    if not sidecar.is_file():
        return {}
    try:
        lines = sidecar.read_text(encoding="utf-8").strip().split("\n")
    except (OSError, UnicodeDecodeError) as err:
        log.warning("could not read %s: %s", sidecar.name, err)
        return {}
    title = lines[0].strip()
    rest, trigger = [], None
    for line in lines[1:]:
        # A trigger word has to be typed into the style, or the LoRA barely
        # shows, so it is pulled out of the prose and shown on its own.
        if line.lower().startswith("trigger:"):
            trigger = line.split(":", 1)[1].strip()
            continue
        rest.append(line)
    body = "\n".join(rest).strip()
    return {k: v for k, v in (("title", title), ("note", body), ("trigger", trigger)) if v}


def install(source: Path, name: str, trigger: str, corpus: str, root: Path | None = None) -> dict:
    """Put a trained LoRA where the engine looks, with a note beside it.

    The app cannot train, so the file arrives from a trainer elsewhere.  It goes into
    the LoRA folder with a .txt naming it and giving its trigger word — the same note
    the downloaded ones carry — and the family file gains a line, so the picker groups
    it under the corpus it came from instead of leaving it under Other."""
    root = root or folder()
    if not root:
        raise ValueError("the app cannot see the engine's model folder")
    names = names_in(source)             # raises if it is not a safetensors file
    if not names:
        raise ValueError("that file holds no tensors")

    stem = re.sub(r"[^a-z0-9]+", "_", (name or source.stem).lower()).strip("_") or "lora"
    if not stem.endswith("_lora"):
        stem += "_lora"                  # the picker reads the word in front as the group
    target = root / f"{stem}.safetensors"
    if target.exists():
        raise ValueError(f"{target.name} is already in the LoRA folder")

    shutil.copyfile(source, target)
    kind = kind_of(names)
    held = {"both": "score and sound", "planner": "score only",
            "decoder": "sound only"}.get(kind, "an unrecognised layout")
    note = [name or stem]
    if trigger:
        note.append(f"Trigger: {trigger.lower()}")
    note.append("")
    note.append(f"Trained from the corpus {corpus} on {time.strftime('%Y-%m-%d')}.")
    note.append(f"Holds {held}.")
    (root / f"{stem}.txt").write_text("\n".join(note) + "\n", encoding="utf-8")

    prefix = stem.split("_")[0]
    if prefix not in families(root):
        path = root / "families.txt"
        header = "" if path.exists() else "# The picker groups LoRAs by the word in front of the file name.\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(header + f"\n{prefix} = {corpus}\n")

    log.info("installed %s (%s)", target.name, kind)
    return {"name": target.name, "kind": kind, "trigger": trigger.lower(), "tensors": len(names)}


def families(root: Path | None) -> dict[str, str]:
    """Readable names for the groups the picker makes, from `families.txt`.

    Authors name a set with a code — chnsn, mltnt — and the picker groups on it
    because that is what the file names carry. `chnsn = Chanson francaise` in
    that file turns the heading into something a person can read."""
    if not root:
        return {}
    path = root / "families.txt"
    if not path.is_file():
        return {}
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").split("\n"):
            if "=" in line and not line.strip().startswith("#"):
                key, _, label = line.partition("=")
                out[key.strip().lower()] = label.strip()
    except (OSError, UnicodeDecodeError) as err:
        log.warning("could not read families.txt: %s", err)
    return out


def describe(name: str, root: Path | None) -> dict:
    """One entry for the picker: what the file is, what it is for, and whether
    it can be read at all."""
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
    entry.update(note_for(path))
    return entry


def catalogue(listed: list[str]) -> list[dict]:
    """Everything the engine can load, with what each one holds.  The engine's
    list is the authority on what exists; the files only add detail."""
    root = folder()
    named = families(root)
    entries = []
    for name in listed:
        entry = describe(name, root)
        family = name.replace(".safetensors", "").split("-")[0].split("_")[0].lower()
        if family in named:
            entry["family"] = named[family]
        entries.append(entry)
    return entries


def usable(entry: dict) -> bool:
    """A style LoRA has to hold a half this app knows how to chain, and must not
    be one the app already applies for another reason."""
    return not entry["reserved"] and entry["kind"] in ("planner", "decoder", "both", "unknown")
