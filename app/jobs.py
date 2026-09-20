"""The two job lanes: the GPU lane (transcribe, plan, render) driven through the
engine, and the CPU lane for stems.  Both run in this process."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import config, identities, instrumental, lyrics, score, stems
from .db import bump_average, execute, get_setting, one, rows
from .engine import Engine, load_template
from .library import audio_duration, ensure_peaks, inside, remove_tree, take_audio_path, write_take_note

personas = identities

log = logging.getLogger("yue2.jobs")

ENGINE = Engine(config.ENGINE_URL)
QUEUE: "asyncio.Queue[dict]" = asyncio.Queue()
# Stems get their own lane.  Renders run on the GPU and stems on the CPU, so a
# three minute separation must never sit in front of a render.
STEM_QUEUE: "asyncio.Queue[dict]" = asyncio.Queue()
CURRENT: dict = {}
CURRENT_STEMS: dict = {}
# Ids whose running job was cancelled.  The job notices and stops.
CANCELLED: set[str] = set()
# Identity songs being copied in and having their vocal separated, on the CPU.
IDENTITY_QUEUE: "asyncio.Queue[dict]" = asyncio.Queue()
CURRENT_IDENTITY: dict = {}
# GPU steps for an identity song.  Copying in, the vocal and the lyrics run on the CPU.
IDENTITY_FIELDS = {
    "identity_score": "score_state", "identity_style": "style_state",
    "persona_score": "score_state", "persona_style": "style_state",
}
PERSONA_QUEUE = IDENTITY_QUEUE
CURRENT_PERSONA = CURRENT_IDENTITY
PERSONA_FIELDS = IDENTITY_FIELDS
# Lyric drafts, by id.  Kept in memory only: a draft is copied into the form as soon
# as it lands, so nothing is lost when the app restarts.
LYRICS: dict[str, dict] = {}
LYRICS_KEEP = 3600   # seconds a finished draft stays readable


# ------------------------------------------------------------------- templates
def build_transcribe_graph(engine_file: str) -> dict:
    graph = load_template("transcribe.json")
    graph["1"]["inputs"]["audio"] = engine_file
    return graph


# The ABC sampler settings behind the "plan variety" control.
# The vendor default is temperature 0.7 with a repetition penalty of 1.005, which
# lets a four-bar loop repeat for a whole song. A higher penalty pushes back on that.
# The penalty hits every token, bar lines and voice headers included, so too much of
# it breaks the score: wild used to be 1.25 / 1.18 and broke 6 of 6 test plans.
# 1.15 / 1.08 kept every test plan readable and still varies more than bold.
PLAN_VARIETY = {
    "calm": {"temperature": 0.5, "repetition_penalty": 1.02},
    "normal": {"temperature": 0.7, "repetition_penalty": 1.005},
    "bold": {"temperature": 1.0, "repetition_penalty": 1.08},
    "wild": {"temperature": 1.15, "repetition_penalty": 1.08},
}


# The Harmony control.  Each step is a setting of the yue2_harmony node, measured
# against the stock planner on the same lyrics and seeds, on indie pop and on
# minor-key rock (see the README).  Every step caps a held root at 8 bars: without
# the cap, Colourful sat on one chord for 30 bars on rock.
#   Familiar     the stock planner: often one four-chord loop for the whole song
#   Varied       recently used chords are discouraged by their exact spelling
#   Colourful    the same, harder: verse and chorus part ways, richer chords
#   Adventurous  recently used roots are discouraged, so the harmony has to move;
#                borrowed chords appear
#   Outside      adventurous, plus a pull towards roots outside the key
HARMONY_NODE = "YuE2GenerateABCHarmony"
HARMONY_STEPS = ["Familiar", "Varied", "Colourful", "Adventurous", "Outside"]
HARMONY_OFF = {"chord_identity": "root", "chord_strength": 0.0, "chord_window": 16, "hold_limit": 8,
               "outside_bonus": 0.0, "outside_limit": 0.25}
HARMONY = {
    1: {"chord_identity": "spelling", "chord_strength": 8.0},
    2: {"chord_identity": "spelling", "chord_strength": 16.0},
    3: {"chord_identity": "root", "chord_strength": 32.0},
    4: {"chord_identity": "root", "chord_strength": 32.0, "outside_bonus": 3.0},
}


# How the render reads the score: the music sampler's settings, one named set each.
# Standard is YuE2's own default.  The names describe the result, not the numbers.
INTERPRETATIONS = {
    "standard": {"temperature": 1.0, "top_p": 0.95, "top_k": 100, "repetition_penalty": 1.2},
    "tight": {"temperature": 0.8},
    "loose": {"temperature": 1.2},
    "settled": {"repetition_penalty": 1.0},
    "restless": {"repetition_penalty": 1.35},
    "wide": {"top_k": 250, "top_p": 0.99},
}
INTERPRETATION_NAMES = {
    "standard": "Standard", "tight": "Tight", "loose": "Loose",
    "settled": "Settled", "restless": "Restless", "wide": "Wide",
}


def interpretation_sampling(name: str | None) -> dict:
    return {**INTERPRETATIONS["standard"], **INTERPRETATIONS.get(name or "standard", {})}


def feel_strength(take: dict) -> float:
    return instrumental.FEELS.get(take.get("feel") or "steady", instrumental.FEELS["steady"])


def build_plan_graph(take: dict) -> dict:
    """Write a score plan from the style and lyrics alone. No recording involved."""
    graph = load_template("song_plan.json")
    graph["1"]["inputs"]["ckpt_name"] = config.CHECKPOINT
    node = graph["2"]["inputs"]
    node["style"] = take["style"]
    node["lyrics"] = take["lyrics"]
    node["seed"] = int(take["seed"])
    node["mode"] = "full"
    variety = PLAN_VARIETY.get(take.get("variety") or "normal", PLAN_VARIETY["normal"])
    node["temperature"] = variety["temperature"]
    node["repetition_penalty"] = variety["repetition_penalty"]
    step = int(take.get("harmony") or 0)
    if step in HARMONY:
        graph["2"]["class_type"] = HARMONY_NODE
        node.update({**HARMONY_OFF, **HARMONY[step]})
    if take.get("kind") == "instrumental":
        instrumental.with_lora(graph, "1", config.INSTRUMENTAL_LORA, ("2",), feel_strength(take))
    style_lora = take.get("style_lora")
    if style_lora:
        with_plan_lora(graph, "1", style_lora, ("2",), float(take.get("style_lora_clip") or 0.0))
    voice_lora = take.get("voice_lora")
    voice_clip = float(take.get("voice_lora_clip") or 0.0)
    if voice_lora and voice_clip and voice_lora != style_lora:
        with_plan_lora(graph, "1", voice_lora, ("2",), voice_clip, node_id="22")
    return graph


def with_plan_lora(graph: dict, loader: str, lora: str, text_nodes: tuple[str, ...],
                   strength_clip: float = 1.0, node_id: str = "21") -> dict:
    """Put a style LoRA in front of the planner, where its planner half does its
    work: the plan is written in its own run, before any audio exists.

    It chains onto whatever already feeds those text nodes rather than replacing
    it, so an instrumental keeps its own LoRA and gains this one."""
    upstream = graph[text_nodes[0]]["inputs"].get("clip") or [loader, 1]
    graph[node_id] = {"class_type": "LoraLoader", "inputs": {
        "model": [loader, 0], "clip": upstream, "lora_name": lora,
        "strength_model": 0.0, "strength_clip": strength_clip}}
    for node in text_nodes:
        graph[node]["inputs"]["clip"] = [node_id, 1]
    return graph


def with_render_lora(graph: dict, node_id: str, lora: str, loader: str = "10", strength_model: float = 1.0, strength_clip: float = 0.0) -> dict:
    """Put a LoRA between the current model upstream and KSampler. The text/CLIP
    side is left alone (default 0.0), so the ABC planner and language model are untouched."""
    current_model = graph["14"]["inputs"]["model"]
    graph[node_id] = {
        "class_type": "LoraLoader",
        "inputs": {
            "model": current_model,
            "clip": [loader, 1],
            "lora_name": lora,
            "strength_model": strength_model,
            "strength_clip": strength_clip,
        },
    }
    graph["14"]["inputs"]["model"] = [node_id, 0]
    return graph


def with_realaudio_lora(graph: dict, loader: str = "10", lora: str | None = None, strength: float = 1.0) -> dict:
    """Put the Realaudio decoder LoRA between the checkpoint and KSampler. The text/CLIP
    side is left alone (strength 0.0), so the ABC planner and language model are untouched."""
    lora_name = lora or config.REAL_AUDIO_LORA
    return with_render_lora(graph, "25", lora_name, loader=loader, strength_model=strength, strength_clip=0.0)


def with_style_lora(graph: dict, lora: str, loader: str = "10",
                    strength_model: float = 1.0, strength_clip: float = 1.0) -> dict:
    """Put a style LoRA from elsewhere between the checkpoint and KSampler.

    Unlike the app's own two, both strengths are the caller's to set.  A style
    LoRA usually holds both halves, and the planner half is the one that changes
    what is written, so switching it off quietly is the wrong default."""
    return with_render_lora(graph, "27", lora, loader=loader,
                            strength_model=strength_model, strength_clip=strength_clip)


def with_identity_lora(graph: dict, lora: str, loader: str = "10", strength: float = 1.0,
                       strength_clip: float = 0.0) -> dict:
    """Put the Identity voice LoRA between the checkpoint (or upstream LoRA) and KSampler.

    The voice lives in the decoder half, which is what `strength` sets and what
    this has always applied.  An Identity trained by the FS_Audio pipeline also
    holds a planner half — how that singer writes, not how they sound — and
    `strength_clip` is that, off unless asked for."""
    return with_render_lora(graph, "26", lora, loader=loader, strength_model=strength,
                            strength_clip=strength_clip)


with_persona_lora = with_identity_lora


def build_render_graph(take: dict) -> dict:
    graph = load_template("render.json")
    graph["10"]["inputs"]["ckpt_name"] = config.CHECKPOINT
    node = graph["11"]["inputs"]
    node.update(interpretation_sampling(take.get("interpretation")))
    node["style"] = take["style"]
    node["lyrics"] = take["lyrics"]
    node["abc"] = take["abc"] or ""
    node["seed"] = int(take["seed"])
    node["mode"] = take["mode"]
    node["max_duration"] = float(take.get("max_duration") or 360)
    graph["14"]["inputs"]["seed"] = int(take["seed"])
    # A prefix unique to this run.  ComfyUI caches an output node whose inputs have
    # not changed and answers with the file it saved last time, which the app has
    # already taken and deleted.  With a new prefix only the save runs again.
    graph["16"]["inputs"]["filename_prefix"] = f"yue2studio/{take['id']}-{int(time.time() * 1000)}"
    if take.get("realaudio"):
        with_realaudio_lora(graph, "10", config.REAL_AUDIO_LORA)
    voice_lora = take.get("voice_lora")
    style_lora = take.get("style_lora")
    # The same file can be reached two ways: as an Identity's voice, which is
    # applied model-side only, and as a style LoRA, which is applied on both.
    # Chaining it twice would double it, so the style picker wins: it is the
    # more explicit of the two, and it carries both strengths.
    if voice_lora and voice_lora != style_lora:
        strength = float(take.get("voice_lora_strength") or 1.0)
        with_identity_lora(graph, voice_lora, loader="10", strength=strength,
                           strength_clip=float(take.get("voice_lora_clip") or 0.0))
    if style_lora:
        with_style_lora(graph, style_lora, loader="10",
                        strength_model=float(take.get("style_lora_model") or 0.0),
                        strength_clip=float(take.get("style_lora_clip") or 0.0))
    if take.get("kind") == "instrumental":
        node["mode"] = "full"
        instrumental.with_lora(graph, "10", config.INSTRUMENTAL_LORA, ("11",), feel_strength(take))
    return graph


def build_lyrics_graph(record: dict) -> dict:
    """Gemma through ComfyUI's own text nodes.  Built here rather than from a
    template, so an engine without them still passes the compatibility check."""
    prompt = lyrics.build_prompt(record["brief"], record["style"], record["structure"])
    return {
        "1": {"class_type": "CLIPLoader", "inputs": {"clip_name": config.LYRICS_MODEL, "type": "stable_diffusion"}},
        "2": {"class_type": "TextGenerate", "inputs": {
            "clip": ["1", 0], "prompt": prompt, "max_length": 900, "thinking": False,
            "sampling_mode": "on", "sampling_mode.temperature": 0.8, "sampling_mode.top_k": 64,
            "sampling_mode.top_p": 0.95, "sampling_mode.min_p": 0.05, "sampling_mode.repetition_penalty": 1.05,
            "sampling_mode.seed": int(record["seed"])}},
        "3": {"class_type": "PreviewAny", "inputs": {"source": ["2", 0]}},
    }


def forget_old_lyrics(now: float | None = None) -> None:
    now = now or time.time()
    for key in [k for k, r in LYRICS.items() if r["status"] in ("done", "failed") and now - r["created_at"] > LYRICS_KEEP]:
        del LYRICS[key]


def _outputs_of(job: dict, class_types: tuple[str, ...]) -> list[dict]:
    prompt = (job or {}).get("prompt") or []
    graph = prompt[2] if len(prompt) > 2 else {}
    wanted = {nid for nid, node in graph.items() if node.get("class_type") in class_types}
    return [out for nid, out in ((job or {}).get("outputs") or {}).items() if nid in wanted]


def extract_text_output(job: dict, *class_types: str) -> str | None:
    """Pull a node's text output out of a finished history record."""
    for out in _outputs_of(job, class_types):
        text = out.get("text")
        if isinstance(text, list) and text and isinstance(text[0], str):
            return text[0]
    return None


def extract_audio_item(job: dict, class_type: str) -> dict | None:
    for out in _outputs_of(job, (class_type,)):
        audio = out.get("audio")
        if isinstance(audio, list) and audio:
            return audio[0]
    return None


# ----------------------------------------------------------------------- GPU lane
def fail(kind: str, ref_id: str, message: str) -> None:
    log.warning("%s %s failed: %s", kind, ref_id, message)
    if kind == "lyrics":
        if ref_id in LYRICS:
            LYRICS[ref_id].update({"status": "failed", "error": message})
    elif kind == "transcribe":
        execute("UPDATE sources SET transcribe_state = 'failed', transcribe_error = ? WHERE id = ?", (message, ref_id))
    else:
        execute("UPDATE takes SET status = 'failed', error = ?, stage = NULL WHERE id = ?", (message, ref_id))


async def _ensure_engine_file(source: dict) -> str:
    """Upload the recording now.  Doing it at transcribe time, not at upload time,
    means a failed or lost upload is simply retried, and an engine that was
    replaced or wiped still gets the file."""
    path = Path(source["stored_path"])
    data = await asyncio.to_thread(path.read_bytes)
    result = await ENGINE.upload(f"{source['id']}{path.suffix}", data)
    name = result.get("name")
    if not name:
        raise RuntimeError("the engine did not accept the recording")
    execute("UPDATE sources SET engine_file = ? WHERE id = ?", (name, source["id"]))
    return name


async def _wait_for(kind: str, ref_id: str, prompt_id: str) -> tuple[str, dict | None]:
    """Poll until the prompt finishes.  Returns ('done', job), ('cancelled', None),
    ('timeout', None) or ('lost', None).  The time limit starts when the engine
    starts executing, so a wait in the engine's own queue does not count."""
    limit = config.TIMEOUTS[kind]
    deadline = None
    last_queue_check = 0.0
    while True:
        await asyncio.sleep(1.5)
        if ref_id in CANCELLED:
            return "cancelled", None
        job = None
        try:
            job = await ENGINE.history(prompt_id)
        except Exception as exc:  # noqa: BLE001
            log.debug("history poll failed: %s", exc)
        if job and job.get("status", {}).get("completed") is not None and job.get("status", {}).get("status_str"):
            return "done", job
        now = time.time()
        if now - ENGINE.last_contact > config.ENGINE_LOST_AFTER:
            return "lost", None
        if deadline is None:
            if ENGINE.has_started(prompt_id):
                deadline = now + limit
            elif now - last_queue_check > 6:
                last_queue_check = now
                state = await ENGINE.prompt_state(prompt_id)
                if state == "running":
                    deadline = now + limit
                elif state == "gone":
                    # Finished between the two calls, or the engine restarted.
                    try:
                        job = await ENGINE.history(prompt_id)
                    except Exception:  # noqa: BLE001
                        job = None
                    if job:
                        continue
                    return "lost", None
        elif now > deadline:
            return "timeout", None


async def run_job(kind: str, ref_id: str) -> None:
    started = time.time()
    record = None
    if kind in IDENTITY_FIELDS:
        await run_identity_job(kind, ref_id)
        return
    if kind == "lyrics":
        record = LYRICS.get(ref_id)
        if not record or record["status"] != "queued":
            return   # cancelled while it waited
        record["status"] = "running"
        graph = build_lyrics_graph(record)
    elif kind == "transcribe":
        record = one("SELECT * FROM sources WHERE id = ?", (ref_id,))
        if not record or record["transcribe_state"] != "queued":
            return   # deleted or cancelled while it waited
        execute("UPDATE sources SET transcribe_state = 'running', transcribe_error = NULL WHERE id = ?", (ref_id,))
        try:
            graph = build_transcribe_graph(await _ensure_engine_file(record))
        except Exception as exc:  # noqa: BLE001
            fail(kind, ref_id, f"could not send the recording to the engine: {exc}")
            return
    else:
        record = one("SELECT * FROM takes WHERE id = ?", (ref_id,))
        if not record or record["status"] != "queued":
            return   # deleted or cancelled while it waited
        graph = build_plan_graph(record) if kind == "plan" else build_render_graph(record)
        execute("UPDATE takes SET status = 'running', error = NULL, stage = NULL WHERE id = ?", (ref_id,))
        if kind == "render" and record.get("kind") == "instrumental" and check_mode() == "fast":
            # The finished audio will be checked for singing. Loading Demucs takes
            # longer than the check itself, so it is loaded while the render runs
            # and is ready the moment the audio is. Only for instrumentals, so an
            # installation that never makes one never holds the model.
            asyncio.create_task(asyncio.to_thread(stems.warm))

    try:
        prompt_id = await ENGINE.submit(graph)
    except Exception as exc:  # noqa: BLE001
        fail(kind, ref_id, str(exc))
        return

    CURRENT.clear()
    CURRENT.update({"kind": kind, "id": ref_id, "prompt_id": prompt_id, "started": started})
    if kind in ("plan", "render"):
        execute("UPDATE takes SET prompt_id = ? WHERE id = ?", (prompt_id, ref_id))
    try:
        outcome, job = await _wait_for(kind, ref_id, prompt_id)
        if outcome != "done":
            if outcome in ("cancelled", "timeout"):
                await ENGINE.cancel(prompt_id)
            messages = {"cancelled": "cancelled", "timeout": "timed out while the engine was working",
                        "lost": "the engine lost this job, or stopped answering"}
            fail(kind, ref_id, messages[outcome])
            return
        await _finish(kind, ref_id, record, job, started)
    finally:
        ENGINE.forget(prompt_id)
        CURRENT.clear()
        CANCELLED.discard(ref_id)


async def _finish(kind: str, ref_id: str, record: dict, job: dict, started: float) -> None:
    status_str = job.get("status", {}).get("status_str")
    if ref_id in CANCELLED:
        fail(kind, ref_id, "cancelled")
        return
    if status_str != "success":
        detail = json.dumps(job.get("status", {}).get("messages") or [])[-500:]
        fail(kind, ref_id, f"engine reported {status_str}: {detail}")
        return

    if kind == "lyrics":
        text = extract_text_output(job, "TextGenerate", "PreviewAny")
        draft = lyrics.parse(text or "")
        if draft["problems"]:
            fail(kind, ref_id, "the draft came out without song sections. Write again.")
            return
        record.update({"status": "done", "title": draft["title"], "lyrics": draft["lyrics"],
                       "finished_at": time.time(), "error": None})
        return

    if kind == "transcribe":
        abc = extract_text_output(job, "SheetSage2AudioToABC", "PreviewAny")
        if not abc:
            fail(kind, ref_id, "the engine returned no score")
            return
        execute(
            "UPDATE sources SET abc = ?, abc_updated_at = ?, transcribe_state = 'done', transcribe_error = NULL WHERE id = ?",
            (abc, time.time(), ref_id),
        )
        return

    if kind == "plan":
        abc = extract_text_output(job, "YuE2GenerateABC", "PreviewAny")
        if not abc:
            fail(kind, ref_id, "the engine returned no score plan")
            return
        issues = score.problems(abc, instrumental=record.get("kind") == "instrumental")
        if issues:
            # Stored as a failure, never as a plan, so it cannot be rendered or auto-rendered.
            advice = ", or choose a calmer Plan variety" if record.get("variety") in ("bold", "wild") else ""
            fail(kind, ref_id, f"the plan came out unreadable ({', '.join(issues)}). Write a new plan{advice}.")
            return
        elapsed = time.time() - started
        changed = execute(
            "UPDATE takes SET abc = ?, status = 'planned', stage = NULL, error = NULL, elapsed = ? WHERE id = ? AND status = 'running'",
            (abc, elapsed, ref_id),
        )
        bump_average("plan", elapsed)
        # An instrumental whose plan has a melody in the Vocal voice will sing.
        # That is knowable now, before the render is paid for, so the take waits
        # to be looked at rather than being rendered automatically.
        if changed and record.get("kind") == "instrumental" and instrumental.sings(abc):
            execute("UPDATE takes SET error = ? WHERE id = ?",
                    ("the plan has a melody in the vocal part: this may sing", ref_id))
            log.info("instrumental %s planned a vocal line; not auto-rendering", ref_id)
            return
        if changed and record.get("auto_render"):
            execute("UPDATE takes SET status = 'queued' WHERE id = ?", (ref_id,))
            await QUEUE.put({"kind": "render", "id": ref_id})
            log.info("auto-render queued for %s", ref_id)
        return

    item = extract_audio_item(job, "SaveAudioAdvanced")
    if not item:
        fail(kind, ref_id, "the engine returned no audio file")
        return
    dest = take_audio_path(ref_id, record.get("title") or ref_id)
    try:
        await ENGINE.download(item, dest)
    except Exception as exc:  # noqa: BLE001
        fail(kind, ref_id, f"could not fetch the audio: {exc}")
        return
    _drop_engine_output(item)
    # The take may have been deleted or cancelled while the file came down.
    if ref_id in CANCELLED or not one("SELECT id FROM takes WHERE id = ?", (ref_id,)):
        remove_tree(dest.parent)
        return
    duration = await asyncio.to_thread(audio_duration, dest)
    # An instrumental is checked for singing before it is called finished, so no
    # one is told it is ready and left to discover otherwise.
    sung = await asyncio.to_thread(singing_share, dest) if record.get("kind") == "instrumental" else None
    elapsed = time.time() - started
    execute(
        "UPDATE takes SET status = 'done', stage = NULL, audio_path = ?, duration = ?, finished_at = ?, elapsed = ?, error = NULL, vocal_check = ? WHERE id = ?",
        (str(dest), duration, time.time(), elapsed, sung, ref_id),
    )
    fresh = one("SELECT * FROM takes WHERE id = ?", (ref_id,))
    if fresh:
        await asyncio.to_thread(write_take_note, fresh, dest)
    await asyncio.to_thread(ensure_peaks, dest)
    bump_average("render", elapsed)


def _drop_engine_output(item: dict) -> None:
    """The engine keeps every render it saves.  Once the app has its copy, the
    engine's is a duplicate.  Only possible when the folder is mounted here."""
    root = config.ENGINE_OUTPUT_DIR
    if not root or item.get("type", "output") != "output":
        return
    path = root / (item.get("subfolder") or "") / item["filename"]
    if inside(path, root) and path.is_file():
        try:
            path.unlink()
        except OSError as exc:
            log.warning("could not remove the engine's copy %s: %s", path, exc)


async def cancel_take(take: dict) -> None:
    """Stop a take's job, queued or running.  A queued job is skipped when the
    worker reaches it, because its status is no longer 'queued'."""
    if take["status"] == "queued":
        execute("UPDATE takes SET status = 'failed', error = 'cancelled' WHERE id = ? AND status = 'queued'", (take["id"],))
    elif take["status"] == "running":
        CANCELLED.add(take["id"])
        if CURRENT.get("id") == take["id"] and CURRENT.get("prompt_id"):
            await ENGINE.cancel(CURRENT["prompt_id"])


async def cancel_current() -> dict | None:
    if not CURRENT:
        return None
    CANCELLED.add(CURRENT["id"])
    if CURRENT.get("prompt_id"):
        await ENGINE.cancel(CURRENT["prompt_id"])
    return {"kind": CURRENT["kind"], "id": CURRENT["id"]}


# ---------------------------------------------------------------------- identities
def identity_song(song_id: str) -> dict | None:
    return one("SELECT * FROM identity_songs WHERE id = ?", (song_id,))


persona_song = identity_song


def set_song(song_id: str, **fields) -> None:
    if fields:
        execute(f"UPDATE identity_songs SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), song_id))


set_identity_song = set_song


async def identity_worker() -> None:
    """Copies each song into the library and separates its vocal, one at a time,
    then hands the song to the GPU lane for key, tempo, lyrics and style."""
    while True:
        job = await IDENTITY_QUEUE.get()
        CURRENT_IDENTITY.clear()
        CURRENT_IDENTITY.update({"id": job["id"], "started": time.time()})
        try:
            await prepare_song(job["id"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("identity song %s failed", job["id"])
            set_song(job["id"], vocals_state="failed", error=f"could not prepare the song: {exc}"[:400])
        finally:
            CURRENT_IDENTITY.clear()
            IDENTITY_QUEUE.task_done()


persona_worker = identity_worker


async def prepare_song(song_id: str) -> None:
    """Copy in, separate the vocal, and transcribe it with Whisper, skipping whatever
    is already done.  Key and tempo, and the style hint, go to the GPU lane."""
    song = identity_song(song_id)
    if not song or "queued" not in (song["vocals_state"], song["lyrics_state"]):
        return
    if not song["include"]:
        # Unticked while it waited: leave it for later rather than spend the time.
        set_song(song_id, **{f: "none" for f in ("vocals_state", "lyrics_state") if song[f] == "queued"})
        return
    id_val = song.get("identity_id") or song.get("persona_id")
    identity = one("SELECT * FROM identities WHERE id = ?", (id_val,))
    source = Path(identity["folder"]) / song["file"]
    if not identities.allowed(source) or not source.is_file():
        raise RuntimeError("the song is no longer in its folder")
    set_song(song_id, vocals_state="running", error=None)
    folder = identities.song_dir(identity["id"], song)
    folder.mkdir(parents=True, exist_ok=True)
    stored = folder / f"original{source.suffix.lower()}"
    if not stored.exists():
        await asyncio.to_thread(shutil.copy2, source, stored)
    set_song(song_id, stored_path=str(stored))
    # Key and tempo only need the recording, so the GPU can start while demucs runs.
    if song["score_state"] in ("none", "failed"):
        set_song(song_id, score_state="queued")
        await QUEUE.put({"kind": "identity_score", "id": song_id})
    if not (folder / "vocals.wav").exists():
        await stems.separate(stored, folder, "htdemucs", ["vocals"], "wav", work_root=config.WORK_DIR)
    set_song(song_id, vocals_state="done")
    if identity_song(song_id)["style_state"] in ("none", "failed"):
        set_song(song_id, style_state="queued")
        await QUEUE.put({"kind": "identity_style", "id": song_id})
    if not (folder / "whisper.json").exists():
        set_song(song_id, lyrics_state="running")
        try:
            lines = await asyncio.to_thread(identities.transcribe, folder / "vocals.wav")
        except Exception as exc:  # noqa: BLE001
            set_song(song_id, lyrics_state="failed", error=f"lyrics: {exc}"[:400])
            return
        (folder / "whisper.json").write_text(json.dumps(lines, indent=1), encoding="utf-8")
    maybe_draft(song_id)


def maybe_draft(song_id: str) -> None:
    """Tag Whisper's lines with the score's sections once both are in.  A score that
    failed still gets a draft, under one verse."""
    song = identity_song(song_id)
    if not song or not song["stored_path"]:
        return
    folder = Path(song["stored_path"]).parent
    if not (folder / "whisper.json").exists() or song["score_state"] not in ("done", "failed"):
        set_song(song_id, lyrics_state="running")
        return
    lines = json.loads((folder / "whisper.json").read_text(encoding="utf-8"))
    abc = (folder / "score.abc").read_text(encoding="utf-8") if (folder / "score.abc").exists() else ""
    draft = identities.tag_lyrics(lines, identities.score_sections(abc), song["duration"] or 0)
    # Words the user has already checked are theirs: a new draft never replaces them.
    if song["lyrics_checked"]:
        set_song(song_id, lyrics_state="done")
    else:
        set_song(song_id, lyrics=draft, lyrics_state="done")


def _gemma_graph(prompt: str, audio_files: list[str], max_length: int) -> dict:
    """Gemma on the engine: one CLIPLoader, then one TextGenerate per audio file (or
    one with no audio).  Greedy, so a transcription does not invent words."""
    graph = {"1": {"class_type": "CLIPLoader", "inputs": {"clip_name": config.LYRICS_MODEL, "type": "stable_diffusion"}}}
    for index, name in enumerate(audio_files or [None]):
        base = 10 + index * 3
        inputs = {"clip": ["1", 0], "prompt": prompt, "max_length": max_length, "thinking": False, "sampling_mode": "off"}
        if name:
            graph[str(base)] = {"class_type": "LoadAudio", "inputs": {"audio": name}}
            inputs["audio"] = [str(base), 0]
        graph[str(base + 1)] = {"class_type": "TextGenerate", "inputs": inputs}
        graph[str(base + 2)] = {"class_type": "PreviewAny", "inputs": {"source": [str(base + 1), 0]}}
    return graph


def _texts_in_order(job: dict) -> list[str]:
    outputs = (job or {}).get("outputs") or {}
    return [outputs[nid]["text"][0] for nid in sorted(outputs, key=int) if outputs[nid].get("text")]


async def _run_graph(kind: str, ref_id: str, graph: dict) -> dict:
    prompt_id = await ENGINE.submit(graph)
    CURRENT.clear()
    CURRENT.update({"kind": kind, "id": ref_id, "prompt_id": prompt_id, "started": time.time()})
    try:
        outcome, job = await _wait_for(kind, ref_id, prompt_id)
        if outcome != "done":
            if outcome in ("cancelled", "timeout"):
                await ENGINE.cancel(prompt_id)
            raise RuntimeError({"cancelled": "cancelled", "timeout": "timed out"}.get(outcome, "the engine lost the job"))
        if job.get("status", {}).get("status_str") != "success":
            raise RuntimeError("engine error: " + json.dumps(job.get("status", {}).get("messages") or [])[-300:])
        return job
    finally:
        ENGINE.forget(prompt_id)
        CURRENT.clear()
        CANCELLED.discard(ref_id)


async def _upload(path: Path, name: str) -> str:
    data = await asyncio.to_thread(path.read_bytes)
    result = await ENGINE.upload(name, data)
    if not result.get("name"):
        raise RuntimeError("the engine did not accept the audio")
    return result["name"]


async def run_identity_job(kind: str, song_id: str) -> None:
    field = IDENTITY_FIELDS[kind]
    song = identity_song(song_id)
    if not song or song[field] != "queued":
        return
    if not song["include"]:
        set_song(song_id, **{field: "none"})
        return
    set_song(song_id, **{field: "running"})
    folder = Path(song["stored_path"]).parent
    try:
        if kind in ("identity_score", "persona_score"):
            name = await _upload(Path(song["stored_path"]), f"identity-{song_id}{Path(song['stored_path']).suffix}")
            job = await _run_graph(kind, song_id, build_transcribe_graph(name))
            abc = extract_text_output(job, "SheetSage2AudioToABC", "PreviewAny") or ""
            (folder / "score.abc").write_text(abc, encoding="utf-8")
            key, tempo = identities.key_and_tempo(abc)
            set_song(song_id, key=key, tempo=tempo, score_state="done")
            maybe_draft(song_id)
        elif kind in ("identity_style", "persona_style"):
            samples = await asyncio.to_thread(identities.read_mono, Path(song["stored_path"]))
            middle = len(samples) / identities.CHUNK_RATE * 0.4
            clip = identities.write_chunk(samples, (middle, middle + 30), folder / "style-clip.wav")
            name = await _upload(clip, f"identity-{song_id}-style.wav")
            job = await _run_graph(kind, song_id, _gemma_graph(identities.DESCRIBE, [name], 120))
            hint = " ".join((_texts_in_order(job) or [""])[0].split())[:300]
            set_song(song_id, style_hint=hint, style_state="done")
    except Exception as exc:  # noqa: BLE001
        log.warning("%s for %s failed: %s", kind, song_id, exc)
        set_song(song_id, **{field: "failed"}, error=f"{kind.split('_')[1]}: {exc}"[:400])
        if kind in ("identity_score", "persona_score"):
            maybe_draft(song_id)


run_persona_job = run_identity_job


async def cancel_lyrics(record: dict) -> None:
    if record["status"] == "queued":
        record.update({"status": "failed", "error": "cancelled"})
    elif record["status"] == "running":
        CANCELLED.add(record["id"])
        if CURRENT.get("id") == record["id"] and CURRENT.get("prompt_id"):
            await ENGINE.cancel(CURRENT["prompt_id"])


def waiting_jobs() -> list[dict]:
    """App jobs not yet sent to the engine, in the order the worker will take them."""
    return list(QUEUE._queue)   # asyncio.Queue keeps its items in a deque


async def worker() -> None:
    while True:
        job = await QUEUE.get()
        try:
            await run_job(job["kind"], job["id"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("job crashed")
            fail(job["kind"], job["id"], f"internal error: {exc}")
        finally:
            QUEUE.task_done()


async def keeper() -> None:
    """Keep the engine status fresh for the page, and read the node schemas again
    when the engine comes back or every few minutes."""
    last_options = time.time() if ENGINE.options_loaded else 0.0
    was_online = ENGINE.online
    while True:
        await ENGINE.refresh_status()
        now = time.time()
        if ENGINE.online and (not was_online or not ENGINE.options_loaded or now - last_options > 300):
            try:
                await ENGINE.refresh_options()
                last_options = now
            except Exception as exc:  # noqa: BLE001
                log.warning("option refresh failed: %s", exc)
        if ENGINE.online != was_online:
            log.info("engine %s", "online" if ENGINE.online else f"offline: {ENGINE.last_error}")
        was_online = ENGINE.online
        await asyncio.sleep(2)


# ---------------------------------------------------------------------- stem lane
def fail_stem(set_id: str, message: str) -> None:
    log.warning("stems %s failed: %s", set_id, message)
    execute("UPDATE stem_sets SET status = 'failed', error = ?, stage = NULL WHERE id = ?", (message, set_id))


async def run_stems_job(set_id: str) -> None:
    job = one("SELECT * FROM stem_sets WHERE id = ?", (set_id,))
    if not job or job["status"] != "queued":
        return
    started = time.time()
    execute("UPDATE stem_sets SET status = 'running', stage = 'Starting', progress = 0 WHERE id = ?", (set_id,))

    input_path = None
    if job["take_id"]:
        row = one("SELECT audio_path FROM takes WHERE id = ?", (job["take_id"],))
        input_path = row["audio_path"] if row else None
    elif job["source_id"]:
        row = one("SELECT stored_path FROM sources WHERE id = ?", (job["source_id"],))
        input_path = row["stored_path"] if row else None
    if not input_path or not Path(input_path).exists():
        fail_stem(set_id, "the audio for this item is missing")
        return

    last_write = {"at": 0.0}

    def progress(frac: float, stage: str) -> None:
        now = time.time()
        if now - last_write["at"] < 1.0 and frac < 1.0:
            return
        last_write["at"] = now
        execute("UPDATE stem_sets SET progress = ?, stage = ? WHERE id = ?", (round(frac, 3), stage, set_id))

    wanted = [s for s in (job["wanted"] or "").split(",") if s]
    dest = Path(job["folder"]) if job.get("folder") else (config.STEMS_DIR / set_id)
    await stems.separate(Path(input_path), dest, job["model"], wanted, job["fmt"], progress, work_root=config.WORK_DIR)

    elapsed = time.time() - started
    changed = execute(
        """UPDATE stem_sets SET status = 'done', stage = NULL, progress = 1,
                  finished_at = ?, elapsed = ?, error = NULL WHERE id = ?""",
        (time.time(), elapsed, set_id),
    )
    if not changed:
        remove_tree(dest)   # deleted while it ran
        return
    bump_average("stems", elapsed)
    log.info("stems %s done in %.1fs", set_id, elapsed)


def singing_share(audio: Path) -> float | None:
    """How much of a finished instrumental is singing, in a few seconds.

    The instrumental LoRA usually keeps the voice out and sometimes does not, so
    the audio is checked rather than assumed. Three short spans are separated
    with Demucs held in memory: a fresh process spends ten seconds loading the
    model before it does anything, which was long enough for someone to hear the
    opening, believe it was clean, and move on. This answers while they are still
    listening.
    """
    mode = check_mode()
    if mode == "off":
        return None
    work = Path(tempfile.mkdtemp(prefix="vocal-check-", dir=config.WORK_DIR))
    try:
        clip = instrumental.excerpt(audio, work / "excerpt.wav")
        if mode == "thrifty":
            # A separate program, which gives its memory back when it ends, at the
            # cost of loading the model from scratch every time.
            asyncio.run(stems.separate(clip, work / "split", "htdemucs", ["vocals"], "wav",
                                       work_root=config.WORK_DIR))
            vocals = next((work / "split").glob("*vocals*.wav"), None)
            return instrumental.sung_share(vocals) if vocals else None
        samples, rate = stems.vocal_of(clip)
        return instrumental.share_of(samples, rate)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        log.warning("vocal check failed for %s: %s", audio, exc)
        return None
    finally:
        remove_tree(work)


def check_mode() -> str:
    """How thoroughly to pay for the check: fast, thrifty, or not at all.

    Holding the separator cannot be undone once it is loaded — releasing the
    model leaves the memory with the allocator rather than the system — so the
    thrifty choice runs it as a separate program instead."""
    mode = (get_setting("instrumental.vocal_check", "fast") or "fast").lower()
    return mode if mode in ("fast", "thrifty", "off") else "fast"


async def run_vocal_check(take_id: str) -> None:
    """The same check for a take that already exists, used to fill in one made
    before the check did."""
    take = one("SELECT id, audio_path, kind FROM takes WHERE id = ?", (take_id,))
    if not take or take["kind"] != "instrumental" or not take["audio_path"]:
        return
    audio = Path(take["audio_path"])
    if not audio.exists():
        return
    share = await asyncio.to_thread(singing_share, audio)
    if share is not None:
        execute("UPDATE takes SET vocal_check = ? WHERE id = ?", (share, take_id))


def fail_cover_lyrics(source_id: str, message: str) -> None:
    execute("UPDATE sources SET lyrics_state = 'failed', lyrics_error = ?, lyrics_stage = NULL WHERE id = ?",
            (message, source_id))


async def run_cover_lyrics(source_id: str) -> None:
    """Hear the words in a recording: separate its vocal, transcribe it, and lay
    the lines under the sections of the score already transcribed from it."""
    source = one("SELECT * FROM sources WHERE id = ?", (source_id,))
    if not source or source["lyrics_state"] != "queued":
        return
    path = Path(source["stored_path"])
    if not path.exists():
        fail_cover_lyrics(source_id, "the recording is missing")
        return

    last = {"at": 0.0}

    def progress(frac: float, stage: str) -> None:
        now = time.time()
        if now - last["at"] < 1.0 and frac < 1.0:
            return
        last["at"] = now
        execute("UPDATE sources SET lyrics_progress = ?, lyrics_stage = ? WHERE id = ?",
                (round(frac, 3), stage, source_id))

    execute("UPDATE sources SET lyrics_state = 'running', lyrics_error = NULL,"
            " lyrics_stage = 'Starting', lyrics_progress = 0 WHERE id = ?", (source_id,))

    work = config.WORK_DIR / f"lyrics-{source_id}"
    # Separation is most of the wait, so it owns most of the bar.
    await stems.separate(path, work, "htdemucs", ["vocals"], "wav",
                         lambda frac, stage: progress(0.02 + 0.58 * frac, "Separating the vocal"),
                         work_root=config.WORK_DIR)
    vocal = next(iter(work.glob("vocals.*")), None)
    if not vocal:
        fail_cover_lyrics(source_id, "the vocal could not be separated")
        return

    try:
        seconds = await asyncio.to_thread(instrumental.duration_of, vocal)
        progress(0.62, "Listening for words")
        lines = await asyncio.to_thread(
            identities.transcribe, vocal,
            lambda frac: progress(0.62 + 0.33 * frac, "Listening for words"), seconds)
        if not lines:
            fail_cover_lyrics(source_id, "no words were heard in this recording")
            return
        progress(0.97, "Laying the words out")
        sections = identities.score_sections(source["abc"] or "")
        text = await asyncio.to_thread(identities.tag_lyrics, lines, sections, seconds)
        execute("UPDATE sources SET lyrics = ?, lyrics_state = 'done', lyrics_stage = NULL,"
                " lyrics_progress = 1 WHERE id = ?", (text, source_id))
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def stems_worker() -> None:
    while True:
        job = await STEM_QUEUE.get()
        lyrics_job = job.get("kind") == "lyrics"
        table, fail = ("sources", fail_cover_lyrics) if lyrics_job else ("stem_sets", fail_stem)
        row = one(f"SELECT title FROM {table} WHERE id = ?", (job["id"],))
        task = asyncio.create_task(
            run_cover_lyrics(job["id"]) if lyrics_job else run_stems_job(job["id"]))
        CURRENT_STEMS.clear()
        CURRENT_STEMS.update({"id": job["id"], "started": time.time(), "task": task,
                              "title": row["title"] if row else ""})
        try:
            try:
                await asyncio.wait({task})
            except asyncio.CancelledError:
                # The app is shutting down: stop demucs with it.
                task.cancel()
                with contextlib.suppress(BaseException):
                    await task
                raise
            if task.cancelled():
                fail(job["id"], "cancelled")
            elif task.exception():
                log.error("a CPU job crashed", exc_info=task.exception())
                fail(job["id"], str(task.exception())[:400])
        finally:
            CURRENT_STEMS.clear()
            STEM_QUEUE.task_done()


def cancel_stems(item: dict) -> None:
    if item["status"] == "queued":
        execute("UPDATE stem_sets SET status = 'failed', error = 'cancelled' WHERE id = ? AND status = 'queued'", (item["id"],))
    elif item["status"] == "running" and CURRENT_STEMS.get("id") == item["id"]:
        CURRENT_STEMS["task"].cancel()
