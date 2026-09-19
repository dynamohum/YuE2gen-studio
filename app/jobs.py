"""The two job lanes: the GPU lane (transcribe, plan, render) driven through the
engine, and the CPU lane for stems.  Both run in this process."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from pathlib import Path

from . import config, instrumental, lyrics, score, stems
from .db import bump_average, execute, one
from .engine import Engine, load_template
from .library import audio_duration, ensure_peaks, inside, remove_tree, take_audio_path, write_take_note

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
    return graph


def with_realaudio_lora(graph: dict, loader: str = "10", lora: str | None = None, strength: float = 1.0) -> dict:
    """Put the Realaudio decoder LoRA between the checkpoint and KSampler. The text/CLIP
    side is left alone (strength 0.0), so the ABC planner and language model are untouched."""
    lora_name = lora or config.REAL_AUDIO_LORA
    graph["25"] = {"class_type": "LoraLoader", "inputs": {
        "model": [loader, 0], "clip": [loader, 1], "lora_name": lora_name,
        "strength_model": strength, "strength_clip": 0.0}}
    graph["14"]["inputs"]["model"] = ["25", 0]
    return graph


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
    elapsed = time.time() - started
    execute(
        "UPDATE takes SET status = 'done', stage = NULL, audio_path = ?, duration = ?, finished_at = ?, elapsed = ?, error = NULL WHERE id = ?",
        (str(dest), duration, time.time(), elapsed, ref_id),
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


async def stems_worker() -> None:
    while True:
        job = await STEM_QUEUE.get()
        row = one("SELECT title FROM stem_sets WHERE id = ?", (job["id"],))
        task = asyncio.create_task(run_stems_job(job["id"]))
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
                fail_stem(job["id"], "cancelled")
            elif task.exception():
                log.error("stems job crashed", exc_info=task.exception())
                fail_stem(job["id"], str(task.exception())[:400])
        finally:
            CURRENT_STEMS.clear()
            STEM_QUEUE.task_done()


def cancel_stems(item: dict) -> None:
    if item["status"] == "queued":
        execute("UPDATE stem_sets SET status = 'failed', error = 'cancelled' WHERE id = ? AND status = 'queued'", (item["id"],))
    elif item["status"] == "running" and CURRENT_STEMS.get("id") == item["id"]:
        CURRENT_STEMS["task"].cancel()
