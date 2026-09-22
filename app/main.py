"""YuE2 Studio: a browser front end for YuE2 running in ComfyUI.

The heavy lifting happens in the engine.  This service keeps the library, drives
the engine, separates stems, and serves one page.

  config.py   environment settings
  db.py       SQLite: connections, schema, migrations, settings
  library.py  files in the data folder: names, sidecars, durations, peaks
  engine.py   the ComfyUI client
  jobs.py     the GPU and stem job lanes
  main.py     this file: the HTTP API
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from . import config, identities, instrumental, jobs, loras, lyrics, score, stems
from .db import DEFAULT_SPACE, execute, get_setting, migrate, one, rows, set_setting

personas = identities
from .engine import stage_label
from .jobs import (CURRENT, CURRENT_STEMS, ENGINE, HARMONY_STEPS, INTERPRETATION_NAMES, INTERPRETATIONS, LYRICS,
                   PLAN_VARIETY, QUEUE, STEM_QUEUE)
from .library import (audio_duration, ensure_peaks, inside, relayout, remove_tree, slugify,
                      source_path, take_folder)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("yue2")
# The keeper polls the engine every two seconds; one log line per request is noise.
logging.getLogger("httpx").setLevel(logging.WARNING)

STATIC_DIR = Path(__file__).parent / "static"
ACTIVE = ("queued", "running")
MAX_SEED = 2**64 - 1


# --------------------------------------------------------------------- settings
# Everything the Settings panel can change.  The panel renders this spec, so a
# new setting is a server-side change only.
SETTINGS_SPEC: list[dict] = [
    {
        "key": "stems.format",
        "label": "Stem audio format",
        "type": "select",
        "default": "wav",
        "options": [
            {"value": "wav", "label": "WAV, uncompressed"},
            {"value": "flac", "label": "FLAC, lossless"},
            {"value": "mp3", "label": "MP3, 320 kbps"},
        ],
        "help": "The format for new stems.",
    },
    {
        "key": "stems.model",
        "label": "Stem separation model",
        "type": "select",
        "default": "htdemucs",
        "options": [{"value": key, "label": spec["label"]} for key, spec in stems.MODELS.items()],
        "help": "The model new runs start with.",
    },
    {
        "key": "instrumental.vocal_check",
        "label": "Vocal check on instrumentals",
        "type": "select",
        "default": "fast",
        "options": [
            {"value": "fast", "label": "Quick, holds about 800 MB"},
            {"value": "thrifty", "label": "Thrifty, slower, holds nothing"},
            {"value": "off", "label": "Off"},
        ],
        "help": "Checks a finished instrumental for singing.",
    },
    {
        "key": "stems.folder",
        "label": "Stem save folder",
        "type": "text",
        "default": str(config.STEMS_DIR),
        "help": f"Where stems are written. It must sit inside {config.DATA_DIR}.",
    },
]

SETTINGS_BY_KEY = {item["key"]: item for item in SETTINGS_SPEC}


def setting_value(key: str) -> str:
    return get_setting(key, None) or SETTINGS_BY_KEY[key]["default"]


def settings_payload() -> list[dict]:
    return [{**spec, "value": setting_value(spec["key"])} for spec in SETTINGS_SPEC]


def save_setting(key: str, value: str) -> None:
    spec = SETTINGS_BY_KEY.get(key)
    if not spec:
        raise HTTPException(400, f"unknown setting {key}")
    value = (value or "").strip()
    if spec["type"] == "select":
        allowed = [option["value"] for option in spec["options"]]
        if value not in allowed:
            raise HTTPException(400, f"{key} must be one of {', '.join(allowed)}")
    if key == "stems.folder":
        if not value:
            raise HTTPException(400, "the stem folder cannot be empty")
        if not inside(Path(value), config.DATA_DIR):
            raise HTTPException(400, f"the stem folder must be inside {config.DATA_DIR}")
    set_setting(key, value)


def guess_title(lyrics: str) -> str:
    """First real lyric line. Section and genre tags do not make a title."""
    for line in (lyrics or "").splitlines():
        text = line.strip()
        if not text or text[0] in "[#({":
            continue
        return text[:60]
    return ""


def remove_folders(folders: list[tuple[Path | None, Path]]) -> None:
    """Delete each folder that sits strictly inside its root.  The check stops a bad
    path in the database from ever taking the library with it."""
    for folder, root in folders:
        if folder and inside(folder, root) and folder.resolve() != root.resolve():
            remove_tree(folder)


# --------------------------------------------------------------------- lifecycle
@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate()
    remove_tree(config.WORK_DIR)
    config.WORK_DIR.mkdir(parents=True, exist_ok=True)
    # Songs to build a corpus from go here, so nobody has to mount a folder or know
    # a path: copy the files in, and the corpus screen offers them.
    await asyncio.to_thread(config.CORPUS_INBOX.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(sweep_engine_input)
    # A job that was running when the app stopped cannot be picked up again.  One
    # that was only waiting can, so it goes back in the queue.
    execute("UPDATE takes SET status = 'failed', error = 'interrupted by a restart' WHERE status = 'running'")
    execute("UPDATE sources SET transcribe_state = 'failed', transcribe_error = 'interrupted by a restart' WHERE transcribe_state = 'running'")
    execute("UPDATE stem_sets SET status = 'failed', error = 'interrupted by a restart' WHERE status = 'running'")
    await requeue_waiting()
    await asyncio.to_thread(relayout)
    await asyncio.to_thread(fill_source_durations)
    if config.ENGINE_OUTPUT_DIR:
        # Renders are saved here.  Created by the app, so the app may delete the
        # engine's copy once it has its own, though the engine writes as root.
        try:
            (config.ENGINE_OUTPUT_DIR / "yue2studio").mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("engine output folder not usable, renders stay in the engine: %s", exc)
    await ENGINE.start()
    # Identity analysis is not queued again after a restart: its states go back to
    # none, and Analyse picks up whatever is left.
    execute("""UPDATE identity_songs SET vocals_state = 'none' WHERE vocals_state IN ('queued', 'running')""")
    for field in ("score_state", "lyrics_state", "style_state"):
        execute(f"UPDATE identity_songs SET {field} = 'none' WHERE {field} IN ('queued', 'running')")
    tasks = [asyncio.create_task(jobs.worker()), asyncio.create_task(jobs.stems_worker()), asyncio.create_task(jobs.keeper()),
             asyncio.create_task(jobs.identity_worker())]
    log.info("YuE2 Studio %s up. engine=%s (%s) data=%s", config.VERSION, config.ENGINE_URL,
             "online" if ENGINE.online else "offline", config.DATA_DIR)
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await ENGINE.close()


async def requeue_waiting() -> None:
    """Put jobs that were waiting at shutdown back in their queues, oldest first."""
    waiting = [(row["created_at"], "take", row) for row in rows("SELECT id, abc, created_at FROM takes WHERE status = 'queued'")]
    waiting += [(row["created_at"], "source", row) for row in rows("SELECT id, created_at FROM sources WHERE transcribe_state = 'queued'")]
    for _, kind, row in sorted(waiting, key=lambda item: item[0]):
        if kind == "source":
            await QUEUE.put({"kind": "transcribe", "id": row["id"]})
        else:
            await QUEUE.put({"kind": "render" if (row["abc"] or "").strip() else "plan", "id": row["id"]})
    for row in rows("SELECT id FROM stem_sets WHERE status = 'queued' ORDER BY created_at"):
        await STEM_QUEUE.put({"id": row["id"]})
    for row in rows("SELECT id FROM sources WHERE lyrics_state IN ('queued', 'running') ORDER BY created_at"):
        execute("UPDATE sources SET lyrics_state = 'queued' WHERE id = ?", (row["id"],))
        await STEM_QUEUE.put({"kind": "lyrics", "id": row["id"]})
    if waiting:
        log.info("%d waiting jobs queued again after the restart", len(waiting))


app = FastAPI(title="YuE2 Studio", lifespan=lifespan)


def host_allowed(host_header: str) -> bool:
    if "*" in config.ALLOWED_HOSTS:
        return True
    hostname = (urlsplit("//" + host_header).hostname or "").lower()
    return hostname in config.ALLOWED_HOSTS


@app.middleware("http")
async def guard(request: Request, call_next):
    """Refuse unknown Host names (DNS rebinding) and cross-site writes (a page on
    another site posting to this one).  Then set cache headers on the page."""
    if not host_allowed(request.headers.get("host", "")):
        return PlainTextResponse("This host name is not allowed. Add it to ALLOWED_HOSTS.", status_code=421)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin is not None and urlsplit(origin).netloc.lower() != request.headers.get("host", "").lower():
            return PlainTextResponse("Cross-site request refused.", status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return PlainTextResponse("Cross-site request refused.", status_code=403)
    if request.method == "POST" and request.url.path == "/api/sources":
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > config.MAX_UPLOAD_MB * 1024 * 1024 + 65536:
            return PlainTextResponse(f"That file is larger than {config.MAX_UPLOAD_MB} MB.", status_code=413)
    response = await call_next(request)
    # Revalidate the page and its assets on every load, so a new app.js is never
    # hidden behind a stale copy, but an unchanged file costs a 304, not a download.
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.middleware("http")
async def revalidate_static(request, call_next):
    """Let the browser cache the page's scripts and stylesheets, but check them
    every time.  They are asked for as app.js?v=<VERSION>, and the version moves
    only for a feature release, so without this a deploy could leave a browser on
    the old files.  StaticFiles sends an ETag and a Last-Modified, so an unchanged
    file costs a 304 rather than a download."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ------------------------------------------------------------------- api models
class ScoreIn(BaseModel):
    abc: str = Field(max_length=200_000)


class SongIn(BaseModel):
    title: str | None = Field(None, max_length=200)
    style: str = Field(config.DEFAULT_STYLE, max_length=2000)
    lyrics: str = Field("", max_length=20_000)
    seed: int | None = Field(None, ge=0, le=MAX_SEED)
    max_duration: float = Field(360.0, ge=10, le=900)
    auto_render: bool = False
    interpretation: str = "standard"
    variety: str = "normal"
    harmony: int = Field(0, ge=0, le=len(HARMONY_STEPS) - 1)
    space_id: str = Field(DEFAULT_SPACE, max_length=64)
    realaudio: bool = True
    identity_id: str | None = Field(None, max_length=64)
    persona_id: str | None = Field(None, max_length=64)
    voice_lora: str | None = Field(None, max_length=200)
    voice_lora_strength: float = 1.0
    voice_lora_clip: float = Field(0.0, ge=0.0, le=3.0)
    style_lora: str | None = Field(None, max_length=200)
    style_lora_model: float = Field(1.0, ge=0.0, le=3.0)
    style_lora_clip: float = Field(1.0, ge=0.0, le=3.0)


def _style_lora_of(body) -> dict:
    """The style LoRA a create request asked for.  Both strengths are kept even
    when the name is empty, so an interrupted choice does not leave a take
    claiming a strength it never used."""
    name = (getattr(body, "style_lora", None) or "").strip() or None
    return {
        "style_lora": name,
        "style_lora_model": float(getattr(body, "style_lora_model", 1.0) or 0.0) if name else 1.0,
        "style_lora_clip": float(getattr(body, "style_lora_clip", 1.0) or 0.0) if name else 1.0,
    }


class ReplanIn(BaseModel):
    # Both optional: an omitted field keeps what the take already has.
    variety: str | None = None
    harmony: int | None = Field(None, ge=0, le=len(HARMONY_STEPS) - 1)


class TakeIn(BaseModel):
    source_id: str = Field(max_length=64)
    title: str | None = Field(None, max_length=200)
    style: str = Field(config.DEFAULT_STYLE, max_length=2000)
    lyrics: str = Field("", max_length=20_000)
    abc: str | None = Field(None, max_length=200_000)
    mode: str = "full"
    seed: int | None = Field(None, ge=0, le=MAX_SEED)
    max_duration: float = Field(360.0, ge=10, le=900)
    space_id: str = Field(DEFAULT_SPACE, max_length=64)
    interpretation: str = "standard"
    realaudio: bool = True
    identity_id: str | None = Field(None, max_length=64)
    persona_id: str | None = Field(None, max_length=64)
    voice_lora: str | None = Field(None, max_length=200)
    voice_lora_strength: float = 1.0
    voice_lora_clip: float = Field(0.0, ge=0.0, le=3.0)
    style_lora: str | None = Field(None, max_length=200)
    style_lora_model: float = Field(1.0, ge=0.0, le=3.0)
    style_lora_clip: float = Field(1.0, ge=0.0, le=3.0)


class InstrumentalIn(BaseModel):
    title: str | None = Field(None, max_length=200)
    style: str = Field(config.DEFAULT_STYLE, max_length=2000)
    structure: str = Field(instrumental.BARE, max_length=4000)
    seed: int | None = Field(None, ge=0, le=MAX_SEED)
    max_duration: float = Field(360.0, ge=10, le=900)
    auto_render: bool = False
    variety: str = "normal"
    harmony: int = Field(0, ge=0, le=len(HARMONY_STEPS) - 1)
    space_id: str = Field(DEFAULT_SPACE, max_length=64)
    interpretation: str = "standard"
    feel: str = "steady"
    realaudio: bool = True
    identity_id: str | None = Field(None, max_length=64)
    persona_id: str | None = Field(None, max_length=64)
    voice_lora: str | None = Field(None, max_length=200)
    voice_lora_strength: float = 1.0
    voice_lora_clip: float = Field(0.0, ge=0.0, le=3.0)
    style_lora: str | None = Field(None, max_length=200)
    style_lora_model: float = Field(1.0, ge=0.0, le=3.0)
    style_lora_clip: float = Field(1.0, ge=0.0, le=3.0)


class IdentityIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    trigger_word: str = Field(min_length=2, max_length=40)
    description: str = Field("", max_length=400)
    voice: str = Field("", max_length=20)
    folder: str = Field(min_length=1, max_length=1000)
    consent: bool = False
    lora: str | None = Field(None, max_length=200)


PersonaIn = IdentityIn


class IdentityEdit(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    trigger_word: str | None = Field(None, min_length=2, max_length=40)
    description: str | None = Field(None, max_length=400)
    voice: str | None = Field(None, max_length=20)
    lora: str | None = Field(None, max_length=200)


PersonaEdit = IdentityEdit


class IdentitySongEdit(BaseModel):
    include: bool | None = None
    # This song's sound, when it differs from the identity's. Empty means the identity's.
    description: str | None = Field(None, max_length=400)
    lyrics: str | None = Field(None, max_length=20_000)
    lyrics_checked: bool | None = None


PersonaSongEdit = IdentitySongEdit


class RenderIn(BaseModel):
    # Optional: an omitted interpretation keeps the take's own.
    interpretation: str | None = None
    # A fresh seed for the same score: what to reach for when a take came out
    # wrong in a way the settings do not explain, such as an instrumental that
    # sang. The plan is kept; only the rendering of it changes.
    reseed: bool = False
    realaudio: bool | None = None
    identity_id: str | None = Field(None, max_length=64)
    persona_id: str | None = Field(None, max_length=64)
    voice_lora: str | None = Field(None, max_length=200)
    voice_lora_strength: float | None = None


class VariationsIn(BaseModel):
    interpretations: list[str] = Field(min_length=1, max_length=len(INTERPRETATIONS))
    realaudio: bool | None = None
    identity_id: str | None = Field(None, max_length=64)
    persona_id: str | None = Field(None, max_length=64)
    voice_lora: str | None = Field(None, max_length=200)
    voice_lora_strength: float | None = None


class LyricsIn(BaseModel):
    brief: str = Field(min_length=1, max_length=1000)
    style: str = Field("", max_length=2000)
    structure: str = lyrics.DEFAULT_STRUCTURE
    seed: int | None = Field(None, ge=0, le=2**32 - 1)


class SpaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class MoveIn(BaseModel):
    space_id: str = Field(max_length=64)


class StemsIn(BaseModel):
    # All optional: an omitted field means "use what Settings says", not a hard
    # coded default, which is why these are None rather than "wav" and friends.
    model: str | None = None
    stems: list[str] = []
    format: str | None = None
    save_dir: str | None = Field(None, max_length=1000)


class SettingIn(BaseModel):
    key: str
    value: str = Field(max_length=1000)


# ------------------------------------------------------------------ page, state
_INDEX = (STATIC_DIR / "index.html").read_text(encoding="utf-8").replace("{{VERSION}}", config.VERSION)


_GUIDE = (STATIC_DIR / "guide.html").read_text(encoding="utf-8").replace("{{VERSION}}", config.VERSION)


@app.get("/")
def index() -> HTMLResponse:
    return HTMLResponse(_INDEX)


@app.get("/guide")
def guide() -> HTMLResponse:
    """The user guide, which is markdown on disk and rendered in the browser.

    It is served from a tidy path rather than /static/guide.html because it is a
    page people are sent to, and because the markdown itself stays readable in
    the repository and on GitHub."""
    return HTMLResponse(_GUIDE)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "engine": ENGINE.online, "version": config.VERSION}


def _shorten(text: str, limit: int) -> str:
    """Cut at the last whole word that fits, and say it was cut.  A line that
    stops mid-word reads like something went wrong with the prompt."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] or text[:limit]
    return cut + "\u2026"


def _job_title(kind: str, ref_id: str) -> str | None:
    if kind in jobs.IDENTITY_FIELDS:
        row = one("SELECT title FROM identity_songs WHERE id = ?", (ref_id,))
        label = {"identity_score": "key and tempo", "identity_style": "style",
                 "persona_score": "key and tempo", "persona_style": "style"}.get(kind, "analysis")
        return f"Identity {label}: {row['title']}" if row else None
    if kind == "lyrics":
        record = LYRICS.get(ref_id)
        return ("Lyrics: " + _shorten(record["brief"], 60)) if record else None
    if kind == "transcribe":
        row = one("SELECT title FROM sources WHERE id = ?", (ref_id,))
    else:
        row = one("SELECT title FROM takes WHERE id = ?", (ref_id,))
    return row["title"] if row else None


def queue_view() -> list[dict]:
    """Everything ahead of and behind the GPU: the engine's own queue, running first,
    then the app's jobs that have not been sent yet.  Jobs sent to the engine by
    something else are listed too, without a title, since only their kind is known."""
    now = time.time()
    items = []
    for entry in ENGINE.queue:
        item = {"state": entry["state"], "kind": entry["kind"], "outside": not entry["mine"],
                "client": None if entry["mine"] else (entry["client"] or "unknown"),
                "since": entry["running_since"] if entry["state"] == "running" else entry["queued_at"]}
        if entry["mine"] and CURRENT.get("prompt_id") == entry["prompt_id"]:
            item.update({"id": CURRENT["id"], "kind": CURRENT["kind"], "title": _job_title(CURRENT["kind"], CURRENT["id"])})
            if entry["state"] == "running":
                snap = ENGINE.snapshot(entry["prompt_id"])
                item.update({"progress": snap.get("progress"),
                             "label": stage_label(snap["stage"]) if snap.get("stage") else None})
        elif entry["mine"] and not entry["client"].startswith(ENGINE.client_id):
            item["note"] = "sent before the app restarted"
        items.append(item)
    for job in jobs.waiting_jobs():
        if job["kind"] in jobs.IDENTITY_FIELDS:
            song = one(f"SELECT {jobs.IDENTITY_FIELDS[job['kind']]} AS status FROM identity_songs WHERE id = ?", (job["id"],))
            row = {"title": _job_title(job["kind"], job["id"]), "status": song["status"]} if song else None
        elif job["kind"] == "lyrics":
            draft = LYRICS.get(job["id"])
            row = {"title": _job_title("lyrics", job["id"]), "status": draft["status"]} if draft else None
        elif job["kind"] == "transcribe":
            row = one("SELECT title, transcribe_state AS status FROM sources WHERE id = ?", (job["id"],))
        else:
            row = one("SELECT title, status FROM takes WHERE id = ?", (job["id"],))
        if not row or row["status"] != "queued":
            continue   # deleted or cancelled while it waited; the worker will skip it
        title = row["title"]
        items.append({"state": "waiting", "kind": job["kind"], "id": job["id"], "title": title,
                      "outside": False, "client": None, "since": None})
    for item in items:
        item["seconds"] = round(now - item["since"], 1) if item.get("since") else None
        item.pop("since", None)
    return items


@app.get("/api/state")
def state() -> dict:
    """Served from what the keeper last saw, so a page poll never waits on the engine."""
    training = _training_run()
    current = None
    if CURRENT:
        current = {
            "kind": CURRENT["kind"],
            "id": CURRENT["id"],
            "elapsed": round(time.time() - CURRENT["started"], 1),
            **ENGINE.snapshot(CURRENT.get("prompt_id")),
        }
        if current.get("stage"):
            current["label"] = stage_label(current["stage"])

    return {
        "version": config.VERSION,
        "settings": settings_payload(),
        "engine": {
            "url": config.ENGINE_URL,
            "online": ENGINE.online,
            "error": ENGINE.last_error,
            "compat": ENGINE.compat,
            "queue": ENGINE.queue_counts,
            "gpu": ENGINE.gpu() if ENGINE.online else None,
        },
        "current": current,
        # A LoRA being trained holds the card, so the page disables the rest while it
        # reports: a training run, how far along, and what it has cost so far.
        "training": None if not training else {
            "id": training["id"],
            "identity_id": training["identity_id"],
            "lora_name": training["lora_name"],
            "state": training["state"],
            "steps": training["steps"],
            "rank": training["rank"],
            "elapsed": round(time.time() - training["started_at"], 1) if training["started_at"] else 0,
        },
        "queue": queue_view(),
        "stems": {
            "available": stems.installed(),
            "models": [{"id": k, "label": v["label"], "stems": v["stems"]} for k, v in stems.MODELS.items()],
            "formats": stems.FORMATS,
            "avg_seconds": float(get_setting("avg_stems_seconds", "0") or 0),
            "current": ({"id": CURRENT_STEMS.get("id"), "title": CURRENT_STEMS.get("title"),
                         "elapsed": round(time.time() - CURRENT_STEMS.get("started", time.time()), 1)}
                        if CURRENT_STEMS else None),
        },
        "options": {
            "default_style": config.DEFAULT_STYLE,
            "avg_render_seconds": float(get_setting("avg_render_seconds", "0") or 0),
            "interpretations": [{"id": key, "name": INTERPRETATION_NAMES[key]} for key in INTERPRETATIONS],
            "lyric_structures": [{"id": key, "sections": value} for key, value in lyrics.STRUCTURES.items()],
            "lyrics_available": ENGINE.options.get("lyrics", False),
            "instrumental_available": ENGINE.options.get("instrumental", False),
            "realaudio": ENGINE.options.get("realaudio", False),
            "loras": loras.catalogue(ENGINE.options.get("loras", [])),
            "harmony_steps": HARMONY_STEPS,
            # Unknown until the engine has been read, so only a confirmed absence disables it.
            "harmony_available": ENGINE.options.get("harmony", False) or not ENGINE.options_loaded,
            # EXPERIMENTAL: off unless built in, so the corpus screen hides the button
            # rather than offering something that answers 501.  See config.TRAINING_ENABLED.
            "training_available": config.TRAINING_ENABLED and ENGINE.options.get("trainer", False),
        },
    }


# ----------------------------------------------------------------------- sources
@app.get("/api/sources")
def list_sources() -> list[dict]:
    got = rows(
        """SELECT id, title, filename, created_at, transcribe_state, transcribe_error, duration,
                  abc, lyrics_state, (lyrics IS NOT NULL AND lyrics != '') AS has_lyrics,
                  (abc IS NOT NULL AND abc != '') AS has_score,
                  (SELECT COUNT(*) FROM takes t WHERE t.source_id = sources.id) AS take_count
           FROM sources ORDER BY created_at DESC"""
    )
    for item in got:
        # What the score says the music lasts, so the page can weigh it against the
        # recording without asking for the whole score.
        found = score.estimate(item.pop("abc") or "")
        item["score_seconds"] = found["seconds"] if found else None
        item["score_bpm"] = found["bpm"] if found else None
    return got


@app.get("/api/sources/{source_id}")
def get_source(source_id: str) -> dict:
    source = one("SELECT * FROM sources WHERE id = ?", (source_id,))
    if not source:
        raise HTTPException(404, "no such source")
    return source


class TooLarge(Exception):
    pass


def _store_upload(fileobj) -> tuple[str, Path, int]:
    """Copy an upload into the work folder while hashing it, a megabyte at a time."""
    config.WORK_DIR.mkdir(parents=True, exist_ok=True)
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    digest = hashlib.sha256()
    size = 0
    fd, name = tempfile.mkstemp(dir=config.WORK_DIR, prefix="upload-")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as out:
            fileobj.seek(0)
            while chunk := fileobj.read(1 << 20):
                size += len(chunk)
                if size > limit:
                    raise TooLarge()
                digest.update(chunk)
                out.write(chunk)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return digest.hexdigest(), tmp, size


@app.post("/api/sources")
async def upload_source(file: UploadFile = File(...), title: str = Form("", max_length=200)) -> dict:
    try:
        digest, tmp, size = await asyncio.to_thread(_store_upload, file.file)
    except TooLarge:
        raise HTTPException(413, f"That file is larger than {config.MAX_UPLOAD_MB} MB.")
    if not size:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, "empty upload")
    existing = one("SELECT * FROM sources WHERE sha256 = ?", (digest,))
    if existing:
        tmp.unlink(missing_ok=True)
        return {**existing, "duplicate": True}

    ext = Path(file.filename or "source.mp3").suffix.lower() or ".mp3"
    if len(ext) > 6 or not ext[1:].isalnum():
        ext = ".audio"
    source_id = uuid.uuid4().hex[:12]
    dest = source_path(digest, file.filename or "", title or "source", ext)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp.replace(dest)

    record = {
        "id": source_id,
        "title": title or Path(file.filename or "Untitled").stem,
        "filename": file.filename or dest.name,
        "stored_path": str(dest),
        "engine_file": None,   # sent to the engine when it is transcribed
        "sha256": digest,
        "created_at": time.time(),
        # Read once here, so a score transcribed from it can be checked against it.
        "duration": await asyncio.to_thread(audio_duration, dest),
    }
    execute(
        """INSERT INTO sources(id, title, filename, stored_path, engine_file, sha256, created_at, duration)
           VALUES(:id, :title, :filename, :stored_path, :engine_file, :sha256, :created_at, :duration)""",
        record,
    )
    return {**record, "transcribe_state": "none", "abc": None, "duplicate": False}


@app.post("/api/sources/{source_id}/transcribe")
async def transcribe(source_id: str) -> dict:
    _gpu_free_for_rendering()
    source = one("SELECT * FROM sources WHERE id = ?", (source_id,))
    if not source:
        raise HTTPException(404, "no such source")
    if source["transcribe_state"] in ACTIVE:
        raise HTTPException(409, "this recording is already being transcribed")
    if not Path(source["stored_path"]).exists():
        raise HTTPException(400, "the file for this recording is missing")
    execute("UPDATE sources SET transcribe_state = 'queued', transcribe_error = NULL WHERE id = ?", (source_id,))
    await QUEUE.put({"kind": "transcribe", "id": source_id})
    return {"queued": True}


@app.put("/api/sources/{source_id}/score")
def save_score(source_id: str, body: ScoreIn) -> dict:
    if not execute("UPDATE sources SET abc = ?, abc_updated_at = ? WHERE id = ?", (body.abc, time.time(), source_id)):
        raise HTTPException(404, "no such source")
    return {"saved": True, "chars": len(body.abc)}


@app.delete("/api/sources/{source_id}")
async def delete_source(source_id: str) -> dict:
    """Delete an uploaded recording and its stems.  Covers made from it keep their
    audio and score, but cannot be rendered again from the recording."""
    source = one("SELECT * FROM sources WHERE id = ?", (source_id,))
    if not source:
        raise HTTPException(404, "no such source")
    if source["transcribe_state"] in ACTIVE:
        raise HTTPException(409, "this recording is being transcribed. Wait for it to finish.")
    sets = rows("SELECT * FROM stem_sets WHERE source_id = ?", (source_id,))
    for item in sets:
        jobs.cancel_stems(item)
    execute("DELETE FROM stem_sets WHERE source_id = ?", (source_id,))
    execute("DELETE FROM sources WHERE id = ?", (source_id,))
    folders = [(Path(source["stored_path"]), config.SOURCES_DIR)]
    folders += [(Path(item["folder"]), config.DATA_DIR) for item in sets if item["folder"]]
    await asyncio.to_thread(remove_folders, folders)
    return {"deleted": True}


# ------------------------------------------------------------------------- takes
def _attach_stem_sets(takes: list[dict]) -> None:
    by_take: dict[str, list[dict]] = {take["id"]: [] for take in takes}
    if by_take:
        marks = ",".join("?" * len(by_take))
        for item in rows(
            f"""SELECT id, take_id, status, stage, progress, wanted, model, fmt, elapsed, error, folder
                FROM stem_sets WHERE take_id IN ({marks}) ORDER BY created_at DESC""",
            tuple(by_take),
        ):
            item["files"] = stem_files(item) if item["status"] == "done" else []
            by_take[item.pop("take_id")].append(item)
    for take in takes:
        take["stem_sets"] = by_take[take["id"]]


@app.get("/api/takes")
def list_takes(
    request: Request,
    source_id: str | None = None,
    space_id: str | None = None,
    favourite: bool = False,
    limit: int = Query(300, ge=1, le=5000),
) -> Response:
    """The library, newest first.  Carries an ETag, so a poll that finds nothing
    new costs a 304 instead of the whole list."""
    where, args = [], []
    if source_id:
        where.append("source_id = ?")
        args.append(source_id)
    if space_id:
        where.append("space_id = ?")
        args.append(space_id)
    if favourite:
        where.append("favourite = 1")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = one(f"SELECT COUNT(*) AS n FROM takes {clause}", tuple(args))["n"]
    got = rows(f"SELECT * FROM takes {clause} ORDER BY created_at DESC LIMIT ?", (*args, limit))
    for take in got:
        take["has_audio"] = bool(take["audio_path"] and Path(take["audio_path"]).exists())
        if take.get("prompt_id") and take["status"] == "running":
            take["live"] = ENGINE.snapshot(take["prompt_id"])
    _attach_stem_sets(got)
    body = json.dumps(got, separators=(",", ":"))
    etag = '"' + hashlib.sha1(body.encode()).hexdigest()[:24] + f'-{total}"'
    headers = {"ETag": etag, "Cache-Control": "no-cache", "X-Total-Count": str(total)}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="application/json", headers=headers)


@app.get("/api/takes/{take_id}")
def get_take(take_id: str) -> dict:
    take = one("SELECT * FROM takes WHERE id = ?", (take_id,))
    if not take:
        raise HTTPException(404, "no such take")
    take["has_audio"] = bool(take["audio_path"] and Path(take["audio_path"]).exists())
    if take.get("prompt_id") and take["status"] == "running":
        take["live"] = ENGINE.snapshot(take["prompt_id"])
    return take


@app.post("/api/takes/{take_id}/favourite")
def favourite(take_id: str, value: bool = True) -> dict:
    if not execute("UPDATE takes SET favourite = ? WHERE id = ?", (1 if value else 0, take_id)):
        raise HTTPException(404, "no such take")
    return {"favourite": value}


@app.delete("/api/takes/{take_id}")
async def delete_take(take_id: str) -> dict:
    take = one("SELECT * FROM takes WHERE id = ?", (take_id,))
    if not take:
        raise HTTPException(404, "no such take")
    if take["status"] in ACTIVE:
        await jobs.cancel_take(take)
    sets = rows("SELECT * FROM stem_sets WHERE take_id = ?", (take_id,))
    for item in sets:
        jobs.cancel_stems(item)
    # Rows first: a file that fails to delete leaves clutter, never a row that
    # points at nothing.
    execute("DELETE FROM stem_sets WHERE take_id = ?", (take_id,))
    execute("DELETE FROM takes WHERE id = ?", (take_id,))
    folder = Path(take["audio_path"]).parent if take.get("audio_path") else take_folder(take_id, take["title"])
    folders = [(folder, config.TAKES_DIR)] + [(Path(item["folder"]), config.DATA_DIR) for item in sets if item["folder"]]
    await asyncio.to_thread(remove_folders, folders)
    return {"deleted": True}


def _check_score(abc: str | None, kind: str | None = None) -> None:
    """Refuse to render a score that cannot be the song.  An empty score is allowed:
    the engine then writes its own."""
    if abc and abc.strip():
        issues = score.problems(abc, need_chords=False, instrumental=kind == "instrumental")
        if issues:
            raise HTTPException(400, f"This score cannot be rendered ({', '.join(issues)}). "
                                     "Write a new plan, or fix the score.")


def _checkpoint() -> str:
    """The one checkpoint the app uses.  Refused only once the engine has been read
    and does not have it; before that the job waits for the engine like any other."""
    if ENGINE.options_loaded and config.CHECKPOINT not in (ENGINE.options.get("checkpoints") or []):
        raise HTTPException(400, f"The engine does not have {config.CHECKPOINT}. Run scripts/fetch-models.sh.")
    return config.CHECKPOINT


def _interpretation(name: str | None) -> str:
    if name not in INTERPRETATIONS:
        raise HTTPException(400, f"unknown interpretation: {name}")
    return name


@app.post("/api/takes")
async def create_take(body: TakeIn) -> dict:
    source = one("SELECT * FROM sources WHERE id = ?", (body.source_id,))
    if not source:
        raise HTTPException(404, "no such source")
    _check_score(body.abc if body.abc is not None else source["abc"])
    _space(body.space_id)
    take_id = uuid.uuid4().hex[:12]
    seed = body.seed if body.seed is not None else int.from_bytes(os.urandom(4), "big")
    record = {
        "id": take_id,
        "source_id": body.source_id,
        "title": body.title or source["title"],
        "style": body.style.strip() or config.DEFAULT_STYLE,
        "lyrics": body.lyrics,
        "abc": body.abc if body.abc is not None else (source["abc"] or ""),
        "mode": body.mode if body.mode in ("full", "melody") else "full",
        "seed": seed,
        "checkpoint": _checkpoint(),
        "max_duration": body.max_duration,
        "created_at": time.time(),
        "space_id": body.space_id,
        "interpretation": _interpretation(body.interpretation),
        "realaudio": 1 if body.realaudio else 0,
        "identity_id": body.identity_id or body.persona_id,
        "persona_id": body.identity_id or body.persona_id,
        "voice_lora": body.voice_lora,
        "voice_lora_strength": body.voice_lora_strength,
        "voice_lora_clip": body.voice_lora_clip,
        **_style_lora_of(body),
    }
    execute(
        """INSERT INTO takes(id, source_id, title, style, lyrics, abc, mode, seed, checkpoint, max_duration, status, created_at,
                             space_id, interpretation, realaudio, identity_id, persona_id, voice_lora, voice_lora_strength, voice_lora_clip,
                             style_lora, style_lora_model, style_lora_clip)
           VALUES(:id, :source_id, :title, :style, :lyrics, :abc, :mode, :seed, :checkpoint, :max_duration, 'queued', :created_at,
                  :space_id, :interpretation, :realaudio, :identity_id, :persona_id, :voice_lora, :voice_lora_strength, :voice_lora_clip,
                  :style_lora, :style_lora_model, :style_lora_clip)""",
        record,
    )
    if record["mode"] == "full" and not record["abc"]:
        log.info("render queued with an empty score; the engine will write its own chords")
    await QUEUE.put({"kind": "render", "id": take_id})
    return {**record, "status": "queued"}


@app.post("/api/songs")
async def create_song(body: SongIn) -> dict:
    _gpu_free_for_rendering()
    """Plan a song from style and lyrics alone. The take lands in the planned state."""
    if not body.lyrics.strip():
        raise HTTPException(400, "write some lyrics first. The planner needs words to shape the melody.")
    title = (body.title or "").strip() or guess_title(body.lyrics) or "Untitled song"
    return await _plan_new_take("song", title, body.lyrics, body)


@app.post("/api/instrumentals")
async def create_instrumental(body: InstrumentalIn) -> dict:
    """Plan an instrumental from style and structure.  Its structure is kept where a
    song keeps its lyrics, so replan, render and Variations work unchanged."""
    if ENGINE.options_loaded and not ENGINE.options.get("instrumental"):
        raise HTTPException(400, f"The engine cannot make instrumentals: it needs {config.INSTRUMENTAL_LORA} "
                                 "in models/loras. Run scripts/fetch-models.sh.")
    try:
        structure = instrumental.normalise(body.structure)
    except ValueError as exc:
        raise HTTPException(400, f"That structure will not work: {exc}") from exc
    # "varied" was a setting once, and an old page may still send it. It is
    # taken as steady rather than refused, because that is what it renders as.
    if body.feel not in instrumental.FEELS and body.feel != "varied":
        raise HTTPException(400, f"unknown feel: {body.feel}")
    title = (body.title or "").strip() or "Untitled instrumental"
    return await _plan_new_take("instrumental", title, structure, body)


async def _plan_new_take(kind: str, title: str, words: str, body: SongIn | InstrumentalIn) -> dict:
    _check_harmony(body.harmony)
    _space(body.space_id)
    take_id = uuid.uuid4().hex[:12]
    seed = body.seed if body.seed is not None else int.from_bytes(os.urandom(4), "big")
    record = {
        "id": take_id,
        "kind": kind,
        "title": title,
        "style": body.style.strip() or config.DEFAULT_STYLE,
        "lyrics": words,
        "mode": "full",
        "seed": seed,
        "checkpoint": _checkpoint(),
        "max_duration": body.max_duration,
        "created_at": time.time(),
        "auto_render": 1 if body.auto_render else 0,
        "variety": body.variety if body.variety in PLAN_VARIETY else "normal",
        "harmony": body.harmony,
        "space_id": body.space_id,
        "interpretation": _interpretation(body.interpretation),
        "feel": getattr(body, "feel", "steady"),
        "realaudio": 1 if getattr(body, "realaudio", True) else 0,
        "identity_id": getattr(body, "identity_id", None) or getattr(body, "persona_id", None),
        "persona_id": getattr(body, "identity_id", None) or getattr(body, "persona_id", None),
        "voice_lora": getattr(body, "voice_lora", None),
        "voice_lora_strength": getattr(body, "voice_lora_strength", 1.0),
        "voice_lora_clip": getattr(body, "voice_lora_clip", 0.0),
        **_style_lora_of(body),
    }
    execute(
        """INSERT INTO takes(id, kind, source_id, title, style, lyrics, abc, mode, seed, checkpoint,
                             max_duration, status, created_at, auto_render, variety, harmony, space_id, interpretation, feel, realaudio,
                             identity_id, persona_id, voice_lora, voice_lora_strength, voice_lora_clip,
                             style_lora, style_lora_model, style_lora_clip)
           VALUES(:id, :kind, NULL, :title, :style, :lyrics, '', :mode, :seed, :checkpoint,
                  :max_duration, 'queued', :created_at, :auto_render, :variety, :harmony, :space_id, :interpretation, :feel, :realaudio,
                  :identity_id, :persona_id, :voice_lora, :voice_lora_strength, :voice_lora_clip,
                  :style_lora, :style_lora_model, :style_lora_clip)""",
        record,
    )
    await QUEUE.put({"kind": "plan", "id": take_id})
    return {**record, "status": "queued"}


# ------------------------------------------------------------------------ spaces
def _space(space_id: str) -> dict:
    space = one("SELECT * FROM spaces WHERE id = ?", (space_id,))
    if not space:
        raise HTTPException(404, "that space no longer exists. Choose another.")
    return space


def _space_name(name: str, keep: str | None = None) -> str:
    """A trimmed name no other space already has, ignoring case."""
    name = " ".join(name.split())
    if not name:
        raise HTTPException(400, "give the space a name")
    clash = one("SELECT id FROM spaces WHERE lower(name) = lower(?) AND id IS NOT ?", (name, keep))
    if clash:
        raise HTTPException(409, f"there is already a space called {name}")
    return name


@app.get("/api/spaces")
def list_spaces() -> list[dict]:
    """Default first, then by name, each with how many takes it holds."""
    return rows(
        """SELECT s.id, s.name, s.created_at, COUNT(t.id) AS takes, MAX(t.created_at) AS last_take_at
           FROM spaces s LEFT JOIN takes t ON t.space_id = s.id
           GROUP BY s.id ORDER BY s.id != ?, lower(s.name)""",
        (DEFAULT_SPACE,),
    )


@app.post("/api/spaces")
def create_space(body: SpaceIn) -> dict:
    space = {"id": uuid.uuid4().hex[:12], "name": _space_name(body.name), "created_at": time.time()}
    execute("INSERT INTO spaces(id, name, created_at) VALUES(:id, :name, :created_at)", space)
    return {**space, "takes": 0, "last_take_at": None}


@app.put("/api/spaces/{space_id}")
def rename_space(space_id: str, body: SpaceIn) -> dict:
    _space(space_id)
    name = _space_name(body.name, keep=space_id)
    execute("UPDATE spaces SET name = ? WHERE id = ?", (name, space_id))
    return {"id": space_id, "name": name}


@app.delete("/api/spaces/{space_id}")
def delete_space(space_id: str) -> dict:
    """Deleting a space never deletes takes: they move to Default."""
    if space_id == DEFAULT_SPACE:
        raise HTTPException(400, "the Default space cannot be deleted")
    _space(space_id)
    moved = execute("UPDATE takes SET space_id = ? WHERE space_id = ?", (DEFAULT_SPACE, space_id))
    execute("DELETE FROM spaces WHERE id = ?", (space_id,))
    return {"deleted": True, "moved": moved}


@app.post("/api/takes/{take_id}/move")
def move_take(take_id: str, body: MoveIn) -> dict:
    space = _space(body.space_id)
    if not execute("UPDATE takes SET space_id = ? WHERE id = ?", (space["id"], take_id)):
        raise HTTPException(404, "no such take")
    return {"space_id": space["id"], "name": space["name"]}


def _check_harmony(step: int | None) -> None:
    if step and ENGINE.options_loaded and not ENGINE.options.get("harmony"):
        raise HTTPException(400, "The engine has no harmony node, so Harmony must stay at Familiar. "
                                 "Rebuild the engine: docker compose up -d --build engine")


def _idle_take(take_id: str) -> dict:
    take = one("SELECT * FROM takes WHERE id = ?", (take_id,))
    if not take:
        raise HTTPException(404, "no such take")
    if take["status"] in ACTIVE:
        raise HTTPException(409, "this take is already queued or running. Cancel it first.")
    return take


@app.post("/api/takes/{take_id}/render")
async def render_take(take_id: str, body: RenderIn | None = None) -> dict:
    _gpu_free_for_rendering()
    """Render a take that already has a score, optionally in another interpretation."""
    take = _idle_take(take_id)
    if not (take["abc"] or "").strip():
        raise HTTPException(400, "this take has no score yet. Write a plan first.")
    _check_score(take["abc"], take["kind"])
    _checkpoint()
    interpretation = take["interpretation"] if body is None or body.interpretation is None else _interpretation(body.interpretation)
    realaudio = take["realaudio"] if body is None or body.realaudio is None else (1 if body.realaudio else 0)
    identity_val = None
    if body is not None:
        identity_val = body.identity_id or body.persona_id
    if identity_val is None:
        identity_val = take.get("identity_id") or take.get("persona_id")
    voice_lora = take.get("voice_lora") if body is None or body.voice_lora is None else (body.voice_lora or None)
    voice_lora_strength = take.get("voice_lora_strength", 1.0) if body is None or body.voice_lora_strength is None else body.voice_lora_strength
    seed = int.from_bytes(os.urandom(4), "big") if (body is not None and body.reseed) else take["seed"]
    execute("UPDATE takes SET status = 'queued', error = NULL, stage = NULL, checkpoint = ?, interpretation = ?, realaudio = ?, identity_id = ?, persona_id = ?, voice_lora = ?, voice_lora_strength = ?, seed = ?, vocal_check = NULL WHERE id = ?",
            (config.CHECKPOINT, interpretation, realaudio, identity_val, identity_val, voice_lora, voice_lora_strength, seed, take_id))
    await QUEUE.put({"kind": "render", "id": take_id})
    return {"queued": True, "seed": seed}


@app.post("/api/takes/{take_id}/clear")
def clear_take(take_id: str) -> dict:
    """Drop a stale failure.  A take interrupted by a restart keeps its audio and its
    score, so it can go back to the state it already reached without another job."""
    take = one("SELECT * FROM takes WHERE id = ?", (take_id,))
    if not take:
        raise HTTPException(404, "no such take")
    if take["status"] != "failed":
        raise HTTPException(409, "this take has not failed")
    audio = take["audio_path"]
    if audio and Path(audio).exists():
        status = "done"
    elif (take["abc"] or "").strip():
        status = "planned"
    else:
        raise HTTPException(400, "this take has nothing to keep. Delete it, or write a plan.")
    execute("UPDATE takes SET status = ?, error = NULL, stage = NULL WHERE id = ?", (status, take_id))
    return {"status": status}


@app.post("/api/takes/{take_id}/replan")
async def replan_take(take_id: str, body: ReplanIn | None = None) -> dict:
    """Write a fresh score plan for the same lyrics and style, optionally with a
    different plan variety or harmony."""
    take = _idle_take(take_id)
    body = body or ReplanIn()
    _check_harmony(body.harmony)
    variety = body.variety if body.variety in PLAN_VARIETY else take["variety"]
    harmony = take["harmony"] if body.harmony is None else body.harmony
    seed = int.from_bytes(os.urandom(4), "big")
    execute(
        "UPDATE takes SET seed = ?, abc = '', status = 'queued', error = NULL, stage = NULL, variety = ?, harmony = ?, checkpoint = ? WHERE id = ?",
        (seed, variety, harmony, config.CHECKPOINT, take_id),
    )
    await QUEUE.put({"kind": "plan", "id": take_id})
    return {"queued": True, "seed": seed}


def _base_title(title: str) -> str:
    """'Night drive · Tight' -> 'Night drive', so a variation of a variation is not 'X · Tight · Loose'."""
    head, sep, tail = title.rpartition(" \u00b7 ")
    return head if sep and tail in INTERPRETATION_NAMES.values() else title


@app.post("/api/takes/{take_id}/variations")
async def variations(take_id: str, body: VariationsIn) -> dict:
    _gpu_free_for_rendering()
    """Render the same score and seed once in each chosen interpretation.  Each is a
    new take beside the original, titled with its interpretation."""
    take = one("SELECT * FROM takes WHERE id = ?", (take_id,))
    if not take:
        raise HTTPException(404, "no such take")
    if not (take["abc"] or "").strip():
        raise HTTPException(400, "this take has no score to render again. Write a plan first.")
    _check_score(take["abc"], take["kind"])
    _checkpoint()
    wanted = list(dict.fromkeys(_interpretation(name) for name in body.interpretations))
    base = _base_title(take["title"])
    now = time.time()
    created = []
    realaudio = take.get("realaudio", 0) if body.realaudio is None else (1 if body.realaudio else 0)
    identity_val = (body.identity_id or body.persona_id) if (body.identity_id is not None or body.persona_id is not None) else (take.get("identity_id") or take.get("persona_id"))
    voice_lora = take.get("voice_lora") if body.voice_lora is None else (body.voice_lora or None)
    voice_lora_strength = take.get("voice_lora_strength", 1.0) if body.voice_lora_strength is None else body.voice_lora_strength
    for offset, name in enumerate(wanted):
        record = {
            "id": uuid.uuid4().hex[:12], "kind": take["kind"], "source_id": take["source_id"],
            "title": f"{base} \u00b7 {INTERPRETATION_NAMES[name]}", "style": take["style"], "lyrics": take["lyrics"],
            "abc": take["abc"], "mode": take["mode"], "seed": take["seed"], "checkpoint": config.CHECKPOINT,
            "max_duration": take["max_duration"], "created_at": now + offset * 0.001, "variety": take["variety"],
            "harmony": take["harmony"], "space_id": take["space_id"], "interpretation": name, "feel": take["feel"],
            "realaudio": realaudio, "identity_id": identity_val, "persona_id": identity_val,
            "voice_lora": voice_lora, "voice_lora_strength": voice_lora_strength,
            "voice_lora_clip": take.get("voice_lora_clip", 0.0),
            "style_lora": take.get("style_lora"),
            "style_lora_model": take.get("style_lora_model", 1.0),
            "style_lora_clip": take.get("style_lora_clip", 1.0),
        }
        execute(
            """INSERT INTO takes(id, kind, source_id, title, style, lyrics, abc, mode, seed, checkpoint, max_duration,
                                 status, created_at, variety, harmony, space_id, interpretation, feel, realaudio,
                                 identity_id, persona_id, voice_lora, voice_lora_strength, voice_lora_clip,
                                 style_lora, style_lora_model, style_lora_clip)
               VALUES(:id, :kind, :source_id, :title, :style, :lyrics, :abc, :mode, :seed, :checkpoint, :max_duration,
                      'queued', :created_at, :variety, :harmony, :space_id, :interpretation, :feel, :realaudio,
                      :identity_id, :persona_id, :voice_lora, :voice_lora_strength, :voice_lora_clip,
                      :style_lora, :style_lora_model, :style_lora_clip)""",
            record,
        )
        await QUEUE.put({"kind": "render", "id": record["id"]})
        created.append({"id": record["id"], "title": record["title"], "interpretation": name})
    return {"created": created}


# ---------------------------------------------------------------------- identities
IDENTITY_STEPS = ("vocals_state", "score_state", "lyrics_state", "style_state")
PERSONA_STEPS = IDENTITY_STEPS


def _identity(identity_id: str) -> dict:
    identity = one("SELECT * FROM identities WHERE id = ?", (identity_id,))
    if not identity:
        raise HTTPException(404, "no such identity")
    return identity


_persona = _identity


def _identity_view(identity: dict) -> dict:
    songs = rows("SELECT * FROM identity_songs WHERE identity_id = ? ORDER BY position", (identity["id"],))
    for song in songs:
        song["caption"] = identities.caption(identity["trigger_word"], song["description"] or identity["description"],
                                            identity["voice"], song["key"], song["tempo"])
    chosen = [s for s in songs if s["include"]]
    busy = any(s[f] in ("queued", "running") for s in songs for f in IDENTITY_STEPS)
    return {**identity, "songs": songs, "busy": busy,
            "summary": {"songs": len(songs), "included": len(chosen),
                        "minutes": round(sum(s["duration"] or 0 for s in chosen) / 60, 1),
                        "analysed": sum(1 for s in chosen if all(s[f] == "done" for f in IDENTITY_STEPS)),
                        "checked": sum(1 for s in chosen if s["lyrics_checked"])}}


_persona_view = _identity_view


def _clean_trigger(word: str) -> str:
    word = re.sub(r"[^a-z0-9]", "", word.lower())
    if len(word) < 2:
        raise HTTPException(400, "the trigger word needs at least two letters or digits")
    return word


@app.get("/api/import/browse")
def import_browse(path: str | None = None) -> dict:
    try:
        return identities.browse(path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/engine/reload-options")
async def reload_engine_options() -> dict:
    """Read the engine's lists again, for a model file that changed by hand."""
    try:
        await ENGINE.refresh_options()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"the engine did not answer: {exc}")
    options = ENGINE.options or {}
    return {"checkpoints": len(options.get("checkpoints") or []),
            "loras": len(options.get("loras") or [])}


@app.get("/api/identities")
@app.get("/api/personas", include_in_schema=False)
def list_identities() -> list[dict]:
    return rows("""SELECT i.id, i.name, i.trigger_word, i.voice, i.lora, i.created_at, i.exported_at,
                          COUNT(s.id) AS songs, SUM(s.include) AS included
                   FROM identities i LEFT JOIN identity_songs s ON s.identity_id = i.id
                   GROUP BY i.id ORDER BY i.created_at DESC""")


list_personas = list_identities


@app.post("/api/identities")
@app.post("/api/personas", include_in_schema=False)
async def create_identity(body: IdentityIn) -> dict:
    """Scan a folder of one singer's songs.  The folder is only read."""
    if not body.consent:
        raise HTTPException(400, "confirm that the voice is yours, or that the singer has given permission")
    folder = Path(body.folder)
    try:
        found = await asyncio.to_thread(identities.scan, folder)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not found:
        raise HTTPException(400, "there are no songs in that folder")
    identity_id = uuid.uuid4().hex[:12]
    execute("""INSERT INTO identities(id, name, trigger_word, description, voice, folder, consent, created_at, lora)
               VALUES(?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (identity_id, body.name.strip(), _clean_trigger(body.trigger_word), body.description.strip(),
             body.voice.strip().lower(), str(folder), time.time(), (body.lora or "").strip() or None))
    for position, song in enumerate(found):
        execute("""INSERT INTO identity_songs(id, identity_id, file, title, sha256, duration, bit_rate, include, flag, position)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (uuid.uuid4().hex[:12], identity_id, song["file"], song["title"], song["sha256"], song["duration"],
                 song["bit_rate"], 1 if song["include"] else 0, song["flag"], position))
    return _identity_view(_identity(identity_id))


create_persona = create_identity


@app.get("/api/identities/{identity_id}")
@app.get("/api/personas/{identity_id}", include_in_schema=False)
def get_identity(identity_id: str) -> dict:
    return _identity_view(_identity(identity_id))


get_persona = get_identity


@app.put("/api/identities/{identity_id}")
@app.put("/api/personas/{identity_id}", include_in_schema=False)
def edit_identity(identity_id: str, body: IdentityEdit) -> dict:
    _identity(identity_id)
    changes = {k: v.strip() for k, v in body.model_dump().items() if v is not None}
    if "trigger_word" in changes:
        changes["trigger_word"] = _clean_trigger(changes["trigger_word"])
    if "voice" in changes:
        changes["voice"] = changes["voice"].lower()
    if changes:
        execute(f"UPDATE identities SET {', '.join(f'{k} = ?' for k in changes)} WHERE id = ?", (*changes.values(), identity_id))
    return _identity_view(_identity(identity_id))


edit_persona = edit_identity


@app.delete("/api/identities/{identity_id}")
@app.delete("/api/personas/{identity_id}", include_in_schema=False)
async def delete_identity(identity_id: str) -> dict:
    """Removes the identity and its copies in the library.  The original folder is untouched."""
    _identity(identity_id)
    execute("DELETE FROM identity_songs WHERE identity_id = ?", (identity_id,))
    execute("DELETE FROM identities WHERE id = ?", (identity_id,))
    await asyncio.to_thread(remove_tree, config.DATA_DIR / "identities" / identity_id)
    return {"deleted": True}


delete_persona = delete_identity


@app.put("/api/identities/{identity_id}/songs/{song_id}")
@app.put("/api/personas/{identity_id}/songs/{song_id}", include_in_schema=False)
def edit_identity_song(identity_id: str, song_id: str, body: IdentitySongEdit) -> dict:
    song = one("SELECT * FROM identity_songs WHERE id = ? AND identity_id = ?", (song_id, identity_id))
    if not song:
        raise HTTPException(404, "no such song")
    changes = {}
    if body.include is not None:
        changes["include"] = 1 if body.include else 0
    if body.lyrics is not None:
        changes["lyrics"] = body.lyrics.replace("\r\n", "\n")
    if body.lyrics_checked is not None:
        changes["lyrics_checked"] = 1 if body.lyrics_checked else 0
    if body.description is not None:
        changes["description"] = " ".join(body.description.split())
    if changes:
        jobs.set_song(song_id, **changes)
    return one("SELECT * FROM identity_songs WHERE id = ?", (song_id,))


edit_persona_song = edit_identity_song


@app.post("/api/identities/{identity_id}/analyse")
@app.post("/api/personas/{identity_id}/analyse", include_in_schema=False)
async def analyse_identity(identity_id: str) -> dict:
    """Queue every step not yet done for each included song.  Safe to press again:
    finished steps are kept, failed ones are tried again."""
    _identity(identity_id)
    queued = 0
    for song in rows("SELECT * FROM identity_songs WHERE identity_id = ? AND include = 1 ORDER BY position", (identity_id,)):
        cpu = {f: "queued" for f in ("vocals_state", "lyrics_state") if song[f] in ("none", "failed")}
        if cpu:
            jobs.set_song(song["id"], **cpu, error=None)
            await jobs.IDENTITY_QUEUE.put({"id": song["id"]})
            queued += 1
        if song["vocals_state"] == "done":
            for kind, field in jobs.IDENTITY_FIELDS.items():
                if song[field] in ("none", "failed") and kind.startswith("identity_"):
                    jobs.set_song(song["id"], **{field: "queued"}, error=None)
                    await QUEUE.put({"kind": kind, "id": song["id"]})
                    queued += 1
    return {"queued": queued}


analyse_persona = analyse_identity


@app.get("/api/identities/{identity_id}/songs/{song_id}/audio")
@app.get("/api/personas/{identity_id}/songs/{song_id}/audio", include_in_schema=False)
def identity_song_audio(identity_id: str, song_id: str, which: str = "original") -> FileResponse:
    song = one("SELECT * FROM identity_songs WHERE id = ? AND identity_id = ?", (song_id, identity_id))
    if not song or not song["stored_path"]:
        raise HTTPException(404, "this song has not been copied in yet. Press Analyse.")
    path = Path(song["stored_path"]) if which == "original" else Path(song["stored_path"]).parent / "vocals.wav"
    if not path.is_file() or not inside(path, config.DATA_DIR):
        raise HTTPException(404, "not there yet")
    return FileResponse(path)


persona_song_audio = identity_song_audio


@app.post("/api/identities/{identity_id}/lora")
async def install_identity_lora(
    identity_id: str,
    file: UploadFile = File(...),
    name: str = Form("", max_length=80),
    trigger: str = Form("", max_length=40),
) -> dict:
    """Take a LoRA trained from this corpus and put it where the engine will find it.

    The app prepares the training set and cannot train, so the file arrives from a
    trainer: here, in ComfyUI, or anywhere else.  It is placed in models/loras with a
    note beside it, the corpus records it, and the engine is asked to look again so
    the picker offers it at once."""
    identity = _identity(identity_id)
    try:
        _digest, tmp, size = await asyncio.to_thread(_store_upload, file.file)
    except TooLarge:
        raise HTTPException(413, f"That file is larger than {config.MAX_UPLOAD_MB} MB.")
    if not size:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, "empty upload")
    wanted = name.strip() or Path(file.filename or "lora").stem
    try:
        result = await asyncio.to_thread(
            loras.install, tmp, wanted, (trigger.strip() or identity["trigger_word"]), identity["name"]
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except OSError as exc:
        raise HTTPException(500, f"could not write the LoRA: {exc}")
    finally:
        tmp.unlink(missing_ok=True)
    execute("UPDATE identities SET lora = ? WHERE id = ?", (result["name"], identity_id))
    try:
        await ENGINE.refresh_options()
    except Exception as exc:  # noqa: BLE001
        log.warning("the engine's list was not re-read: %s", exc)
    return result


def _training_run() -> dict | None:
    """The LoRA being trained, if there is one: it holds the whole GPU."""
    return one("SELECT * FROM lora_runs WHERE state IN ('queued', 'running') ORDER BY started_at IS NULL, started_at DESC LIMIT 1")


def _engine_free_for_training() -> None:
    """Refuse to start training when the card is already in use."""
    busy = CURRENT.get("kind")
    if busy:
        raise HTTPException(409, f"The engine is busy with a {busy}. Wait for it to finish.")
    waiting = one("SELECT COUNT(*) AS n FROM takes WHERE status IN ('queued', 'running')")["n"]
    if waiting:
        raise HTTPException(409, "Something is already queued for the engine. Wait for it, or stop it.")


def _gpu_free_for_rendering() -> None:
    """Refuse to start a render while a LoRA is training.  The two cannot share the
    card: training was measured at 12.5 GB of 16, and a render on top would fail."""
    run = _training_run()
    if run:
        raise HTTPException(409, "A LoRA is training, and it has the GPU until it finishes. "
                                 "Stop it first if you need the engine.")


class TrainIn(BaseModel):
    steps: int | None = Field(None, ge=50, le=50000)
    rank: int | None = Field(None, ge=4, le=128)


def _training_built_in() -> None:
    """EXPERIMENTAL FEATURE GATE.  Training is off unless it was built in.

    See config.TRAINING_ENABLED for why it is off by default: the node pack it needs
    adapts only the acoustic branch and what it produces does not sound like the
    corpus.  The route stays so the feature can be turned back on whole, and so a
    caller gets a reason rather than a 404 that looks like a bug."""
    if not config.TRAINING_ENABLED:
        raise HTTPException(
            501,
            "Training a LoRA here is experimental and is not built in. Build the engine "
            "with --build-arg WITH_TRAINER=1 and set TRAINING_ENABLED=1 for the app. "
            "Export the training set instead and train it elsewhere.",
        )


@app.post("/api/identities/{identity_id}/train")
async def train_identity(identity_id: str, body: TrainIn | None = None) -> dict:
    """EXPERIMENTAL, off unless built in.  Train a LoRA from this corpus's set.

    It takes the better part of an hour and the whole GPU, so the app refuses to start
    it while the engine is busy, refuses to start anything else on the engine while it
    runs, and shows it on the main screen with a stop button."""
    _training_built_in()
    identity = _identity(identity_id)
    if _training_run():
        raise HTTPException(409, "A LoRA is already training.")
    _engine_free_for_training()
    dataset = config.DATA_DIR / "identities" / identity_id / "dataset"
    songs = sorted(dataset.glob("*.flac")) if dataset.is_dir() else []
    if not songs:
        raise HTTPException(400, "Export the training set first: there is nothing to train on.")
    if not config.ENGINE_INPUT_DIR:
        raise HTTPException(503, "The app cannot see the engine's input folder, so it cannot hand it the set.")

    run_id = uuid.uuid4().hex[:12]
    name = re.sub(r"[^a-z0-9]+", "_", (identity["name"] or "corpus").lower()).strip("_")[:40] or "corpus"
    run = {
        "id": run_id,
        "identity_id": identity_id,
        "lora_name": f"{name}_lora",
        "steps": (body.steps if body and body.steps else config.TRAIN_STEPS),
        "rank": (body.rank if body and body.rank else config.TRAIN_RANK),
    }
    execute(
        """INSERT INTO lora_runs(id, identity_id, lora_name, steps, rank, state)
           VALUES(:id, :identity_id, :lora_name, :steps, :rank, 'queued')""",
        run,
    )
    await jobs.QUEUE.put({"kind": "train", "id": run_id})
    return {**run, "state": "queued", "songs": len(songs)}


@app.post("/api/lora-runs/{run_id}/cancel")
async def cancel_lora_run(run_id: str) -> dict:
    """EXPERIMENTAL, off unless built in.  Stop a run started before it was turned off."""
    run = one("SELECT * FROM lora_runs WHERE id = ?", (run_id,))
    if not run:
        raise HTTPException(404, "no such training run")
    await jobs.cancel_train(run_id)
    return {"cancelled": True}


@app.post("/api/identities/{identity_id}/export")
@app.post("/api/personas/{identity_id}/export", include_in_schema=False)
async def export_identity(identity_id: str) -> dict:
    """Write the training set: per included song, the audio as FLAC, its lyrics and
    its style caption.  Songs without a copy yet are skipped and listed."""
    identity = _identity(identity_id)
    view = _identity_view(identity)
    dest = config.DATA_DIR / "identities" / identity_id / "dataset"
    await asyncio.to_thread(remove_tree, dest)
    dest.mkdir(parents=True, exist_ok=True)
    written, skipped, unchecked = [], [], []
    for song in [s for s in view["songs"] if s["include"]]:
        if not song["stored_path"] or not Path(song["stored_path"]).is_file() or not song["lyrics"].strip():
            skipped.append(song["title"])
            continue
        name = identities.export_name(song)
        await asyncio.to_thread(subprocess.run, ["ffmpeg", "-v", "error", "-y", "-i", song["stored_path"], str(dest / f"{name}.flac")],
                                check=True, timeout=600)
        (dest / f"{name}.lyrics.txt").write_text(song["lyrics"].strip() + "\n", encoding="utf-8")
        (dest / f"{name}.txt").write_text(song["caption"] + "\n", encoding="utf-8")
        written.append(song["title"])
        if not song["lyrics_checked"]:
            unchecked.append(song["title"])
    manifest = {"identity": identity["name"], "trigger_word": identity["trigger_word"], "consent": True,
                "songs": written, "unchecked_lyrics": unchecked, "exported_at": time.time(), "app": config.VERSION}
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    execute("UPDATE identities SET exported_at = ?, export_dir = ? WHERE id = ?", (time.time(), str(dest), identity_id))
    return {"folder": _host_path(dest), "written": written, "skipped": skipped, "unchecked": unchecked}


export_persona = export_identity


def _host_path(path: Path) -> str:
    """A path under the data folder as the user sees it on the host, when known."""
    if config.DATA_DIR_HOST:
        try:
            return config.DATA_DIR_HOST + "/" + str(path.relative_to(config.DATA_DIR))
        except ValueError:
            pass
    return str(path)


# ------------------------------------------------------------------------ lyrics
@app.post("/api/lyrics")
async def write_lyrics(body: LyricsIn) -> dict:
    """Queue a lyric draft.  The page polls GET /api/lyrics/{id} for the words."""
    if ENGINE.options_loaded and not ENGINE.options.get("lyrics"):
        raise HTTPException(400, f"The engine cannot write lyrics: it needs {config.LYRICS_MODEL} "
                                 "in models/text_encoders. Run scripts/fetch-models.sh.")
    if body.structure not in lyrics.STRUCTURES:
        raise HTTPException(400, f"unknown structure: {body.structure}")
    jobs.forget_old_lyrics()
    record = {
        "id": uuid.uuid4().hex[:12], "status": "queued", "brief": body.brief.strip(),
        "style": body.style.strip(), "structure": body.structure,
        "seed": body.seed if body.seed is not None else int.from_bytes(os.urandom(4), "big"),
        "created_at": time.time(), "title": None, "lyrics": None, "error": None,
    }
    LYRICS[record["id"]] = record
    await QUEUE.put({"kind": "lyrics", "id": record["id"]})
    return record


@app.get("/api/lyrics/{draft_id}")
def get_lyrics(draft_id: str) -> dict:
    record = LYRICS.get(draft_id)
    if not record:
        raise HTTPException(404, "no such draft. It may have expired, or the app restarted.")
    return record


@app.post("/api/lyrics/{draft_id}/cancel")
async def cancel_lyrics(draft_id: str) -> dict:
    record = LYRICS.get(draft_id)
    if not record:
        raise HTTPException(404, "no such draft")
    if record["status"] not in ACTIVE:
        return {"cancelled": False, "status": record["status"]}
    await jobs.cancel_lyrics(record)
    return {"cancelled": True}


@app.post("/api/takes/{take_id}/cancel")
async def cancel_take(take_id: str) -> dict:
    take = one("SELECT * FROM takes WHERE id = ?", (take_id,))
    if not take:
        raise HTTPException(404, "no such take")
    if take["status"] not in ACTIVE:
        return {"cancelled": False, "status": take["status"]}
    await jobs.cancel_take(take)
    return {"cancelled": True}


@app.put("/api/takes/{take_id}/score")
def save_take_score(take_id: str, body: ScoreIn) -> dict:
    if not execute("UPDATE takes SET abc = ? WHERE id = ?", (body.abc, take_id)):
        raise HTTPException(404, "no such take")
    return {"saved": True, "chars": len(body.abc)}


@app.get("/api/takes/{take_id}/audio")
def take_audio(take_id: str) -> FileResponse:
    take = one("SELECT audio_path, title FROM takes WHERE id = ?", (take_id,))
    if not take or not take["audio_path"] or not Path(take["audio_path"]).exists():
        raise HTTPException(404, "no audio for this take")
    safe = "".join(ch for ch in (take["title"] or "take") if ch.isalnum() or ch in " -_")[:60].strip() or "take"
    return FileResponse(take["audio_path"], media_type="audio/flac", filename=f"{safe}.flac")


@app.get("/api/takes/{take_id}/peaks")
def take_peaks(take_id: str) -> dict:
    take = one("SELECT audio_path FROM takes WHERE id = ?", (take_id,))
    if not take or not take["audio_path"] or not Path(take["audio_path"]).exists():
        raise HTTPException(404, "no audio for this take")
    result = ensure_peaks(Path(take["audio_path"]))
    if not result:
        raise HTTPException(500, "could not read the waveform")
    return result


def sweep_engine_input(max_age_hours: float = 24) -> None:
    """Let go of the copies the app has sent the engine and finished with.

    Everything the app uploads is written into the engine's input folder and, until
    now, nothing ever removed it: 634 MB had collected.  It is only ever a copy of
    something the app still holds, so anything a day old goes.  Directories are left
    alone — a training run caches its encoded latents in one, and rebuilding that
    costs twenty five seconds per corpus."""
    root = config.ENGINE_INPUT_DIR
    if not root or not root.is_dir():
        return
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for entry in root.iterdir():
        try:
            if not entry.is_file() or entry.stat().st_mtime > cutoff:
                continue
            entry.unlink()
            removed += 1
        except OSError as exc:  # noqa: BLE001
            log.debug("could not remove %s: %s", entry, exc)
    if removed:
        log.info("removed %d finished uploads from the engine's input folder", removed)


def fill_source_durations() -> None:
    """Recordings added before the column existed: read each one's length once."""
    for source in rows("SELECT id, stored_path FROM sources WHERE duration IS NULL"):
        path = Path(source["stored_path"])
        if not path.exists():
            continue
        seconds = audio_duration(path)
        if seconds:
            execute("UPDATE sources SET duration = ? WHERE id = ?", (seconds, source["id"]))


@app.get("/api/sources/{source_id}/peaks")
def source_peaks(source_id: str) -> dict:
    """The waveform for a recording, cached beside it the way a take's is."""
    source = one("SELECT stored_path FROM sources WHERE id = ?", (source_id,))
    if not source or not Path(source["stored_path"]).exists():
        raise HTTPException(404, "no audio for this recording")
    result = ensure_peaks(Path(source["stored_path"]))
    if not result:
        raise HTTPException(500, "could not read the waveform")
    return result


@app.get("/api/sources/{source_id}/audio")
def source_audio(source_id: str) -> FileResponse:
    source = one("SELECT stored_path, filename FROM sources WHERE id = ?", (source_id,))
    if not source or not Path(source["stored_path"]).exists():
        raise HTTPException(404, "no audio for this source")
    return FileResponse(source["stored_path"], filename=source["filename"])


# ---------------------------------------------------------------------- jobs
@app.post("/api/jobs/current/cancel")
async def cancel_current_job() -> dict:
    stopped = await jobs.cancel_current()
    return {"cancelled": bool(stopped), "job": stopped}


@app.post("/api/engine/interrupt")
async def interrupt() -> dict:
    """Stops whatever the engine is running, including work this app did not send."""
    await ENGINE.interrupt()
    return {"interrupted": True}


# ------------------------------------------------------------------- settings
@app.get("/api/settings")
def get_settings() -> dict:
    return {"settings": settings_payload()}


@app.put("/api/settings")
def put_setting(body: SettingIn) -> dict:
    save_setting(body.key, body.value)
    log.info("setting %s = %s", body.key, body.value)
    return {"settings": settings_payload()}


# ----------------------------------------------------------------------- stems
@app.get("/api/stems/options")
def stems_options() -> dict:
    return {
        "available": stems.installed(),
        "models": [{"id": key, "label": spec["label"], "stems": spec["stems"]} for key, spec in stems.MODELS.items()],
        "formats": stems.FORMATS,
        "default_dir": setting_value("stems.folder"),
        "default_format": setting_value("stems.format"),
        "default_model": setting_value("stems.model"),
        "threads": stems.DEFAULT_THREADS,
        "avg_seconds": float(get_setting("avg_stems_seconds", "0") or 0),
    }


def queue_stems(kind: str, ref_id: str, body: StemsIn) -> dict:
    if not stems.installed():
        raise HTTPException(503, "demucs is not installed in this container")
    if kind == "take":
        item = one("SELECT id, title, audio_path FROM takes WHERE id = ?", (ref_id,))
        if not item:
            raise HTTPException(404, "no such take")
        if not item["audio_path"] or not Path(item["audio_path"]).exists():
            raise HTTPException(400, "this take has no audio yet")
        take_id, source_id = item["id"], None
    else:
        item = one("SELECT id, title, stored_path FROM sources WHERE id = ?", (ref_id,))
        if not item:
            raise HTTPException(404, "no such source")
        if not Path(item["stored_path"]).exists():
            raise HTTPException(400, "the file for this recording is missing")
        take_id, source_id = None, item["id"]
    # An explicit choice wins; otherwise the Settings panel decides.
    model = body.model if body.model in stems.MODELS else setting_value("stems.model")
    if model not in stems.MODELS:
        model = "htdemucs"
    allowed = stems.MODELS[model]["stems"]
    wanted = [s for s in body.stems if s in allowed] or list(allowed)
    fmt = body.format if body.format in stems.FORMATS else setting_value("stems.format")
    if fmt not in stems.FORMATS:
        fmt = "wav"
    set_id = uuid.uuid4().hex[:12]
    # Default destination, or an override that must stay inside the data folder so
    # it survives a container rebuild and lands in the backup.
    wanted_dir = (body.save_dir or "").strip() or setting_value("stems.folder")
    dest = Path(wanted_dir) / f"{slugify(item['title'])}-{set_id}"
    if not inside(dest, config.DATA_DIR):
        raise HTTPException(400, f"the save folder must be inside {config.DATA_DIR}")
    execute(
        """INSERT INTO stem_sets(id, take_id, source_id, title, model, wanted, fmt, status, created_at, folder)
           VALUES(?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)""",
        (set_id, take_id, source_id, item["title"], model, ",".join(wanted), fmt, time.time(), str(dest)),
    )
    return {"id": set_id, "model": model, "stems": wanted, "format": fmt, "status": "queued"}


@app.post("/api/takes/{take_id}/stems")
async def take_stems(take_id: str, body: StemsIn) -> dict:
    result = queue_stems("take", take_id, body)
    await STEM_QUEUE.put({"id": result["id"]})
    return result


@app.post("/api/sources/{source_id}/stems")
async def source_stems(source_id: str, body: StemsIn) -> dict:
    result = queue_stems("source", source_id, body)
    await STEM_QUEUE.put({"id": result["id"]})
    return result


@app.post("/api/sources/{source_id}/lyrics")
async def source_lyrics(source_id: str) -> dict:
    """Hear the words in a recording.  Separating the vocal and listening to it
    takes minutes, so it is asked for rather than done with every transcription,
    and it runs in the CPU lane beside stems, leaving the GPU free."""
    source = one("SELECT * FROM sources WHERE id = ?", (source_id,))
    if not source:
        raise HTTPException(404, "no such recording")
    if not Path(source["stored_path"]).exists():
        raise HTTPException(400, "the file for this recording is missing")
    if source["lyrics_state"] in ("queued", "running"):
        return {"state": source["lyrics_state"], "progress": source["lyrics_progress"]}
    execute("UPDATE sources SET lyrics_state = 'queued', lyrics_error = NULL, lyrics_progress = 0,"
            " lyrics_stage = 'Waiting' WHERE id = ?", (source_id,))
    await STEM_QUEUE.put({"kind": "lyrics", "id": source_id})
    return {"state": "queued", "progress": 0.0}


@app.get("/api/sources/{source_id}/lyrics")
def source_lyrics_state(source_id: str) -> dict:
    """What the job is doing, and the words once it has them."""
    source = one("SELECT * FROM sources WHERE id = ?", (source_id,))
    if not source:
        raise HTTPException(404, "no such recording")
    return {
        "state": source["lyrics_state"],
        "progress": source["lyrics_progress"],
        "stage": source["lyrics_stage"],
        "error": source["lyrics_error"],
        "lyrics": source["lyrics"],
    }


@app.delete("/api/sources/{source_id}/lyrics")
def stop_source_lyrics(source_id: str) -> dict:
    """Stop a running job.  A queued one never starts; a running one is the task
    the CPU lane is holding."""
    source = one("SELECT * FROM sources WHERE id = ?", (source_id,))
    if not source:
        raise HTTPException(404, "no such recording")
    if source["lyrics_state"] == "running" and CURRENT_STEMS.get("id") == source_id:
        CURRENT_STEMS["task"].cancel()
    elif source["lyrics_state"] == "queued":
        execute("UPDATE sources SET lyrics_state = 'failed', lyrics_error = 'cancelled',"
                " lyrics_stage = NULL WHERE id = ?", (source_id,))
    return {"state": "cancelled"}


def stem_files(item: dict) -> list[dict]:
    if not item.get("folder"):
        return []
    folder = Path(item["folder"])
    if not folder.is_dir():
        return []
    return [
        {"name": path.stem, "file": path.name, "bytes": path.stat().st_size}
        for path in sorted(folder.glob(f"*.{item['fmt']}"))
    ]


@app.get("/api/stem-sets")
def list_stem_sets(take_id: str | None = None, source_id: str | None = None) -> list[dict]:
    if take_id:
        sets = rows("SELECT * FROM stem_sets WHERE take_id = ? ORDER BY created_at DESC", (take_id,))
    elif source_id:
        sets = rows("SELECT * FROM stem_sets WHERE source_id = ? ORDER BY created_at DESC", (source_id,))
    else:
        sets = rows("SELECT * FROM stem_sets ORDER BY created_at DESC LIMIT 100")
    for item in sets:
        item["files"] = stem_files(item) if item["status"] == "done" else []
    return sets


def _build_zip(files: list[Path]) -> Path:
    config.WORK_DIR.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=config.WORK_DIR, prefix="zip-", suffix=".zip")
    os.close(fd)
    with zipfile.ZipFile(name, "w", zipfile.ZIP_STORED) as archive:
        for path in files:
            archive.write(path, arcname=path.name)
    return Path(name)


@app.get("/api/stem-sets/{set_id}/zip")
def stem_zip(set_id: str) -> FileResponse:
    item = one("SELECT * FROM stem_sets WHERE id = ?", (set_id,))
    if not item or not item["folder"]:
        raise HTTPException(404, "no such stem set")
    files = [Path(item["folder"]) / f["file"] for f in stem_files(item)]
    if not files:
        raise HTTPException(404, "this stem set has no files")
    archive = _build_zip(files)
    safe = "".join(ch for ch in (item["title"] or "stems") if ch.isalnum() or ch in " -_")[:60].strip() or "stems"
    return FileResponse(archive, media_type="application/zip", filename=f"{safe} stems.zip",
                        background=BackgroundTask(archive.unlink, missing_ok=True))


def _stem_path(set_id: str, name: str) -> Path:
    """Only names the set actually holds.  Nothing built from the request is trusted."""
    item = one("SELECT * FROM stem_sets WHERE id = ?", (set_id,))
    if not item or not item["folder"]:
        raise HTTPException(404, "no such stem set")
    if name not in {f["file"] for f in stem_files(item)}:
        raise HTTPException(404, "no such stem")
    return Path(item["folder"]) / name


@app.get("/api/stem-sets/{set_id}/{name}/peaks")
def stem_peaks(set_id: str, name: str) -> dict:
    result = ensure_peaks(_stem_path(set_id, name))
    if not result:
        raise HTTPException(500, "could not read the waveform")
    return result


@app.get("/api/stem-sets/{set_id}/{name}")
def stem_file(set_id: str, name: str) -> FileResponse:
    return FileResponse(_stem_path(set_id, name), filename=name)


@app.post("/api/stem-sets/{set_id}/cancel")
async def cancel_stem_set(set_id: str) -> dict:
    item = one("SELECT * FROM stem_sets WHERE id = ?", (set_id,))
    if not item:
        raise HTTPException(404, "no such stem set")
    jobs.cancel_stems(item)
    return {"cancelled": item["status"] in ACTIVE}


@app.delete("/api/stem-sets/{set_id}")
async def delete_stem_set(set_id: str) -> dict:
    item = one("SELECT * FROM stem_sets WHERE id = ?", (set_id,))
    if not item:
        raise HTTPException(404, "no such stem set")
    jobs.cancel_stems(item)
    execute("DELETE FROM stem_sets WHERE id = ?", (set_id,))
    if item["folder"]:
        await asyncio.to_thread(remove_folders, [(Path(item["folder"]), config.DATA_DIR)])
    return {"deleted": True}
