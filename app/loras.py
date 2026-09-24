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
import zipfile
from pathlib import Path

from . import config

log = logging.getLogger("yue2.loras")

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
    rest, trigger, styles, strengths = [], None, [], None
    for line in lines[1:]:
        # A trigger word has to be typed into the style, or the LoRA barely
        # shows, so it is pulled out of the prose and shown on its own.
        if line.lower().startswith("trigger:"):
            trigger = line.split(":", 1)[1].strip()
            continue
        style = parse_style(line)
        if style:
            styles.append(style)
            continue
        found = parse_strengths(line)
        if found:
            strengths = found
            continue
        rest.append(line)
    body = "\n".join(rest).strip()
    return {k: v for k, v in (("title", title), ("note", body), ("trigger", trigger), ("styles", styles),
                              ("strengths", strengths)) if v}


# The strengths a LoRA starts at when it is chosen, kept in its note so they travel with
# it when it is shared:  Strengths: Planner 0.80, Sound 0.60
STRENGTHS = re.compile(r"^strengths:\s*planner\s+([\d.]+)\s*,\s*sound\s+([\d.]+)\s*$", re.I)


def parse_strengths(line: str) -> dict | None:
    match = STRENGTHS.match(line.strip())
    if not match:
        return None
    try:
        return {"planner": float(match.group(1)), "sound": float(match.group(2))}
    except ValueError:
        return None


def set_strengths(path: Path, planner: float | None, sound: float | None) -> None:
    """Write, replace or (with both None) remove the Strengths line in a LoRA's note,
    just under its trigger word.  A LoRA with no note gets one named after its file."""
    sidecar = path.with_suffix(".txt")
    try:
        lines = sidecar.read_text(encoding="utf-8").rstrip("\n").split("\n") if sidecar.is_file() else [path.stem]
    except (OSError, UnicodeDecodeError):
        lines = [path.stem]
    lines = [line for line in lines if not parse_strengths(line)]
    if planner is not None and sound is not None:
        at = next((i + 1 for i, line in enumerate(lines) if line.lower().startswith("trigger:")), 1)
        lines.insert(at, f"Strengths: Planner {planner:.2f}, Sound {sound:.2f}")
    sidecar.write_text("\n".join(lines) + "\n", encoding="utf-8")


# A learned style travels in the note as one line, so a LoRA shared as its file and
# note still offers its chips:  Style: Jet | pop, synth, male vocal, key of A major | 136
STYLE_PREFIX = "style:"


def parse_style(line: str) -> dict | None:
    if not line.lower().startswith(STYLE_PREFIX):
        return None
    parts = [part.strip() for part in line.split(":", 1)[1].split("|")]
    if len(parts) < 2 or not parts[1]:
        return None
    tempo = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    return {"title": parts[0], "prompt": parts[1], "hint": parts[1], "tempo": tempo, "key": None}


def style_line(style: dict) -> str:
    clean = lambda text: str(text or "").replace("|", "/").replace("\n", " ").strip()
    tempo = f" | {style['tempo']}" if style.get("tempo") else ""
    return f"Style: {clean(style.get('title'))} | {clean(style.get('prompt'))}{tempo}"


def note_with_styles(path: Path, styles: list[dict]) -> str:
    """The note beside a LoRA, with its learned styles written in, replacing any it
    already carries.  A LoRA with no note gets one named after its file."""
    sidecar = path.with_suffix(".txt")
    try:
        lines = sidecar.read_text(encoding="utf-8").rstrip().split("\n") if sidecar.is_file() else [path.stem]
    except (OSError, UnicodeDecodeError):
        lines = [path.stem]
    lines = [line for line in lines if not parse_style(line)]
    while lines and not lines[-1].strip():
        lines.pop()
    if styles:
        lines += [""] + [style_line(style) for style in styles]
    return "\n".join(lines) + "\n"


def bundle(path: Path, styles: list[dict], dest: Path) -> Path:
    """One file to hand to someone else: the LoRA and its note, styles included.
    Stored rather than compressed, since a safetensors file does not compress."""
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.write(path, path.name)
        archive.writestr(path.with_suffix(".txt").name, note_with_styles(path, styles))
    return dest


def remove(name: str, root: Path | None = None) -> list[str]:
    """Delete a LoRA and what belongs to it alone: its note, its training log, and
    its line in families.txt.  A line naming a whole set by its prefix is left, since
    other files share it."""
    root = root or folder()
    if not root:
        raise ValueError("the app cannot see the engine's model folder")
    path = root / name
    stem = path.stem
    gone = []
    for item in (path, root / f"{stem}.txt", root / f"{stem}_log.json"):
        if item.is_file():
            item.unlink()
            gone.append(item.name)
    listing = root / "families.txt"
    if listing.is_file():
        lines = listing.read_text(encoding="utf-8").split("\n")
        kept = [line for line in lines
                if line.strip().startswith("#") or line.partition("=")[0].strip().lower() != stem.lower()]
        if len(kept) != len(lines):
            text = "\n".join(kept)
            while "\n\n\n" in text:
                text = text.replace("\n\n\n", "\n\n")
            listing.write_text(text, encoding="utf-8")
            gone.append("its line in families.txt")
    log.info("removed LoRA %s: %s", name, ", ".join(gone))
    return gone


# The group a LoRA installed from someone else's bundle goes in.
INSTALLED_FAMILY = "Installed"


def install_shared(source: Path, filename: str, root: Path | None = None) -> dict:
    """Put a LoRA someone shared where the engine looks: a bundle from Download (the
    file and its note), or a bare safetensors file.  The note is kept as it came, so
    the LoRA arrives with its name, trigger word and chips."""
    root = root or folder()
    if not root:
        raise ValueError("the app cannot see the engine's model folder")
    note = None
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            weights = [m for m in members if m.filename.lower().endswith(".safetensors")]
            if len(weights) != 1:
                raise ValueError("that zip should hold one .safetensors file")
            stem = Path(weights[0].filename).stem
            texts = [m for m in members if Path(m.filename).name.lower() == f"{stem.lower()}.txt"]
            staged = source.with_name(source.name + ".lora")
            with archive.open(weights[0]) as src, staged.open("wb") as out:
                shutil.copyfileobj(src, out)
            if texts:
                note = archive.read(texts[0]).decode("utf-8", errors="replace")
        weights_path = staged
    else:
        stem = Path(filename or "lora").stem
        weights_path = source
    try:
        names = names_in(weights_path)          # raises if it is not a safetensors file
        if not names:
            raise ValueError("that file holds no tensors")
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._") or "lora"
        target = root / f"{stem}.safetensors"
        if target.exists():
            raise ValueError(f"{target.name} is already in the LoRA folder")
        shutil.copyfile(weights_path, target)
    finally:
        if weights_path != source:
            weights_path.unlink(missing_ok=True)
    (root / f"{stem}.txt").write_text(note if note is not None else stem + "\n", encoding="utf-8")
    if stem.lower() not in families(root):
        with (root / "families.txt").open("a", encoding="utf-8") as handle:
            handle.write(f"\n{stem.lower()} = {INSTALLED_FAMILY}\n")
    log.info("installed shared LoRA %s (%s)", target.name, kind_of(names))
    return {"name": target.name, "kind": kind_of(names), "styles": len(note_for(target).get("styles", []))}


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
    target = root / f"{stem}.safetensors"
    if target.exists():
        raise ValueError(f"{target.name} is already in the LoRA folder")

    shutil.copyfile(source, target)
    kind = kind_of(names)
    write_note(target, trigger, corpus, title=name)
    log.info("installed %s (%s)", target.name, kind)
    return {"name": target.name, "kind": kind, "trigger": trigger.lower(), "tensors": len(names)}


# The group every LoRA made from one of your corpora shares.  Its own note names it,
# so a group per corpus would only repeat that name above it.
CORPUS_FAMILY = "Your corpora"


def write_note(path: Path, trigger: str, corpus: str, title: str = "", root: Path | None = None) -> Path:
    """The text file the picker reads: what the file is called, its trigger word, and
    where it came from.  Used for a LoRA installed by hand and for one trained here."""
    root = root or path.parent
    stem = path.stem
    note = [title or stem]
    if trigger:
        note.append(f"Trigger: {trigger.lower()}")
    note.append("")
    note.append(f"Trained from the corpus {corpus} on {time.strftime('%Y-%m-%d')}.")
    # Which halves the file holds is what the picker says, with the strength each one
    # needs, so the note does not repeat it.
    note_path = root / f"{stem}.txt"
    note_path.write_text("\n".join(note) + "\n", encoding="utf-8")

    # Grouped by the whole file name, not the word in front of it: that word is a
    # first name here, and paul_mccartney would take in paul_shields.
    if stem.lower() not in families(root):
        path_families = root / "families.txt"
        header = "" if path_families.exists() else "# The picker groups LoRAs by the word in front of the file name.\n"
        with path_families.open("a", encoding="utf-8") as handle:
            handle.write(header + f"\n{stem.lower()} = {CORPUS_FAMILY}\n")
    return note_path


def families(root: Path | None) -> dict[str, str]:
    """Readable names for the groups the picker makes, from `families.txt`.

    Authors name a set with a code — chnsn, mltnt — and the picker groups on it
    because that is what the file names carry. `chnsn = Chanson francaise` in
    that file turns the heading into something a person can read."""
    if not root:
        return {}
    path = root / "families.txt"
    out = {}
    try:
        if not path.is_file():
            return {}
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
    try:
        if not path.is_file():
            return entry
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
        stem = name.replace(".safetensors", "").lower()
        family = stem.split("-")[0].split("_")[0]
        if stem in named or family in named:
            entry["family"] = named.get(stem) or named[family]
        entries.append(entry)
    return entries


def usable(entry: dict) -> bool:
    """A style LoRA has to hold a half this app knows how to chain, and must not
    be one the app already applies for another reason."""
    return not entry["reserved"] and entry["kind"] in ("planner", "decoder", "both", "unknown")
