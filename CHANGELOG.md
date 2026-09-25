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

## 0.0.36 - 2026-09-25

Mostly usability: the corpus window says what it is doing at each step, and the page
takes less room.

### What's new

- **Training again keeps the last LoRA, or deletes it, as you choose.** The Train window asks
  when a corpus already has one. Kept, it is renamed with the day it was trained, for example
  "My corpus · 25 Sep (previous)", with its checkpoints, in a **Previous runs** group, so the new
  run's checkpoints are only its own.
- **The corpus window shows progress for every step:** analysing, exporting and training, each
  with a green line under the buttons. The corpus badge at the top of the page pulses while its
  LoRA trains.
- **Training runs at least 500 steps.** Ten passes over each song gave a small corpus too few
  steps to learn from. The checkpoints are kept, so a run that goes too far can be heard back to
  an earlier step.
- **Environment variables are documented in the README**, the training ones included, with
  `compose.override.yml.example` to copy, and how to set them on the Windows install.
- **The header is one row:** status, corpus, version and Logs sit level with the name.
- **Re-analyse** on a corpus song's review is a bright green button.
- **After an export,** songs using their lyric drafts are counted in a quiet note rather than
  listed in red.

### Fixed

- **Some songs could not be transcribed at all:** the transcriber refused a whole song when a
  note was still sounding as the file ended, such as a long held final chord. What it is sent
  now always ends with a short fade and silence, for covers as well as corpus songs, and a
  corpus song that still fails is tried melody-only, then on its first four minutes.
- **Style analysis took the corpus name for the artist,** so a corpus could have songs described
  in the wrong genre. The LLM is now sent only the song's title and words.
- **Engine errors in the corpus window were unreadable,** showing the audio as a stream of
  numbers. They now name the step and what went wrong.

## 0.0.35 - 2026-09-25

### What's new

- **Checkpoints: hear each training step of a LoRA side by side.** Beside **Delete LoRA**, it
  renders what the panel would make once on each checkpoint a training run kept, all with one
  seed, each take named after its step. Each weighting has its own taste while keeping the style
  the LoRA was trained on. Greyed out for a LoRA without checkpoints.
- **A logo.** One line forking in two, as YuE2 writes a plan and then sings it. It is in the
  header, the browser tab, the Windows shortcuts and the installer.
- **The Windows installer knows an update from a first install.** It says which version it is
  updating from, skips the folder page, and downloads only what has changed. Gemma 4 is offered
  as you chose it last time: already installed and not downloaded again, or left out.
  `YuE2Studio-Setup-0.0.35.exe` is attached to this release.
- **Uninstalling on Windows asks two things.** Keep your library (songs, takes, corpora and
  LoRAs)? Yes unless you say no. Keep the downloaded models? It shows their size, and No unless
  you say yes, so nothing large is left behind by accident. Whatever you keep is picked up by
  the next install, even in a folder other than the default.

- **Training checkpoints are kept**, listed under **Training checkpoints** in the picker. Settings
  can delete them when training ends instead.
- **Save asks which format:** FLAC, WAV or MP3, starting with the one set in Settings, now called
  **Output audio format**. FLAC is the default for stems and takes.
- **Variations has its own length cap**, for the new takes only.
- **Up next shows five rows** and scrolls for the rest.
- **An album in one file can be split into its tracks** by the `.cue` sheet beside it, from the
  corpus window. A recording longer than 10 minutes is no longer analysed as one song.
- **Corpus lyrics are tagged by section more accurately.** With an external LLM set, the sections
  are marked from the words as heard, which finds choruses the music analysis runs together.
  Without one, section boundaries now move to the pause before a line, so a first verse line no
  longer lands in the intro. **Redraft** in a song's review re-tags a song drafted before.
- **The corpus window says what its analysis is doing**, such as the vocal being separated and
  how far it has got, and **Stop** ends it.

### Fixed

- **A format chosen by default was stored as if you had chosen it**, so a later change of default
  never reached you. Settings now keeps only what you change.
- **A trained LoRA the app cannot read** stops the run with the fix, rather than finishing half
  of it.
- **Cancelling a corpus song's analysis on the main page stopped only its GPU step.** The vocal
  separation and lyrics carried on unseen, and the corpus said **Analysing…** with no way to stop
  it. Cancelling now stops every step of that song.
- **A reinstall on Windows after keeping the models could miss them**, when YuE2 Studio had been
  installed somewhere other than the default folder. The kept files stayed behind in the old one.

## 0.0.34 - 2026-09-24

### Fixed

- **Edited lyrics were lost when the take on show was clicked, or played.** Clicking a take, or
  its Play, Score or Stems button, loads the take into the form, and that replaced lyrics you had
  typed over the take already on show. Now your edit stays where it is. Clicking a different take
  still shows that take's words, and keeps yours with **Restore** in the bar above the form.

  To render edited lyrics, press **Create cover** (or **Create song**) with them in the form. A
  take keeps the words it was made with, which is what lets **Again** reproduce it.

- **The expanded Lyrics and Score editors closed under the pointer.** Pressing the mouse inside
  one and letting go just outside it counted as a click on the backdrop, which closed the window.
  The two editors now close only with **Done** (or Esc). Other windows still close on a click
  beside them, but only a click that begins there.

## 0.0.33 - 2026-09-24

### What's new

- **A Windows installer that needs no Docker** (first version, being tested). A small installer
  checks the PC, then downloads each part from its own publisher and sets YuE2 Studio up natively.
  It needs no WSL and no administrator rights, and downloads resume if they break off. It is
  attached to this release as `YuE2Studio-Setup-0.0.33.exe`; see *On Windows, without Docker* in
  the README.
- **Stems default to FLAC**: lossless, about half the size of WAV, and the format takes are
  already saved in. WAV and MP3 are still in Settings, and a format you have already chosen is
  kept.

### Fixed

- **Asking for stems no longer comes back as an error.** The stems were made, but the request was
  answered with an error, since 0.0.14.
- **The Vocal chips follow the style text.** A style that said "female" somewhere other than the
  chips' own phrase (a learned style's "intimate female lead vocals", say) kept Female lit
  whichever chip was clicked. Switching away from Duet also left scraps ("male and") behind, and
  those could tip the model to the wrong voice. The chips now change the voice words where they
  are, and clear old scraps.
- **Normalising writes a louder copy beside the take** instead of replacing its file, so a take
  that is playing, or open in another program, no longer blocks it. Takes normalised by 0.0.29 to
  0.0.32 are converted when the app starts.
- **Corpus style analysis without Gemma or an external LLM** now says what it needs, instead of
  failing with an engine error.

## 0.0.32 - 2026-09-24

### Fixed

- **`scripts/fetch-models.sh` stopped partway through on a fresh install** (since 0.0.14), with
  `REAL_AUDIO: parameter not set`. The Production polish LoRA, its tokenizer head and the training
  regularizer pack were never downloaded, so Production polish stayed greyed out and training
  failed. An install that already has those files was not affected. **If you installed from a
  release since 0.0.14, run `sh scripts/fetch-models.sh` again**; it skips what you already have.

### Notices

- `THIRD_PARTY_NOTICES.md` now names FS_Audio Suite (the trainer) and the hum-to-song regularizer
  pack, both CC BY-NC 4.0.

## 0.0.31 - 2026-09-24

### What's new

- **Normalise any take** with the speaker button at the top of its card, beside Sing again and
  Variations. It shows on finished takes that are not yet normalised.
- **A normalised take still says if it was weak as rendered:** *Weak render, normalised: try
  another seed if it sounds thin*. Normalising raises the level and nothing else, so this is the
  hint to listen. A take that sounds fine can be cleared with the **×** on the note; a new render
  of it brings the check back.

### Improved

- **The All/Starred filter is kept across a reload**, like the layout.
- **With the logs popped out, the Logs button brings that window forward** instead of opening the
  panel as well.

## 0.0.30 - 2026-09-24

### Fixed

- **Normalising a take from its warning now shows it is working.** The card says *Normalising…*
  from the click until the take is done, then *Normalised*. Before, nothing changed for several
  seconds, and it was not clear the click had been taken.

## 0.0.29 - 2026-09-24

### What's new

- **Normalise volume.** Tick it in the form and each take made while it is ticked is brought to the
  usual loudness when it finishes. A take flagged *Weak render* can be normalised from its warning
  ("click here to normalise, or try another seed"). A normalised take is marked *Normalised*, and
  the file as rendered is kept beside it. Nothing is normalised unless you ask.
- **Cancel a job waiting in Up next** before it starts. Cancelling a corpus song's re-analysis keeps
  the style, or key and tempo, it had before.
- **A take that ran on to the Length cap says so.** When a render keeps going past the end of its
  score and is cut at the cap, its ending may loop, wander or stop dead; the card now says so. A
  take capped short on purpose is not flagged.

### Improved

- **Training checkpoints have their own group** in the Style LoRA list, closed until opened and in
  step order, instead of sitting among your finished corpus LoRAs.
- **Learned styles sit in a box that scrolls**, so a large corpus no longer pushes the form down the
  page. A long song title is shortened, with the full style in its tooltip.
- **The header:** the version and Logs sit right-aligned under the status badges, and the name
  lines up with the first badge.
- The queue names corpus jobs as *Corpus analysis*.

## 0.0.28 - 2026-09-24

### Fixed

- **Corpus style tags from a thinking model came back cut off.** With a model that thinks before
  it answers (such as gemini-3.8-flash), the style request's small reply budget went on the model's
  thinking, so a song's style could come back as a single word, a fragment or just "." — and that
  went into its training caption. The budget is now large enough, a reply cut off at its budget is
  logged, and a reply with no words fails the song's style step so **Analyse style** is offered
  again. **If you analysed a corpus with a thinking model, re-analyse its styles** (the button on
  each song), then export and train again.
- **Live off now pauses the log panel** (and the pop-out window), so the lines stay put while you
  read. Before, it only stopped the scrolling.

### Logging

- A crash in the app now reaches the Logs panel and the log file, not only the container output.
- A refused action is logged with its reason; so is a script error in the page (capped), and a
  score saved with changes by hand.
- Log lines never show anything shaped like a key, whichever part of the app or engine wrote them.

### For contributors

- `sh tools/install-hooks.sh` turns on the repository's hooks: a pre-commit check that refuses a
  commit carrying a key, and the same check over the whole history before a push to GitHub.

## 0.0.27 - 2026-09-24

### New

- **A LoRA can keep its own strengths.** When you find the right Planner and Sound for a LoRA,
  press **Save strengths** under the picker. Choosing that LoRA then starts at them, and the note
  says so. They are kept in the LoRA's note, so they travel with it when you share it.
- **Getting back to them.** Load a take made at other strengths, or move a slider, and the note
  offers **use** to put the saved pair back. Choosing the same LoRA again does the same.
- **Architecture document.** `docs/ARCHITECTURE.md` explains how the app drives ComfyUI and YuE2,
  where LoRAs attach, the LLMs, Whisper and demucs, and the app's API with examples, with diagrams.

### Changed

- **Delete LoRA** says what the button deletes.
- A LoRA with saved strengths no longer shows the general strength advice beside them.

## 0.0.26 - 2026-09-24

### New

- **Sing again.** A mic icon in each take's corner sings the same score again with a new seed, as a
  new take beside the original. The melody, chords and words stay; the performance is drawn afresh,
  so the backing and the voice can both change. With a style LoRA the voice usually stays close;
  press again to try another. Useful for keeping a song you like while trying for a better take of
  it, including at a longer length.
- **The Style LoRA list folds by group.** Click a heading to open or close it; the picker
  remembers which groups you left open, and the group holding the current LoRA opens with it.
- **Buttons instead of underlined links** in the left panel: Rescan, Download, Install, Delete,
  Write lyrics, Expand, and the draft bar's Restore and Dismiss. The space buttons get the same
  lighter fill, so they stand out on the dark panels.

### Fixed

- A reload returns to the mode the page was left in (Cover, Song or Instrumental); it always
  opened on Cover.

## 0.0.25 - 2026-09-24

### New

- **Share a LoRA.** Under the Style LoRA picker, **Download** gives one zip with the chosen LoRA
  and its note. For a LoRA trained from a corpus, the note carries its learned styles, so the
  style chips travel with it.
- **Install** takes a shared zip, or a bare `.safetensors` file, and puts it in `models/loras`
  under the heading **Installed**, with its name, trigger word and chips. It is open to everyone,
  not only from inside a corpus.
- **Delete** removes the chosen LoRA with its note, its training log and its line in
  `families.txt`; a corpus that made it forgets it.
- **Rescan** reads `models/loras` again, for a file added by hand. The four sit on one line under
  the picker, with the detail in their tooltips.

### Fixed

- The seed box shows all ten digits. A seed like 1747519420 was cut to 174751942, so changing
  between takes whose seeds differed only in the last digit looked as if the seed had not changed.
- **Previous** and **Next** on the player bar load the take into the left column, as Play on a card
  does. The player moved on while the form, seed included, still described the take before.
- The note under the picker for a LoRA trained here gives the current advice: up to about 0.70 /
  0.70 in a song, Sound near 0.50 in a cover.

### Documentation

- The guide and README say how to share a LoRA, and point to Rescan and Install rather than
  restarting the engine. The README's rows for `TRAINING_ENABLED` and `WITH_TRAINER` are plainer.

## 0.0.24 - 2026-09-24

- **Training a LoRA from your own songs is on by default.** Corpora and LoRA training are part of
  the standard build. Open **Corpora** from the menu, point it at a folder of one artist's songs,
  and train a style LoRA from it. It shows most in a song from a prompt, where the LoRA writes the
  tune: Planner and Sound up to about 0.70, Plan variety Calm or Normal. In a cover, keep Sound
  near 0.50.
- To leave it out, set `TRAINING_ENABLED: "0"` on the app, or build the engine with
  `WITH_TRAINER=0`. An engine image built before this does not include the trainer: run
  `docker compose build engine` to add it.
- The README opens with a short list of what the app does.

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
