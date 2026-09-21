"""ComfyUI engine client for YuE2 Studio.

The engine owns the GPU. This module only speaks HTTP and WebSocket to it.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from . import config

log = logging.getLogger("yue2.engine")

# How often the engine's checkpoints and LoRAs are read again. A model file added or
# removed by hand is otherwise invisible until the app restarts.
OPTIONS_EVERY = 300

STAGE_LABELS = {
    "LoadAudio": "Loading source",
    "AudioEncoderLoader": "Loading transcriber",
    "SheetSage2AudioToABC": "Transcribing melody and chords",
    "CheckpointLoaderSimple": "Loading model",
    "YuE2GenerateABC": "Writing the score plan",
    "YuE2GenerateABCHarmony": "Writing the score plan",
    "YuE2GenerateMusic": "Writing the song",
    "EmptyYuE2LatentAudio": "Preparing the render",
    "ConditioningZeroOut": "Preparing the render",
    "KSampler": "Rendering audio",
    "VAEDecodeAudio": "Decoding audio",
    "SaveAudioAdvanced": "Saving",
    "CLIPLoader": "Loading the lyric writer",
    "TextGenerate": "Writing lyrics",
    "LoraLoader": "Loading the instrumental adapter",
}

# Weights drive the progress bar.
STAGE_WEIGHT = {
    "LoadAudio": 1,
    "AudioEncoderLoader": 1,
    "SheetSage2AudioToABC": 12,
    "CheckpointLoaderSimple": 3,
    "YuE2GenerateABC": 16,
    "YuE2GenerateABCHarmony": 16,
    "YuE2GenerateMusic": 22,
    "EmptyYuE2LatentAudio": 1,
    "ConditioningZeroOut": 1,
    "KSampler": 48,
    "VAEDecodeAudio": 8,
    "SaveAudioAdvanced": 3,
    "CLIPLoader": 2,
    "TextGenerate": 20,
    "LoraLoader": 1,
}

TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATE_NAMES = ("transcribe.json", "render.json", "song_plan.json")
_TEMPLATES = {name: json.loads((TEMPLATE_DIR / name).read_text(encoding="utf-8")) for name in TEMPLATE_NAMES}


def load_template(name: str) -> dict[str, Any]:
    """A fresh copy of a graph template, read from disk once at import."""
    return copy.deepcopy(_TEMPLATES[name])


def combo_options(info: dict[str, Any], node: str, field: str) -> list[str]:
    """ComfyUI lists combo choices in two shapes. Accept both."""
    spec = info.get(node, {}).get("input", {}).get("required", {}).get(field)
    if not isinstance(spec, list) or not spec:
        return []
    if len(spec) > 1 and isinstance(spec[1], dict) and "options" in spec[1]:
        return list(spec[1]["options"])
    first = spec[0]
    if isinstance(first, (list, tuple)):
        return list(first)
    return []


# What a queued graph is, from the nodes in it.  First match wins.
JOB_KINDS = [
    ("YuE2GenerateMusic", "render"),
    ("YuE2GenerateABCHarmony", "plan"),
    ("YuE2GenerateABC", "plan"),
    ("SheetSage2AudioToABC", "transcribe"),
    ("TextGenerate", "text"),
]
APP_CLIENT_PREFIX = "yue2-studio-"


def job_kind(classes: set[str] | list[str]) -> str:
    for class_type, kind in JOB_KINDS:
        if class_type in classes:
            return kind
    return "other"


def queue_items(raw: dict[str, Any], running_since: dict[str, float], now: float) -> list[dict[str, Any]]:
    """The engine's queue, running first, then waiting in the order it will run.
    `running_since` remembers when each prompt was first seen running; the engine does
    not say, and a prompt that is gone from the queue is dropped from it."""
    items = []
    for state, key in (("running", "queue_running"), ("pending", "queue_pending")):
        for entry in sorted(raw.get(key, []), key=lambda e: e[0]):
            prompt_id = entry[1]
            graph = entry[2] if len(entry) > 2 and isinstance(entry[2], dict) else {}
            extra = entry[3] if len(entry) > 3 and isinstance(entry[3], dict) else {}
            client = str(extra.get("client_id") or "")
            created = extra.get("create_time")
            if state == "running":
                running_since.setdefault(prompt_id, now)
            items.append({
                "prompt_id": prompt_id,
                "state": state,
                "kind": job_kind({node.get("class_type") for node in graph.values() if isinstance(node, dict)}),
                "client": client[:40],
                "mine": client.startswith(APP_CLIENT_PREFIX),
                "queued_at": created / 1000 if isinstance(created, (int, float)) else None,
                "running_since": running_since.get(prompt_id) if state == "running" else None,
            })
    live = {item["prompt_id"] for item in items}
    for prompt_id in list(running_since):
        if prompt_id not in live:
            del running_since[prompt_id]
    return items


def stage_label(class_type: str) -> str:
    return STAGE_LABELS.get(class_type, class_type)


def _progress_for(stages: list[str], done_class: str | None, frac: float) -> float:
    total = sum(STAGE_WEIGHT.get(s, 1) for s in stages) or 1
    acc = 0.0
    for name in stages:
        w = STAGE_WEIGHT.get(name, 1)
        if name == done_class:
            acc += w * max(0.0, min(1.0, frac))
            break
        acc += w
    return max(0.0, min(1.0, acc / total))


class Engine:
    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")
        self.client: httpx.AsyncClient | None = None
        # Unique per process: ComfyUI sends progress only to the client that
        # submitted, so two apps on one engine must not share an id.
        self.client_id = f"yue2-studio-{uuid.uuid4().hex[:8]}"
        self._ws_task: asyncio.Task | None = None
        # prompt_id -> progress record
        self.progress: dict[str, dict[str, Any]] = {}
        # graph node id -> class_type, per prompt
        self.graphs: dict[str, dict[str, str]] = {}
        self.online = False
        self.last_error: str | None = None
        self.last_contact = 0.0
        self.options: dict[str, Any] = {"checkpoints": [], "audio_encoders": [], "harmony": False, "lyrics": False,
                                        "instrumental": False}
        self.options_loaded = False
        self._options_task: asyncio.Task[None] | None = None
        self.compat: dict[str, Any] = {"ok": False, "missing": [], "notes": []}
        # Refreshed by the keeper, so page polls never wait on the engine.
        self.stats: dict[str, Any] | None = None
        self.queue_counts = {"running": 0, "pending": 0}
        self.queue: list[dict[str, Any]] = []
        self._running_since: dict[str, float] = {}

    # ---------- lifecycle ----------
    async def start(self) -> None:
        """Never raises.  An engine that is still starting, or asleep in the split
        setup, is picked up by the keeper when it answers."""
        self.client = httpx.AsyncClient(base_url=self.url, timeout=httpx.Timeout(30.0, connect=4.0))
        self._ws_task = asyncio.create_task(self._ws_loop())
        self._options_task = asyncio.create_task(self._options_loop())
        await self.refresh_status()
        if self.online:
            try:
                await self.refresh_options()
            except Exception as exc:  # noqa: BLE001
                log.warning("engine options not read at startup: %s", exc)

    async def close(self) -> None:
        if self._options_task:
            self._options_task.cancel()
        if self._ws_task:
            self._ws_task.cancel()
        if self.client:
            await self.client.aclose()

    # ---------- status ----------
    def _contact(self) -> None:
        self.online = True
        self.last_error = None
        self.last_contact = time.time()

    async def refresh_status(self) -> None:
        assert self.client
        try:
            stats = await self.client.get("/system_stats", timeout=4.0)
            stats.raise_for_status()
            queue = await self.client.get("/queue", timeout=4.0)
            queue.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            self.online = False
            self.last_error = str(exc) or exc.__class__.__name__
            self.stats = None
            self.queue = []
            return
        self._contact()
        self.stats = stats.json()
        raw = queue.json()
        self.queue_counts = {"running": len(raw.get("queue_running", [])), "pending": len(raw.get("queue_pending", []))}
        self.queue = queue_items(raw, self._running_since, time.time())

    def gpu(self) -> dict[str, Any] | None:
        try:
            device = (self.stats or {})["devices"][0]
        except (KeyError, IndexError, TypeError):
            return None
        return {"name": device.get("name"), "vram_total": device.get("vram_total"), "vram_free": device.get("vram_free")}

    async def refresh_options(self) -> None:
        """Read node schemas, then check every node our templates need.  The schema
        document is large, so this runs at startup and when the engine comes back."""
        assert self.client
        r = await self.client.get("/object_info")
        r.raise_for_status()
        info = r.json()
        checkpoints = combo_options(info, "CheckpointLoaderSimple", "ckpt_name")
        encoders = combo_options(info, "AudioEncoderLoader", "audio_encoder_name")
        # The harmony node is optional: plans without it use the stock planner.
        text_models = combo_options(info, "CLIPLoader", "clip_name")
        loras = combo_options(info, "LoraLoader", "lora_name")
        self.options = {"checkpoints": checkpoints, "audio_encoders": encoders,
                        "harmony": "YuE2GenerateABCHarmony" in info,
                        # Lyrics are optional: without Gemma or the node, the button is greyed out.
                        "lyrics": "TextGenerate" in info and config.LYRICS_MODEL in text_models,
                        "instrumental": config.INSTRUMENTAL_LORA in loras,
                        "realaudio": config.REAL_AUDIO_LORA in loras,
                        "loras": loras}

        needed = set()
        for graph in _TEMPLATES.values():
            needed |= {node["class_type"] for node in graph.values()}
        missing = sorted(n for n in needed if n not in info)
        notes = []
        if "sheetsage2_bf16.safetensors" not in encoders:
            notes.append("SheetSage2 audio encoder is not visible to ComfyUI.")
        if config.CHECKPOINT not in checkpoints:
            notes.append(f"The YuE2 checkpoint {config.CHECKPOINT} is not visible to ComfyUI. Run scripts/fetch-models.sh.")
        self.compat = {"ok": not missing and not notes, "missing": missing, "notes": notes}
        self.options_loaded = True

    # ---------- jobs ----------
    async def upload(self, filename: str, data: bytes) -> dict[str, Any]:
        assert self.client
        files = {"image": (filename, data, "application/octet-stream")}
        form = {"type": "input", "overwrite": "true", "subfolder": ""}
        r = await self.client.post("/upload/image", files=files, data=form)
        r.raise_for_status()
        self._contact()
        return r.json()

    async def submit(self, graph: dict[str, Any]) -> str:
        assert self.client
        payload = {"prompt": graph, "client_id": self.client_id}
        r = await self.client.post("/prompt", json=payload)
        if r.status_code >= 400:
            raise RuntimeError(f"engine rejected the job: {r.text[:400]}")
        self._contact()
        pid = r.json()["prompt_id"]
        self.graphs[pid] = {nid: node["class_type"] for nid, node in graph.items()}
        self.progress[pid] = {"stage": None, "frac": 0.0, "value": None, "max": None,
                              "started": time.time(), "executing": False}
        return pid

    async def history(self, prompt_id: str) -> dict[str, Any] | None:
        assert self.client
        r = await self.client.get(f"/history/{prompt_id}")
        r.raise_for_status()
        self._contact()
        return r.json().get(prompt_id)

    async def prompt_state(self, prompt_id: str) -> str | None:
        """'running', 'pending' or 'gone' from the engine's queue; None if it did not answer."""
        assert self.client
        try:
            r = await self.client.get("/queue", timeout=4.0)
            r.raise_for_status()
        except Exception:  # noqa: BLE001
            return None
        self._contact()
        raw = r.json()
        if any(item[1] == prompt_id for item in raw.get("queue_running", [])):
            return "running"
        if any(item[1] == prompt_id for item in raw.get("queue_pending", [])):
            return "pending"
        return "gone"

    def has_started(self, prompt_id: str) -> bool:
        return bool((self.progress.get(prompt_id) or {}).get("executing"))

    async def cancel(self, prompt_id: str) -> None:
        """Take a prompt out of the engine's queue, or stop it if it is running."""
        assert self.client
        try:
            await self.client.post("/queue", json={"delete": [prompt_id]}, timeout=4.0)
            await self.client.post("/interrupt", json={"prompt_id": prompt_id}, timeout=4.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not cancel %s on the engine: %s", prompt_id, exc)

    async def interrupt(self) -> None:
        assert self.client
        await self.client.post("/interrupt")

    async def download(self, item: dict[str, Any], dest: Path) -> Path:
        assert self.client
        params = {"filename": item["filename"], "subfolder": item.get("subfolder", ""), "type": item.get("type", "output")}
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_name(dest.name + ".part")
        try:
            async with self.client.stream("GET", "/view", params=params) as r:
                r.raise_for_status()
                with partial.open("wb") as fh:
                    async for chunk in r.aiter_bytes(1 << 16):
                        fh.write(chunk)
            partial.replace(dest)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        return dest

    # ---------- progress ----------
    def snapshot(self, prompt_id: str | None) -> dict[str, Any]:
        rec = self.progress.get(prompt_id or "")
        if not rec:
            return {"stage": None, "label": None, "progress": 0.0, "value": None, "max": None, "elapsed": 0}
        stages = list(rec.get("stages") or [])
        frac = rec.get("frac") or 0.0
        overall = _progress_for(stages, rec.get("stage"), frac) if stages else 0.0
        if rec.get("stage") and stages and rec["stage"] == stages[-1]:
            overall = 1.0
        return {
            "stage": rec.get("stage"),
            "label": stage_label(rec["stage"]) if rec.get("stage") else None,
            "progress": round(overall, 4),
            "value": rec.get("value"),
            "max": rec.get("max"),
            "elapsed": round(time.time() - rec.get("started", time.time()), 1),
        }

    def forget(self, prompt_id: str) -> None:
        self.progress.pop(prompt_id, None)
        self.graphs.pop(prompt_id, None)

    async def _options_loop(self) -> None:
        """Look at the engine's lists again, now and then.

        They are read once at start-up: a LoRA put into models/loras, or taken out,
        went unnoticed until the app was restarted.  Five minutes is often enough
        for a model file that changes by hand, and one request costs nothing."""
        while True:
            await asyncio.sleep(OPTIONS_EVERY)
            if not self.online:
                continue
            try:
                await self.refresh_options()
            except Exception as exc:  # noqa: BLE001
                log.debug("engine options not re-read: %s", exc)

    async def _ws_loop(self) -> None:
        import websockets

        ws_url = self.url.replace("http://", "ws://").replace("https://", "wss://") + f"/ws?clientId={self.client_id}"
        while True:
            try:
                # Liveness comes from the protocol pings.  An idle engine sends
                # nothing, and that is not a dropped connection.
                async with websockets.connect(ws_url, open_timeout=10, ping_interval=20, ping_timeout=20, max_size=None) as ws:
                    log.info("engine websocket connected")
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            continue
                        self._handle_ws(json.loads(raw))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.debug("engine websocket unavailable: %s", exc)
            await asyncio.sleep(3)

    def _handle_ws(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        data = msg.get("data") or {}
        pid = data.get("prompt_id")
        rec = self.progress.get(pid or "")
        if rec is None:
            return
        if kind == "execution_start":
            rec["stages"] = list(self.graphs.get(pid or "", {}).values())
            rec["started"] = time.time()
            rec["executing"] = True
        elif kind == "executing":
            rec["executing"] = True
            node = data.get("node")
            if node is None:
                rec["stage"] = (rec.get("stages") or [None])[-1]
                rec["frac"] = 1.0
                return
            class_type = self.graphs.get(pid or "", {}).get(str(node))
            if class_type:
                rec["stage"] = class_type
                rec["frac"] = 0.0
                rec["value"] = None
                rec["max"] = None
        elif kind == "progress":
            rec["value"] = data.get("value")
            rec["max"] = data.get("max")
            if rec.get("max"):
                rec["frac"] = float(rec["value"] or 0) / float(rec["max"])
        elif kind in ("execution_error", "execution_interrupted"):
            rec["frac"] = 0.0
