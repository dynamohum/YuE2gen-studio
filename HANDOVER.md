# YuE2 Studio — Handover Document

> **Purpose:** Bring a fresh LLM up to speed on the entire codebase so it can
> contribute immediately. Read this first, then dive into specific files.

---

## 1. What This Project Is

**YuE2 Studio** is a self-hosted, offline web application for generating music
with the [YuE2](https://github.com/multimodal-art-projection/YuE2) foundation
model. It runs two Docker containers — a lightweight **app** (FastAPI + static
JS) and a GPU-heavy **engine** (ComfyUI) — and requires no API keys, accounts,
or cloud services.

**Current version:** `0.0.4` (see `VERSION`).  
**License:** Apache 2.0 for the studio code; model weights carry their own
licenses (see `THIRD_PARTY_NOTICES.md`).

### Core Capabilities

| Feature | How it works |
|---|---|
| **Cover a recording** | Upload audio → transcribe melody & chords with SheetSage2 → edit score → render covers |
| **Song from a prompt** | Style + lyrics → YuE2 plans an ABC score → edit/reroll → render audio |
| **Instrumentals** | YuE2 + instrumental LoRA; three structure modes (free / sections / timed sections) |
| **Harmony Slider** | 5 presets (*Familiar → Outside*) that steer chord diversity via a custom ComfyUI node |
| **Interpretations** | 6 performance styles (*Standard, Tight, Loose, Settled, Restless, Wide*) controlling sampler params |
| **Variations** | Batch-render the same score+seed across multiple interpretations for ear comparison |
| **Write Lyrics** | Gemma 4 E4B drafts structured lyrics from a brief |
| **Stems Extraction** | Demucs on CPU splits tracks into vocals/drums/bass/other (optionally guitar/piano) |
| **Production Polish (Realaudio)** | Mothersuperior v9 real-audio decoder LoRA applied during render for studio separation & clarity |
| **Realaudio Tokenizer & Identity** | MERT-v2 (layer 20 @ 25 Hz) + Transformer head extracts identity tokens for voice conditioning |
| **Spaces & Library** | Organise takes into workspaces; waveform player, starred takes, compact/comfy layouts |
| **Score Editor** | Full-screen editor with chord find-and-replace, chart view, lyrics-with-chords, staff notation via abcjs |

---

## 2. Architecture Overview

```
┌──────────────────────────────────────────────┐
│            Browser (vanilla JS SPA)          │
│         app.js  ·  index.html  ·  abcjs     │
└───────────────────┬──────────────────────────┘
         HTTP REST / polling (no WebSocket to browser)
                    │
┌───────────────────┴──────────────────────────┐
│     App Container  (Python 3.13, :8090)      │
│  FastAPI  ·  SQLite  ·  Demucs (CPU)         │
│  Manages library, drives the engine, stems   │
└───────────────────┬──────────────────────────┘
        HTTP + WebSocket to ComfyUI
                    │
┌───────────────────┴──────────────────────────┐
│    Engine Container  (ComfyUI, :8188)        │
│  CUDA 12.8  ·  PyTorch 2.9  ·  headless     │
│  YuE2 · SheetSage2 · Gemma · LoRAs          │
│  Custom node: yue2_harmony                   │
└──────────────────────────────────────────────┘
              NVIDIA GPU (≥12 GB VRAM)
```

**Key architectural decisions:**
- The app never touches the GPU directly. All ML work goes through ComfyUI's
  HTTP/WebSocket API.
- Demucs runs on CPU inside the app container to avoid fighting YuE2 for VRAM.
- The frontend is intentionally build-free vanilla JS — no framework, no
  bundler, no node_modules.
- SQLite (WAL mode) is the only database. No external services.

---

## 3. Repository Layout

```
.
├── app/                    Python package: FastAPI backend + static frontend
│   ├── __init__.py
│   ├── config.py           Environment variables, paths, model names, timeouts
│   ├── db.py               SQLite: connections, schema, 6 numbered migrations, settings cache
│   ├── engine.py           ComfyUI HTTP/WS client, templates, progress tracking
│   ├── instrumental.py     Instrumental structure parsing, LoRA graph injection
│   ├── jobs.py             Dual-lane job queue (GPU + CPU), worker loops, keeper
│   ├── library.py          File naming, sidecars (take.json), duration, waveform peaks
│   ├── lyrics.py           Gemma prompt construction, response parsing
│   ├── main.py             FastAPI app: all HTTP routes, middleware, lifecycle
│   ├── score.py            ABC notation validation (key, bars, chords)
│   ├── stems.py            Demucs subprocess runner, progress parsing
│   ├── static/
│   │   ├── index.html      Single HTML page (~20 KB)
│   │   ├── app.js          Client-side SPA (~3,000 lines vanilla JS)
│   │   ├── styles.css      Dark-theme CSS with custom properties (~620 lines)
│   │   ├── abcjs-basic-min.js   Vendored ABC notation renderer (MIT)
│   │   └── abcjs.LICENSE.md
│   └── templates/
│       ├── render.json     ComfyUI graph: score → audio
│       ├── song_plan.json  ComfyUI graph: lyrics → ABC score
│       └── transcribe.json ComfyUI graph: audio → ABC score
├── engine/                 GPU engine container
│   ├── Dockerfile          ComfyUI + CUDA 12.8 + PyTorch 2.9, pin COMFYUI_REF=36da3ff7
│   └── custom_nodes/
│       └── yue2_harmony/
│           └── __init__.py Custom node: chord-aware logit steering (~280 lines)
├── tests/                  14 pytest modules, 100% offline (fake engine)
│   ├── conftest.py         Fixtures: temp data dir, TestClient, make_take(), tone()
│   ├── test_api.py         HTTP routes, security (Host/CSRF), uploads, ETags
│   ├── test_db.py          Schema migrations, legacy upgrades, settings cache
│   ├── test_graphs.py      ComfyUI graph construction and output extraction
│   ├── test_harmony.py     Harmony slider mapping and API boundaries
│   ├── test_harmony_node.py  Engine custom node logic (stubbed ComfyUI imports)
│   ├── test_instrumental.py  Instrumental structure, LoRA injection, feel param
│   ├── test_jobs.py        Full job lifecycle with FakeEngine
│   ├── test_library.py     slugify, paths, duration, peaks
│   ├── test_queue.py       Queue display and job classification
│   ├── test_release_features.py  Interpretations, variations, lyrics
│   ├── test_score.py       ABC validation and corrupt plan rejection
│   ├── test_spaces.py      Space CRUD, move, delete-reassign
│   └── test_stems.py       Demucs progress bar parsing
├── scripts/
│   └── fetch-models.sh     Downloads ~17.5 GB of model weights from HuggingFace
├── tools/
│   ├── git-hooks/pre-push  Blocks PDF audit files from reaching GitHub
│   └── ui-harness.mjs      Headless Node.js integration test running real app.js
├── docs/screenshots/       README imagery (compact, cover, song views + full-res)
├── data/                   Runtime: SQLite DB, takes, sources, stems (gitignored)
├── models/                 Downloaded weights (gitignored, ~17.5 GB)
├── engine-state/           ComfyUI runtime dirs: input, output, user (gitignored)
├── Dockerfile              App container: Python 3.13 + CPU PyTorch + Demucs
├── compose.yml             Single-machine GPU setup (app + engine)
├── compose.split.yml       Split topology: app on NAS, engine on GPU box
├── requirements.txt        fastapi, uvicorn, httpx, websockets, python-multipart, numpy
├── requirements-dev.txt    + pytest
├── eslint.config.mjs       Flat ESLint v9 config for app.js (strict scoping rules)
├── VERSION                 "0.0.3" — read by Dockerfile, shown in UI header
├── CHANGELOG.md            Release protocol + notes for 0.0.1 → 0.0.3
├── LICENSE                 Apache 2.0
├── THIRD_PARTY_NOTICES.md  Licenses for YuE2, SheetSage2, Gemma, Demucs, etc.
└── README.md               Full operational guide
```

---

## 4. Data Model (SQLite)

The database lives at `data/yue2.sqlite` (WAL mode). Schema is in `app/db.py`,
managed by 6 numbered migrations (append-only, idempotent).

### Tables

**`sources`** — Uploaded reference audio for covers and transcription.

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | 12-char hex |
| `title` | TEXT | |
| `filename` | TEXT | Original upload name |
| `stored_path` | TEXT | On-disk path: `sources/<hash>-<slug>.<ext>` |
| `engine_file` | TEXT | Filename inside ComfyUI's input folder (set at transcribe time) |
| `sha256` | TEXT | Upload deduplication |
| `abc` | TEXT | Transcribed ABC score (SheetSage2 output) |
| `transcribe_state` | TEXT | `none` → `queued` → `running` → `done`/`failed` |

**`takes`** — Every planned or rendered piece of music.

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | 12-char hex |
| `kind` | TEXT | `cover`, `song`, `instrumental` |
| `source_id` | TEXT | FK → sources (null for songs/instrumentals) |
| `title` | TEXT | |
| `style` | TEXT | Style prompt |
| `lyrics` | TEXT | Lyrics (songs/covers) or structure text (instrumentals) |
| `abc` | TEXT | ABC notation score plan |
| `mode` | TEXT | `full` or `melody` |
| `seed` | INTEGER | Reproducibility seed |
| `checkpoint` | TEXT | Model checkpoint name |
| `max_duration` | REAL | Seconds (10–900) |
| `status` | TEXT | `queued` → `running` → `planned`/`done`/`failed` |
| `audio_path` | TEXT | Path to rendered FLAC |
| `auto_render` | INTEGER | If 1, render immediately after planning |
| `variety` | TEXT | `calm`, `normal`, `bold`, `wild` — plan sampler aggression |
| `harmony` | INTEGER | 0–4 — Harmony slider position |
| `space_id` | TEXT | FK → spaces |
| `interpretation` | TEXT | `standard`, `tight`, `loose`, `settled`, `restless`, `wide` |
| `feel` | TEXT | `steady` or `varied` — instrumental LoRA strength |
| `realaudio` | INTEGER | `0` or `1` — apply Mothersuperior v9 real-audio decoder LoRA |

**`spaces`** — Organisation folders. Default space (`id="default"`) cannot be deleted.

**`settings`** — Key-value store with in-memory cache. Keys include `stems.format`,
`stems.model`, `stems.folder`, `avg_render_seconds`, etc.

**`stem_sets`** — Demucs stem separation jobs. Tracks model, wanted stems,
format, progress (0.0–1.0), output folder path.

### Migration History

| # | What it does |
|---|---|
| 1 | Base schema + legacy take table upgrade (adds `kind`, nullable `source_id`) |
| 2 | Indexes on takes, sources, stem_sets |
| 3 | `takes.harmony` column |
| 4 | `spaces` table + `takes.space_id` column + default space |
| 5 | `takes.interpretation` column |
| 6 | `takes.feel` column |
| 7 | `takes.realaudio` column |

---

## 5. Backend Module Guide

### `config.py`
Environment variables, read once at import. Key settings:

| Variable | Default | Purpose |
|---|---|---|
| `ENGINE_URL` | `http://127.0.0.1:8188` | ComfyUI endpoint |
| `DATA_DIR` | `/data` | Database, takes, stems, sources, tmp |
| `ENGINE_OUTPUT_DIR` | (unset) | Mounted engine output for direct file cleanup |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1,::1` | DNS rebinding protection |
| `MAX_UPLOAD_MB` | `300` | Upload size limit |
| `CHECKPOINT` | `yue2_3b_bf16.safetensors` | The one checkpoint used |
| `LYRICS_MODEL` | `gemma4_e4b_it_int8_convrot.safetensors` | Gemma for lyrics |
| `INSTRUMENTAL_LORA` | `ar_lora_inst_v3abc_comfyui.safetensors` | Instrumental adapter |

### `engine.py` — ComfyUI Client
- `Engine` class manages httpx client + WebSocket connection.
- Unique `client_id` per process (`yue2-studio-<hex>`).
- Loads graph templates from `app/templates/` (deep-copied per job).
- WebSocket loop tracks `execution_start`, `executing`, `progress` events.
- Progress is normalised to 0.0–1.0 using per-node weights (`STAGE_WEIGHT`).
- `refresh_options()` reads `/object_info` to detect available nodes, models, and LoRAs.
- Compatibility check: verifies every node used in templates exists on the engine.

### `jobs.py` — Dual-Lane Job System
Two `asyncio.Queue` instances process jobs serially within their lane:

| Lane | Queue | Worker | Jobs |
|---|---|---|---|
| GPU | `QUEUE` | `worker()` | `lyrics`, `transcribe`, `plan`, `render` |
| CPU | `STEM_QUEUE` | `stems_worker()` | Demucs separation |

Key flows:
- **Plan:** `build_plan_graph()` → submit to engine → poll `history()` →
  validate ABC with `score.problems()` → if valid, store; if `auto_render`, queue render.
- **Render:** `build_render_graph()` → submit → poll → download FLAC → compute
  duration and peaks → write `take.json` sidecar → clean up engine output copy.
- **Transcribe:** Upload source audio to engine → `build_transcribe_graph()` →
  submit → extract ABC text.
- **Lyrics:** `build_lyrics_graph()` → Gemma generates text → `lyrics.parse()`.

The `keeper()` loop polls engine status every 2 seconds and refreshes
capabilities every 5 minutes.

`CANCELLED: set[str]` tracks jobs the user has cancelled. The worker checks it
at each poll iteration and aborts cleanly.

### `main.py` — HTTP API
~1200 lines. Lifecycle on startup: run migrations → clean scratch dir → mark
interrupted jobs as failed → requeue waiting jobs → start engine client →
launch worker, stems_worker, keeper.

**Security middleware (`guard`):**
- Host-header validation (DNS rebinding protection)
- Origin and Sec-Fetch-Site checking (CSRF prevention)
- Upload size enforcement
- `Cache-Control: no-cache` on page and static assets

### `score.py` — ABC Validation
`problems(abc)` returns a list of issues: no key signature, no vocal part,
too few bars, no chord symbols. Used to reject garbled plan outputs before
they can proceed to rendering.

### `stems.py` — Demucs Runner
Runs `demucs` as a subprocess. Parses percentage patterns from stdout for
progress. Supports `htdemucs` (4 stems, 1 pass), `htdemucs_ft` (4 stems,
4-pass ensemble), `htdemucs_6s` (6 stems including guitar and piano).

### `library.py` — File Organisation
- `slugify()` for human-readable folder/file names.
- Takes: `data/takes/<title>-<id>/<title>.flac` + `.peaks.json` + `take.json`.
- Sources: `data/sources/<hash[:16]>-<slug>.<ext>`.
- `relayout()` runs on every start, renaming files to match current titles.
- `compute_peaks()`: ffmpeg → 8 kHz mono → numpy → 1024-column peak/RMS JSON.

### `instrumental.py`
Parses and validates instrumental structure text. Three forms:
- `[instrumental]` (model decides)
- `[intro] [verse] [chorus] ...` (sections, model decides lengths)
- `[intro 0:00-0:15] [verse 0:15-0:45] ...` (timed sections)

`with_lora()` injects a `LoraLoader` node into any ComfyUI graph between the
checkpoint and the text-conditioning nodes, with model strength 0 and clip
strength configurable (1.0 for "steady", 0.8 for "varied").

### `lyrics.py`
Builds a structured prompt for Gemma. `parse()` extracts `[Verse]`/`[Chorus]`
sections from the LLM output, stripping markdown artifacts and preamble.

---

## 6. The Engine Custom Node: `yue2_harmony`

**Location:** `engine/custom_nodes/yue2_harmony/__init__.py` (~280 lines)

**Problem it solves:** YuE2's text planner tends to get stuck in repetitive
4-chord loops. Standard LM repetition penalties break ABC syntax (they
penalise bar lines, voice headers, note durations) before they break chord
loops.

**How it works:**
1. `HarmonyTracker` reads the token stream during ABC generation.
2. It parses chord symbols from quoted ABC text (`"Cmaj7"`, `"G"`, etc.),
   ignoring quotes in header lines (`V: Vocal name="Vocal"`).
3. It builds a sliding window of recent chord changes.
4. For each candidate token, it computes a logit penalty or bonus:
   - **Spelling mode:** Penalises recently used exact chord spellings.
   - **Root mode:** Groups all spellings of a pitch class (C, Cmaj7, C/E → all
     pitch class 0) and penalises recent roots.
   - **Hold limit:** Linear penalty ramp when a single root sustains too long.
   - **Outside bonus:** Rewards moving to roots outside the diatonic key
     (stopped when outside chords exceed `outside_limit` of recent history).
5. `steering()` context manager monkey-patches `comfy.text_encoders.yue2.distribution`
   to subtract penalties from logits during the `"abc"` phase.

**App-side mapping (5 Harmony presets in `jobs.py`):**

| Step | Name | Mode | Strength | Outside Bonus |
|---|---|---|---|---|
| 0 | Familiar | (off) | 0.0 | 0.0 |
| 1 | Varied | spelling | 8.0 | 0.0 |
| 2 | Colourful | spelling | 16.0 | 0.0 |
| 3 | Adventurous | root | 32.0 | 0.0 |
| 4 | Outside | root | 32.0 | 3.0 |

---

## 7. ComfyUI Workflow Graphs

Three JSON templates in `app/templates/` define the execution graphs submitted
to the engine. The app deep-copies a template, fills in parameters, and POSTs
it to `/prompt`.

### `song_plan.json` (Score Planning)
```
CheckpointLoaderSimple(1) → YuE2GenerateABC(2) → PreviewAny(3)
```
Node 2 receives: style, lyrics, seed, temperature, repetition_penalty.
If harmony > 0, the class_type of node 2 is swapped to `YuE2GenerateABCHarmony`
and chord steering params are added.
For instrumentals, a `LoraLoader(20)` is injected between nodes 1 and 2.

### `render.json` (Audio Rendering)
```
CheckpointLoaderSimple(10) → YuE2GenerateMusic(11) → EmptyYuE2LatentAudio(12)
                           → ConditioningZeroOut(13) → KSampler(14)
                           → VAEDecodeAudio(15) → SaveAudioAdvanced(16)
```
KSampler: `dpm_2`, `sgm_uniform`, 32 steps, CFG 1.0. Output: 44.1 kHz FLAC.

### `transcribe.json` (Audio → ABC Score)
```
LoadAudio(1) → AudioEncoderLoader(2) → SheetSage2AudioToABC(3) → PreviewAny(4)
```

### Lyrics (built dynamically, not from template)
```
CLIPLoader(1) → TextGenerate(2) → PreviewAny(3)
```

---

## 8. Frontend Architecture

**Stack:** Vanilla JavaScript (strict mode), no framework, no build step.

**Entry point:** `app/static/index.html` — served by FastAPI at `/`.

### State Management
A single global `State` object holds all client state:
```javascript
var State = {
  sources: [], takes: [], options: {}, filter: 'all', playing: null,
  busy: false, mode: 'cover', planTakeId: null, layout: 'compact',
  editorTakeId: null, editorSourceId: null, leftTakeId: null,
  spaces: [], spaceId: 'default', draft: null, ...
};
```

UI updates are imperative: dedicated `paint*()` functions re-render specific
DOM regions. Fine-grained: elements are only mutated when their serialized
HTML has actually changed.

### Polling Architecture
- **Every 2s:** `pollState()` → `GET /api/state` (engine health, GPU VRAM, active
  job progress, queue).
- **Every 3–6s:** `loadTakes()` → `GET /api/takes` (3s when jobs active, 6s idle).
  Uses ETag/If-None-Match for bandwidth; skips DOM repaint when payload matches.
- **Tab visibility:** `visibilitychange` listener triggers immediate refresh.

### Form Persistence
All form inputs auto-save to `localStorage` (`yue2.form.v1`). Working score
text persists across reloads with restore/dismiss notification.

### Waveform Visualiser
Canvas-based: draws peak outline (transients) and RMS body (loudness) from the
server-computed `.peaks.json`. Pointer-event seeking with `setPointerCapture`.

### Score Editor
Full-screen modal with three views: Chart (chord grid), Notation (abcjs SVG),
Lyrics (chord annotations inline). Undo/redo stack (120-item limit). Chord
find-and-replace across the whole score.

### Audio Player
HTML5 `<audio>` element with MediaSession API integration (hardware media keys,
lock screen metadata). Previous/next navigation across playable takes.

---

## 9. API Reference

### Sources (uploaded audio)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/sources` | List all sources |
| `POST` | `/api/sources` | Upload audio (multipart, ≤300 MB) |
| `GET` | `/api/sources/{id}` | Get source details |
| `DELETE` | `/api/sources/{id}` | Delete source + stems |
| `POST` | `/api/sources/{id}/transcribe` | Queue SheetSage2 transcription |
| `PUT` | `/api/sources/{id}/score` | Save/edit transcribed ABC |
| `GET` | `/api/sources/{id}/audio` | Stream source audio |
| `POST` | `/api/sources/{id}/stems` | Queue Demucs separation |

### Takes (generated music)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/takes` | List takes (ETag, filters: source_id, space_id, favourite) |
| `POST` | `/api/takes` | Queue a render from a source |
| `POST` | `/api/songs` | Queue a new song plan from lyrics |
| `POST` | `/api/instrumentals` | Queue a new instrumental plan |
| `GET` | `/api/takes/{id}` | Get take details |
| `DELETE` | `/api/takes/{id}` | Cancel + delete |
| `POST` | `/api/takes/{id}/render` | Re-render with optional interpretation |
| `POST` | `/api/takes/{id}/replan` | New score plan (new seed, optional variety/harmony) |
| `POST` | `/api/takes/{id}/variations` | Batch-create takes for multiple interpretations |
| `POST` | `/api/takes/{id}/cancel` | Cancel queued/running job |
| `POST` | `/api/takes/{id}/clear` | Clear failure → recover planned/done state |
| `PUT` | `/api/takes/{id}/score` | Save edited ABC |
| `POST` | `/api/takes/{id}/move` | Move to another space |
| `POST` | `/api/takes/{id}/favourite` | Toggle star |
| `GET` | `/api/takes/{id}/audio` | Stream FLAC |
| `GET` | `/api/takes/{id}/peaks` | Waveform data (1024-column JSON) |
| `POST` | `/api/takes/{id}/stems` | Queue Demucs separation |

### Lyrics

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/lyrics` | Queue lyric draft (Gemma 4 E4B) |
| `GET` | `/api/lyrics/{id}` | Poll draft status |
| `POST` | `/api/lyrics/{id}/cancel` | Cancel draft |

### Spaces, Settings, Stems, Engine

| Method | Path | Purpose |
|---|---|---|
| `GET/POST/PUT/DELETE` | `/api/spaces[/{id}]` | CRUD for spaces |
| `GET/PUT` | `/api/settings` | App settings |
| `GET` | `/api/stems/options` | Demucs models, formats, defaults |
| `GET/POST/DELETE` | `/api/stem-sets[/{id}]` | Stem set CRUD |
| `GET` | `/api/stem-sets/{id}/zip` | Download all stems as ZIP |
| `GET` | `/api/stem-sets/{id}/{name}` | Stream individual stem |
| `GET` | `/api/state` | Full app+engine state for page poll |
| `GET` | `/api/health` | Healthcheck |
| `POST` | `/api/jobs/current/cancel` | Cancel active GPU job |
| `POST` | `/api/engine/interrupt` | Global engine interrupt |

---

## 10. Model Weights

Downloaded by `scripts/fetch-models.sh` (~17.5 GB total). Mounted into the
engine container at `/app/models`.

| Path | Size | Purpose |
|---|---|---|
| `checkpoints/yue2_3b_bf16.safetensors` | 7.8 GB | Main YuE2 model (plans + renders) |
| `audio_encoders/sheetsage2_bf16.safetensors` | 1.4 GB | SheetSage2 transcription |
| `text_encoders/gemma4_e4b_it_int8_convrot.safetensors` | 8.1 GB | Gemma 4 E4B (lyrics) |
| `loras/ar_lora_inst_v3abc_comfyui.safetensors` | 0.2 GB | Instrumental LoRA |
| `loras/nar_lora_joint_v9_comfyui.safetensors` | 0.1 GB | Realaudio Production Add-on LoRA |
| `audio_encoders/tokenizer_head_joint_v9.safetensors` | 0.17 GB | Realaudio Tokenizer Head |

Additional weights in the repo:
- `checkpoints/yue2_3b_int8_convrot.safetensors` — Quantised checkpoint (unused by app)
- `loras/paulshields_step100.safetensors`, `paulshields_step250.safetensors` — Custom voice LoRAs

---

## 11. Docker & Deployment

### Single Machine (`compose.yml`)
```bash
scripts/fetch-models.sh      # download weights
docker compose up -d --build  # start both containers
# → app on http://localhost:8090, engine on 127.0.0.1:8189
```
- Engine reserves all NVIDIA GPUs.
- App runs as `user: 1000:1000` to own data files.
- `data/` and `engine-state/` are bind-mounted.

### Split Topology (`compose.split.yml`)
App on a NAS, engine on a separate GPU machine. App container uses
`network_mode: host`, hardened security (read-only FS, all caps dropped,
no-new-privileges, 2 GB memory limit, 64 MB tmpfs on `/tmp`).

### App Dockerfile
- Base: `python:3.13-slim`
- Installs CPU-only PyTorch 2.9 + Demucs 4.1.0 (GPU preserved for engine)
- Healthcheck: `GET /api/health` every 30s
- Entrypoint: `uvicorn app.main:app --host 0.0.0.0 --port 8090`

### Engine Dockerfile
- Base: `python:3.12-slim`
- Clones ComfyUI at commit `36da3ff7` (native YuE2 support)
- Installs PyTorch 2.9 + CUDA 12.8 wheels
- Copies `custom_nodes/yue2_harmony` in late for fast rebuilds
- Models bind-mounted (not baked into image)
- Entrypoint: `python main.py --listen 0.0.0.0 --port 8188`

---

## 12. Testing

**Run tests:**
```bash
pip install -r requirements-dev.txt
pytest tests/
```

Tests are 100% offline — `conftest.py` points `ENGINE_URL` at a closed port
(`127.0.0.1:9`) to verify offline handling. `test_jobs.py` uses a `FakeEngine`
that simulates ComfyUI responses.

### Test Coverage Map

| Module | Tests |
|---|---|
| HTTP routes + security | `test_api.py` (host validation, CSRF, uploads, ETags, cancellation) |
| Database migrations | `test_db.py` (fresh + legacy upgrade, indexes, settings) |
| ComfyUI graph building | `test_graphs.py` (template copies, param propagation, output extraction) |
| Harmony slider | `test_harmony.py` (preset mapping, API boundaries, engine check) |
| Harmony node algorithm | `test_harmony_node.py` (spelling vs root mode, hold limits, outside bonus) |
| Instrumental mode | `test_instrumental.py` (structure parsing, LoRA injection, feel param) |
| Job lifecycle | `test_jobs.py` (plan, render, transcribe, timeout, cancellation, race conditions) |
| File library | `test_library.py` (slugify, paths, duration, peaks) |
| Queue display | `test_queue.py` (job classification, mine vs outside, elapsed times) |
| Feature releases | `test_release_features.py` (interpretations, variations, lyrics) |
| ABC validation | `test_score.py` (key, bars, chords, corrupt plan rejection) |
| Spaces | `test_spaces.py` (CRUD, move, delete-reassign) |
| Demucs progress | `test_stems.py` (multi-pass progress parsing) |

---

## 13. Development Conventions

### Release Process (from CHANGELOG.md)
1. Bump `VERSION`.
2. Add entry to `CHANGELOG.md`.
3. Tag the commit on `master`.
4. Push to internal `origin` (homer server).
5. Optionally push to `github` remote with `gh release create`.

### Git Hooks
`tools/git-hooks/pre-push` blocks top-level PDF files from being pushed to
GitHub (prevents accidental leak of audit documents).

Configure: `git config core.hooksPath tools/git-hooks`

### Code Style
- Python: no formatter enforced, but consistent use of `__future__ annotations`,
  type hints, and docstrings.
- JavaScript: ESLint v9 with strict scoping rules (`no-redeclare`, `no-shadow`,
  `no-undef`, `block-scoped-var`). ECMAScript 2020 script mode.
- CSS: vanilla with custom properties for theming.

### Environment for Development
- Backend: `pip install -r requirements-dev.txt`, run with
  `uvicorn app.main:app --host 0.0.0.0 --port 8090 --reload`.
- Frontend: edit files directly, refresh browser.
- Engine: `docker compose up -d engine` (needs GPU).

---

## 14. Known Gotchas

1. **All takes are sequential.** The GPU queue processes one job at a time.
   Stems run in parallel on CPU.

2. **Lyrics are in-memory only.** `LYRICS` dict is not persisted to SQLite.
   An app restart loses uncopied drafts. This is intentional: the draft is
   copied into the form as soon as it lands.

3. **The engine can be shared.** ComfyUI serves multiple clients. The app
   identifies its own jobs by `client_id` prefix `yue2-studio-`. Jobs from
   other clients show up as "outside" in the queue view.

4. **File ownership matters.** The app container runs as `1000:1000`.
   `scripts/fetch-models.sh` creates `data/` and `engine-state/output/` as
   the current user to prevent Docker creating them as root.

5. **Score validation gates rendering.** `score.problems()` catches garbled
   plans (no key, no vocal part, < 4 bars). A corrupt plan is stored as a
   failure and cannot proceed to render.

6. **The harmony node is optional.** If the engine lacks `YuE2GenerateABCHarmony`,
   harmony must stay at "Familiar" (step 0). The stock `YuE2GenerateABC` is
   used instead.

7. **Windows / WSL2:** The repo must be cloned inside the WSL filesystem
   (not `/mnt/c/`). `.gitattributes` enforces LF line endings to prevent
   `$'\r': command not found` errors in container scripts.

8. **Model download is ~17.5 GB.** `fetch-models.sh` is idempotent and
   resumes interrupted downloads.

9. **take.json sidecars** are written alongside each FLAC so a folder copied
   out of the library is self-documenting.

10. **Engine output cleanup:** When `ENGINE_OUTPUT_DIR` is mounted, the app
    deletes the engine's copy of each render after downloading its own. This
    prevents the engine's output folder from growing unboundedly.

---

## 15. Quick Command Reference

```bash
# First-time setup
scripts/fetch-models.sh
docker compose up -d --build

# Run tests
pip install -r requirements-dev.txt
pytest tests/ -v

# Lint frontend
npx eslint

# Check engine compatibility
curl -s http://localhost:8189/object_info | python3 -c "import json,sys; print(list(json.load(sys.stdin).keys())[:20])"

# Backup user data
tar czf backup.tar.gz data/

# View logs
docker compose logs -f app
docker compose logs -f engine
```

---

*Generated 2026-09-20. Version 0.0.4.*
