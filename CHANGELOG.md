# Changelog

Versions are git tags on `master`. The number lives in `VERSION`, which is copied into the
app image and shown in the header, so a running container can be identified at a glance.

**Every deploy bumps `VERSION`; only a release gets a tag.** The number in the header says
which build is running, so it moves with each change deployed. A tag, an entry here and a push are
for a milestone worth naming, and are cut only when asked for — not for every update.

To deploy a change:

1. Merge to `master`, bump `VERSION`, redeploy.

To cut a release:

1. Add an entry here, newest first.
2. `git tag -a vX.Y.Z -m "..."`
3. `git push origin master --tags`   (homer only, unless GitHub is wanted)
4. For a public release: `git push github master --tags` and
   `gh release create vX.Y.Z --title vX.Y.Z --notes "..."`

Release notes live in two places and neither is a file in this repository: this changelog holds the
history, and each GitHub release holds its published notes. `RELEASE-NOTES-*.md` is ignored so it
cannot creep back in.

## 0.0.23 - 2026-09-23

- **Style LoRAs trained from your own songs (experimental, off by default).** Prepare a corpus from
  a folder of one artist's songs: the app separates each vocal, finds key, tempo and sections,
  drafts the lyrics and writes a caption per song. Export the set, or build the engine with
  `WITH_TRAINER=1` and the app with `TRAINING_ENABLED=1` to train a dual-branch LoRA from it here.
  Training follows the trainer's own recipe, with the number of steps set from the size of the
  corpus, and keeps a snapshot every 50 steps, named for its step, so one can be chosen by ear.
  **Install a LoRA** takes a file trained elsewhere. LoRAs made from a corpus share one group in
  the Style LoRA list, each named after its corpus.
- **Learned styles.** A LoRA made from a corpus offers one chip per song under the Style box, and
  each writes the caption that song was trained with, trigger word first.
- **Style LoRAs reach the render as well as the plan.** The Planner half now shapes the music a
  render writes from the score, not only the score. Strengths go to 3 and can be typed. Changing
  the LoRA swaps its trigger word in the Style, and the note under the picker says what the file
  holds and suggests strengths.
- **Lyrics heard by an external LLM.** With an external LLM that accepts audio, such as Gemini,
  Extract lyrics can have it hear the words while Whisper keeps the timing. A reply that is not
  the whole song falls back to Whisper, and the log says which method ran.
- **Whisper hears the whole vocal.** Its voice detector is off, since it discarded most singing, and
  text it invents over instrumental stretches is dropped. A recording's separated vocal is kept, so
  extracting its lyrics again skips the separation, and a recording that already has lyrics offers
  to extract them again.
- **Weak renders are flagged.** A take that comes out far quieter than usual all the way through
  usually sounds thin or distorted; its card says *Weak render: try another seed*.
- **Take cards always name Harmony, Interpretation and Plan**, defaults included.
- **Layout.** A width control beside the card size, and the takes keep their first row clear of the
  header. The new song button takes the colour of its mode.
- **Settings.** The external LLM key box starts empty and says whether a key is saved; a new key
  replaces it, and Remove clears it.
- **The guide** opens in its own tab and scrolls at desktop widths.

## 0.0.16 - 2026-09-23

- **Custom External LLM Provider Integration.** Users can now configure an external LLM provider
  (e.g. OpenAI, Anthropic, Google Gemini, Groq, OpenRouter, Ollama, LM Studio) in Settings to take
  over all text tasks from local Gemma:
  - **Lyric Generation:** Drafts structured, rhyming song lyrics with verses, choruses, and titles
    without needing `gemma4_e4b_it_int8_convrot.safetensors` on the engine.
  - **Corpus Musical Style Tagging:** Generates accurate, evocative comma-separated musical style
    tags (genres, instruments, drums, moods) from song title, artist, and lyrics metadata.
  - **VRAM & Performance Optimization:** Completely bypasses loading Gemma into GPU memory (~8 GB VRAM),
    freeing up GPU resources for faster audio generation and training.
  - **Comprehensive Action Logging:** Every LLM request, completion, token metric, configuration
    update, and connection test is logged directly to the centralized logging system and web UI
    with sensitive API keys securely masked.
  - **Connection Testing:** Includes a "Test LLM Connection" tool directly in Settings to instantly
    verify connectivity, latency, and model responsiveness.

## 0.0.8 - 2026-09-21

- **The takes scroll in their own pane.** The window no longer scrolls: the form and the takes each
  scroll inside themselves, so the top bar, the space picker, the filters and the player bar all stay
  where they are however long the library grows. Useful with the pick boxes: the Delete button and
  the count stay in view while you scroll. Above 1000px only; below that the columns stack and the
  page scrolls as it did.

## 0.0.7 - 2026-09-21

- **Lyrics from a recording.** A cover needs the words, and now the app can hear them: a **Lyrics**
  button beside Transcribe separates the vocal with Demucs, transcribes it with faster-whisper, and
  lays the lines under the sections the score already names. Measured against a known set of real
  lyrics: 10.7% of words wrong, and the errors are omissions rather than inventions. It is English
  only, and the tooltip says so. Runs in the CPU lane, so it never holds up a render.
- **Audition.** A button on the recording row plays the recording itself through the player at the
  foot of the page, with its waveform, so what is about to be covered can be heard without leaving
  the app. Starting a take ends it, and the space bar resumes the recording rather than a take.
- **One selection object.** `editorTakeId`, `editorSourceId`, `leftTakeId` and `planTakeId` said
  overlapping things about the left column and drifted apart three times, so a cover was rendered
  from another recording's score and a new plan was never shown. They are one `Selection` now, with
  one writer and helpers to read it. `tools/selection-harness.mjs` asserts the selection after each
  way of changing it: fourteen checks, offline, about a second.
- **A cover is rendered from its own recording's score, or none.** Choosing a recording whose score
  is not the one in the box empties the box, and a cover with no score anywhere is refused with the
  reason, rather than quietly rendering a melody the model invents.
- **demucs works in parallel.** It applies its segments one at a time unless given `-j`, which was
  never passed, so separation left most of the machine idle. Measured on a 3:45 recording: 89.2 s
  before, 62.6 s with four jobs. `STEMS_JOBS` scales with the machine, up to four.
- **A score that disagrees with its recording is called out.** Recordings now keep their length, and
  when the score's own bars and tempo describe more or less music than the recording holds, the page
  says so and names the tempo that would fit. The score editor gains a **Tempo** field, which writes
  `Q:1/4=` — honoured by the render within a couple of BPM, measured.
- **Takes can be picked and deleted in one go.** Every card carries a pick box under its icon, the
  filter row gains a Delete button that names the count, and one confirmation lists the takes before
  removing them.

## 0.0.6 - 2026-09-20

- **Style LoRAs.** Any `.safetensors` in `models/loras/` can be chosen for a take, with its own two
  strengths: **Planner**, which shapes the score plan, and **Sound**, which shapes the audio. The app
  reads each file to see which halves it holds, says so in the list, and greys out a strength the
  file cannot use.
- **The planner half is applied where the plan is written**, not only in the render, because a score
  plan is written in a run of its own. The same prompt and seed through one LoRA at planner 0 and 1
  gave 82 BPM and 85 lines of score against 72 BPM and 199.
- **A LoRA can carry its own description.** A `.txt` beside it names it on the first line and
  describes it below, shown in the picker and on hover, and `families.txt` gives the groups their
  headings. A line reading `Trigger: chnsn` is treated as more than text: choosing that LoRA puts the
  word at the front of the Style, changing to another swaps it, and a render puts it back if it was
  deleted, because a LoRA trained on captions that begin with its trigger does very little without it.
- **Identities gain a Planner strength.** An Identity's LoRA usually holds a planner half as well as
  a voice, and the app had always applied the voice alone. That half is now a control, off by
  default, so nothing rendered before this sounds different. Identity files are no longer offered in
  the style list: they belong to the Identity control, and one file is never applied twice.
- Takes record the LoRA and both strengths, cards name them, and clicking a take brings them back, so
  **Again** and Variations reproduce what was heard.
- The stem row shows its progress once, rather than twice.
- The player follows the sound, so a stem can be paused with the button or the space bar instead of
  starting the last take.
- The Windows notes name the step that was missing — WSL integration — and the model list names the
  Realaudio decoder LoRA and tokenizer head, which the fetch script has pulled since 0.0.4.
- API: the create endpoints take `style_lora`, `style_lora_model`, `style_lora_clip` and
  `voice_lora_clip`. The database gains those columns on the first start (migrations 13 and 14).
- `compose.yml` mounts `./models` into the app, read only, so it can read what a LoRA holds. Without
  it the picker still works from the engine's list.

## 0.0.5 - 2026-09-20

- **Instrumentals that sang are caught.** The model occasionally puts a voice into an instrumental. A
  finished one is now checked for singing before it is called done, and a take that came out sung says
  so on its card and offers the two things that help: the same score with a new seed, or a new plan.
- **Feel is gone.** It loosened the instrumental LoRA for more movement between sections, and measured
  at real song lengths any loosening let the vocal back in. Instrumentals always render at full
  strength; movement is still available through Plan variety, Harmony and Interpretation. Takes made
  with it keep their setting and render like any other.
- **A plan that would sing warns first.** An instrumental whose score plan puts a melody in the vocal
  part is not rendered automatically; the card says why, and offers a new plan or the render anyway.
- **Settings: Vocal check on instrumentals.** Quick keeps the separator in memory, Thrifty loads it
  for each check and holds nothing, Off does not check.
- **Take cards read as the recipe that made them**: Harmony, Interpretation and Plan variety are named
  and come first, each shown only when it was not the default.
- Cards keep their tiles on one row in the compact layout, whether starred or not.
- Space and the arrow keys no longer reach the player through a window that is open in front.
- A long lyric brief in the render queue is cut at a word and ends in an ellipsis, so it is clear the
  display was shortened and not the prompt.
- The job card and the lyrics window no longer quote fixed times.
- Unix line endings are enforced through `.gitattributes`, and the README has a section on running the
  app on Windows with Docker Desktop.
- API: `POST /api/takes/{id}/render` takes `reseed`. The database gains `takes.vocal_check` on the
  first start (migration 12).

## 0.0.4 - 2026-09-20

- **Vocal Identities**: Create and manage custom vocal identities to maintain a consistent singing voice across takes. Point to a folder of reference recordings (own voice or with explicit consent) to isolate vocal stems, detect key and tempo with SheetSage, and generate section-tagged lyric drafts with Whisper. Export structured datasets ready for voice model training.
- **Voice LoRA Conditioning**: Attach trained vocal identity LoRAs directly during render, with automatic trigger word insertion and checkpoint selection (Best or individual step snapshots).
- **Production Polish (Realaudio)**: Integrated Mothersuperior v9 real-audio decoder LoRA into the render pipeline to eliminate boxy mid-range haze, enhance bass and drum punch, and provide studio-grade frequency separation with upfront lead vocals.
- **Realaudio Tokenizer**: Added pipeline utility to extract 25 Hz discrete semantic tokens from vocal recordings using MERT-v2 and a transformer head for voice conditioning and modeling.
- **Database & API**: Added `/api/identities` management endpoints, database schema migration for identities and identity songs, and `identity_id` tracking across takes and renders.

## 0.0.3 - 2026-09-19

- **Instrumental**, a third mode beside Cover and Song. Style and structure in, a piece with no
  vocal out, using the YuE2 instrumental LoRA. The structure is built in the panel: let YuE2 decide,
  choose the sections, or choose the sections and time each one. **Sent to YuE2** shows exactly
  what the model receives.
- **Feel** in Instrumental mode: Steady (the LoRA at full strength, repetitive and laid-back) or
  Varied (a little looser, with more movement between sections). The take keeps its feel.
- Instrumentals get the score plan, Harmony, Plan variety, Interpretation, Variations, the chord
  chart and the length cap, like songs. Their takes are green, and clicking one loads its structure
  back into the builder. The lyrics box is left alone.
- The mode switch reads Cover, Song and Instrumental.
- `scripts/fetch-models.sh` also fetches the LoRA into `models/loras/`.
- API: `POST /api/instrumentals`. An instrumental take has `kind` `instrumental`, its structure
  in `lyrics`, and its `feel`.
- The database gains `takes.feel` on the first start (migration 6).
- **Licensing.** The code is now licensed under Apache 2.0 (`LICENSE`), and
  `THIRD_PARTY_NOTICES.md` lists each model and program the app runs, with its licence and a link to
  the publisher's own terms. The README has a short License section.

## 0.0.2 - 2026-09-19

- **Write lyrics.** In *Song from a prompt*, say what the song is about and pick a structure. Gemma 4
  E4B writes a draft on the engine, and it lands in the lyrics box, with a title
  if the title was empty.
- **Interpretation.** Six ways to render the same score, under *Advanced*, for covers and songs:
  Standard, Tight, Loose, Settled, Restless and Wide. The take keeps its interpretation and the card
  names it.
- **Variations.** The sparkle button on a card renders the same score and seed in the other
  interpretations you tick. Each lands as a new take, titled with its interpretation.
- **One checkpoint.** The app uses `yue2_3b_bf16.safetensors` for every plan and render, and the
  checkpoint choice is gone.
- `scripts/fetch-models.sh` fetches the bf16 checkpoint, SheetSage2 and Gemma 4 E4B, about 17 GB.
- The database gains `takes.interpretation` on the first start (migration 5).
- API: `POST /api/lyrics`, `GET /api/lyrics/{id}`, `POST /api/lyrics/{id}/cancel`,
  `POST /api/takes/{id}/variations`, and `interpretation` on songs, covers and renders.

## 0.0.1 - 2026-09-19

Initial release.
