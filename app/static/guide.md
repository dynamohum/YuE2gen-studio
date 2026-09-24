# YuE2 Studio — the guide

This is about **using** the app. Installing it, and everything you need before it runs, is in the
[README](https://github.com/dynamohum/YuE2gen-studio#readme).

The app writes songs with YuE2, a model that works in two steps: first it writes a **score plan** —
the melody, the chords and the sections, as text — and then it **renders** that plan into audio.
Almost everything here follows from that split. A plan costs seconds and can be read, edited and
thrown away; a render costs minutes. So the app lets you look at the plan first.

---

## Your first song

1. **Type a style.** A sentence, not a tag list: *"warm indie rock, expressive female lead, jangly
   guitars, 96 BPM"*. This is the single biggest influence on what comes out.
2. **Add lyrics**, or press **Write lyrics** and let Gemma draft them from a description.
3. Press **Write score plan**. Nothing is rendered yet.
4. **Read the plan** when it lands. If the melody is wrong, **Write a new plan** rerolls it for the
   cost of a few seconds.
5. Press **Render this score**.

Tick *render as soon as the plan is ready* to run both steps without stopping in between.

The take appears in the library on the right, and plays in the bar at the bottom.

### What to put in the Style box

YuE2 reads this as a description of a recording, so describe a recording. Language, genre, voice,
instruments, mood, tempo and production, roughly in that order, all in one sentence. Bare tag lists
work less well, and section markers such as `[Verse]` belong in the lyrics, not here.

The **Vocal** chips below write into the style for you: female, male or duet, and a character such
as breathy or raspy. They are a shortcut for typing, and you can edit the result by hand.

### Drafting the lyrics

**Write lyrics**, beside the lyrics box, asks what the song is about and which shape it should have:
verse and chorus with a bridge, verse and chorus only, with an intro and outro, or a story with two
verses up front. The Style above sets the mood. Gemma writes the draft on the same engine, and it
lands in the box with a title if you had not given one. You can close the window while it writes.

It is a first draft. The lines scan and rhyme, but a model reaches for familiar images, and nothing
checks whether a line is already someone else's. Read it and make it yours before you plan.

---

## Reading and fixing the plan

The plan is written in **ABC notation**: music as plain text, letters instead of dots on a stave.
Chris Walshaw devised it in the early 1990s for sending folk tunes by email, and it stuck.

You do not need to read it. The app renders the same plan as a **chord chart** and as real **staff
notation** below the editor, and **Expand** opens all of it full size. But the text is what YuE2
wrote and what it renders from, so it is worth being able to find your way around.

### Reading a plan

A plan begins with a header, one letter and a colon per line:

```
X:1
M:4/4
L:1/32
Q:1/4=120
V: Vocal clef=treble name="Vocal Melody"
V: Ins   clef=treble name="Ins Melody"
K:D#m
```

| Line | Means |
|---|---|
| `X:1` | the tune's number. Every ABC file starts with one |
| `M:4/4` | the metre — four beats in a bar |
| `L:1/32` | the unit length: a bare letter lasts a thirty-second note |
| `Q:1/4=120` | the tempo — a quarter note at 120 beats per minute |
| `V:` | declares a voice. YuE2 writes two, a vocal and an instrumental line |
| `K:D#m` | the key, D sharp minor. `K:` always comes last in the header |

Then the music itself:

```
% intro
V: Vocal
z24z4"D#m"z4|"D#m"z32|
V: Ins
Z|d16a16-|a16g8a8|
```

- **Notes are letters.** `d16` is a D lasting 16 units. Lowercase sits an octave above uppercase,
  and `'` or `,` shift it further.
- **`-` ties** a note into the next one, so they sound as one.
- **`z` is a rest**, with a length like a note. A capital `Z` rests for a whole bar.
- **Chords live in double quotes**, like `"D#m"`, and sit in front of the note they start on. These
  are what **find and replace** edits.
- **`|` is a bar line**, and **`%` starts a comment** — which is how the sections are marked:
  `% intro`, `% verse`, `% chorus`.

So that fragment says: D sharp minor, four four, 120 beats per minute, and through the intro the
vocal rests while carrying the chord, while the instrument plays a tied D and A, then G and A.

Two practical consequences. **Editing chords is safe** even if the notes look opaque — they are only
the parts in quotes, and everything else can be left alone. And **if you edit the plan, the render
uses what you edited**, so repairing one is usually faster than rerolling until a good one appears.

### Harmony

YuE2 left alone tends to write one four-chord loop and stay there. The **Harmony** slider pushes it
away from chords it has just used, without breaking the song's structure.

| Step | What you get |
|---|---|
| Familiar | YuE2's own chords. Often one loop for the whole song |
| Varied | Avoids repeating the same chords. Stays in the key |
| Colourful | Verse and chorus get different progressions, with richer chords |
| Adventurous | Keeps the harmony moving, and borrows chords from outside the key |
| Outside | Adventurous, and reaches further outside the key |

**Write a new plan** uses the slider's current position, so you can reroll the same words with more
adventurous chords and compare.

This was measured rather than guessed — one set of lyrics, two styles, three seeds each:

| | Familiar | Varied | Colourful | Adventurous | Outside |
|---|---|---|---|---|---|
| Different chords in a song | 4.7 | 6.3 | 8.7 | 9.0 | 10.3 |
| Bars using a chord from outside the key | 0% | 0% | 0% | 13% | 24% |
| Four-bar patterns that are not repeats | 29% | 38% | 50% | 63% | 64% |

Every plan at every step kept its sections and valid chords. Asking for adventurous harmony in the
style text instead — "jazz harmony", "borrowed chords" — had no measurable effect at all.

### Plan variety

Under *Advanced*, **Plan variety** sets how freely the planner writes: calm, normal, bold or wild.
Where Harmony acts on the chords, this acts on everything — melody, structure and length.

---

## Rendering

### Interpretation

The score fixes the notes. The **interpretation** sets how they are performed.

| Interpretation | What you hear |
|---|---|
| Standard | YuE2's usual reading |
| Tight | more controlled and polished |
| Loose | rougher and more spontaneous |
| Settled | free to repeat a figure and sit in a groove |
| Restless | keeps the parts moving, avoids repeating itself |
| Wide | reaches for less obvious sounds |

### Variations

The sparkle button on a card renders **the same score and the same seed** in the other
interpretations. Because only the interpretation changes, what you hear between them is the
interpretation — not a different roll of the dice. Each lands as its own take, titled
*Night drive · Loose*.

### Seed, and reproducing a take

Every take records its seed and every setting that shaped it. The card names them, and clicking a
card loads all of it back into the form. **Again** re-renders from exactly that, so a take you liked
can be reproduced, and a take you nearly liked can be nudged one setting at a time.

Tick **fixed seed** to keep the same seed across renders; leave it off and each render rolls a new
one.

### Production polish

**Production polish** applies Mothersuperior's Realaudio decoder LoRA. Stock YuE2 often sounds boxy
in the mid-range; this separates instruments and vocals more cleanly. On by default.

### Length

The length cap is a firm limit, not a target. YuE2 decides when a song ends, and usually ends by
itself; the cap stops one that will not.

---

## Covering a recording

1. Drop in an audio file, up to 300 MB. It is stored once and hashed, so the same file is never
   held twice.
2. Press **Transcribe**. SheetSage2 writes the melody and the chords into the score box. This is
   cached per recording, so covering the same song again skips it.
3. Fix anything it misheard.
4. Add lyrics, choose a style, press **Create cover**.

A cover follows the original's melody and chords while the style decides everything else, which is
what makes it a cover rather than a copy.

### Extracting the lyrics

**Extract lyrics**, beside *Transcribe*, writes down what the recording sings: it separates the
vocal, listens to it, and lays the lines under the sections of the score. It is asked for rather
than done with every transcription, because it takes a couple of minutes where transcribing a score
takes seconds. It runs on the CPU, so a render is never held up by it, and the bar says which of the
two stages it is on. The separated vocal is kept, so extracting the same recording again skips
straight to the listening, which is most of the wait saved.

The words are kept with the recording. Press **Extract lyrics** again and they go straight back in
the box, and you're asked whether to extract them again, which is worth doing after changing the
method in Settings.

Expect a good draft rather than a transcript. Measured against the real words of two songs, Whisper
got **1.5% of words wrong** on one and **25%** on the other, where lead and backing vocals sing over
each other in the last chorus. It listens to the whole vocal: it used to skip whatever its voice
detector took for silence, which on sung vocals was most of the song. Read the draft and fix what it
misheard, especially where voices overlap.

**Letting an external LLM listen.** If an external LLM is your provider, Settings has a choice under
*Lyrics from a recording*. Set it to **External LLM** and the separated vocal is sent to the model to
hear the words, while Whisper still works out when each line is sung. On the same two songs Gemini
got **1.5% and 23%**, so the two are close; try both on a song Whisper struggles with. It needs a
model that accepts audio, such as Gemini. If the model refuses the audio, writes words that don't
match the recording, or holds back — cutting lines short, or pointing you at a lyrics site, as a
model may with a song it recognises — you get Whisper's version instead. The message when it finishes names which one
heard the words. The vocal leaves your machine for this; Whisper keeps it here.

---

## Instrumentals

The third mode writes a piece with no vocal. In place of lyrics it takes a **structure**:

| Structure | What YuE2 gets | Who decides |
|---|---|---|
| Let YuE2 decide | `[instrumental]` | YuE2 chooses the sections and their lengths |
| Sections | `[intro] [verse] [chorus] …` | you choose the sections, YuE2 their length |
| Timed sections | `[intro 0:00-0:15] …` | you choose both |

Add sections with the **+** chips, reorder them with the arrows, and give each a length when timed.
**Sent to YuE2** shows exactly what the model receives. The structure is guidance: YuE2 may rename a
section, add an interlude, or run past the times you gave, so the length cap is the firm limit.

### When an instrumental sings

Occasionally the model puts a voice into an instrumental. This is a model failure, not a setting
you got wrong, and the app handles it in two places:

- **Before rendering**, if the plan puts notes in the vocal voice, a dialog offers a new plan, a new
  seed, or rendering anyway.
- **After rendering**, the finished audio is checked for singing and the card says how much it
  found.

The check holds a separator in memory for speed. *Settings* offers a thriftier mode that loads it
per check and holds nothing, or turns the check off.

---

## Voices

The **Vocal** chips set the singer's sex and character by writing into the style.

## Corpora and training a LoRA

A **corpus** is a folder of one artist's songs, prepared as a training set for a style LoRA.
Open **Corpora** from the menu. It is on by default; `TRAINING_ENABLED=0` for the app, or an
engine built with `WITH_TRAINER=0`, takes it out.

1. **New corpus.** Give it a name and a **trigger word**, say whether the voice is male or female,
   describe the sound shared by every song, and open the folder that holds the songs. Confirm you
   have the right to train on them, then press **Scan the folder**. The folder is only read.
2. **Choose the songs.** Untick any you want left out.
3. **Analyse.** Each song's vocal is separated, its key, tempo and sections are found, and its
   lyrics are drafted, tagged by section.
4. **Review.** Open a song to check its lyrics and tick **checked**, and to describe its sound
   where it differs from the rest. The style caption shows what the trainer will read.
5. **Export training set.** Writes the audio, lyrics and caption for each song.
6. **Train a LoRA.** This takes a long time, and the GPU is not available to the app until it
   finishes. Progress shows on the main screen, where you can stop it.

When training finishes, the LoRA appears in the **Style LoRA** list with its trigger word. See
**Balancing Planner and Sound** below for starting strengths. To share it, press **Download** under
the picker; see **Sharing a LoRA** below.

To use a LoRA trained elsewhere from the exported set, press **Install a LoRA** and choose the
file. It is added to the Style LoRA list with this corpus's trigger word.

**Deleting a corpus** removes the app's copies of its songs, the separated vocals, the lyrics and
the scores. The folder you pointed it at, and any LoRA made from it, are not touched.

---

## Copyright and consent

What you train on, and what you do with the result, is your responsibility under the law where you
live. The app asks you to declare it and does not check it: creating a corpus requires you to confirm
that you have the right to train on those recordings.

Two facts are worth knowing:

- The YuE2 weights are **CC BY-NC 4.0** — non-commercial use, whatever you train from them.
- Training privately on a corpus and publishing the LoRA or its output are different acts. The second
  is the one that usually needs permission: from whoever holds the rights in the recordings, and for
  a recognisable voice, from the singer.

LoRAs you did not train yourself carry their own licences. `models/loras/SOURCES.md` records them
for the collection installed here.

## Style LoRAs

A LoRA is a small file that leans the model towards a sound. Put one in `models/loras/` and press
**Rescan** under the picker, or use **Install**, and it appears in the **Style LoRA** list.

A style LoRA can hold two halves, and the picker shows which ones a file holds:

- **Planner** shapes what is played — the score plan (form, harmony, phrasing), and then the music
  the render writes from that score. It applies at both steps.
- **Sound** shapes the audio — timbre and production.

A strength the file cannot use is greyed out, and a file this engine cannot load at all is named as
such rather than failing quietly inside a render.

### Balancing Planner and Sound

- **Cohesive corpora:** A LoRA trained on a single album or unified acoustic sound (e.g. 1960s folk rock) can run higher strengths, typically around **Planner ~0.85 / Sound ~0.80**.
- **Diverse corpora:** If the training corpus spans multiple genres, production styles, or eras (e.g. acoustic folk, rock, and synth-pop), high Sound weights can cause acoustic clashing. Up to about **Planner 0.70 / Sound 0.70** keeps the audio clean while retaining the artist's melodic phrasing and vocal character.
- **Covers:** your recording sets the melody, so there is less for the LoRA to shape and the Sound half is pushed harder. Keep Sound near **0.50**.
- **Plan variety:** with a LoRA trained from a corpus, **Calm** or **Normal** gives the most recognisable result.
- **Save strengths:** when you find the right pair for a LoRA, press **Save strengths** under the
  picker. Choosing that LoRA then starts at them, and they travel with it when you share it.

### Trigger words

Most style LoRAs are trained on captions that **begin** with a trigger word, and do very little
without it. The app handles this: choosing a LoRA puts its trigger at the front of the Style,
changing to another swaps it, choosing None removes it, and a render puts it back if it was
deleted. You will see the word appear in the Style box — it is yours to edit or move.

### Descriptions

The list is grouped by set. Click a heading to open or fold it; the picker remembers which you
left open, and the group holding your current choice always opens with it.

Hover any entry to read what it is, in its author's words, with their suggested strengths. Those
descriptions come from a text file beside the LoRA:

```
CHNSN Rive Gauche
Trigger: chnsn
Step 200, the decoder-loss minimum. The more supple of the two: acoustic
narrative, yé-yé, female leads, waltz meters.
```

The first line names it, a `Trigger:` line becomes the trigger word, and the rest is the
description. A LoRA of your own gets one by writing a `.txt` beside it. `families.txt` in the same
folder gives the groups their headings, one `prefix = label` per line.

### LoRAs trained from a corpus

A LoRA trained from one of your corpora is an ordinary style LoRA: it appears in this list with the
rest, its trigger word beside it, and the same two strengths apply.

New files appear once the engine has looked at `models/loras/` again, which it does when the
options are reloaded.

### Sharing a LoRA

Choose a LoRA and press **Download** under the picker: you get one zip with the LoRA and its note.
For a LoRA trained from a corpus, the note carries its learned styles, so the chips come with it.

To add one someone sent you, press **Install** and choose their zip, or a bare `.safetensors`
file. It goes into `models/loras` under the heading **Installed**, with its name, trigger word and
chips. **Delete LoRA** removes the chosen LoRA, its note and its group line; **Rescan** reads the folder
again after you add a file by hand.

---

## Stems

Press **Stems** on any take. Choose a model, tick the parts you want — vocals, drums, bass, other,
and guitar and piano on some models — and run.

Separation runs on the **CPU**, so it never competes with a render for the GPU. *Fine tuned* runs
four models in turn for a better split and takes about four times as long.

Stems land in `data/stems/<title>-<id>/`, play from the chips on the card, and download singly or as
a zip. They stay until you delete them.

---

## Stopping, deleting and starting again

A queued or running take shows **Cancel** on its card, and **stop** on the job card stops whatever
the engine is working on. Deleting a take stops its job and removes its stems. **Delete** beside a
recording removes the file and its stems; covers made from it keep their audio and score, but cannot
be rendered again.

**New song** — or **New cover** — beside the heading starts again from the take on show. It clears
the title, the lyrics and the score, and **keeps your settings**: style, vocal, Harmony, plan
variety, length cap, interpretation, LoRA and seed. The take being shown lets go of the panel, so
Render cannot act on it by mistake.

Words you had typed but not used are not thrown away: a bar offers to restore them.

## The library

### Spaces

Takes live in **spaces**: a space per song, per album, or for sketches. The menu above the takes
chooses which is on show, and anything you make lands there. Deleting a space never deletes takes —
they move to Default. Recordings are shared by every space, so one recording can be covered in
several.

The folder button on a card moves that take to another space.

### Cards

Each card names the settings that shaped it — Harmony, Interpretation, Plan variety, the LoRA and
its strengths, the seed and its age — so a card reads as the recipe that made it.

**Starred** shows only starred takes. **Compact** switches between three narrow cards across and
wider ones with the full title and style.

### The player

Click or drag the waveform to seek. Previous and next step through the cards in the order shown.

| Key | Does |
|---|---|
| Space | play or pause |
| Left, Right | back or forward five seconds |
| Up, Down | volume |

The keys do nothing while you are typing, or while a window is open in front. The system media keys
work too.

---

## Settings

Press **YuE2 Studio** in the top left. Settings live on the server, so they follow you to any
browser and survive a rebuild: the stem format, the separation model, where stems are written, and
how instrumentals are checked for singing.

---

## System Logs

The app writes a consolidated, real-time log of every major action — score planning, rendering, audio transcription, stem separation, and LoRA training — tagged with `INFO`, `WARN`, and `ERROR` prefixes.

- **In-Browser Console:** Click the **Logs** button in the topbar (or select *Logs* from the brand menu) to open a floating, draggable, and resizable console. It stays open without blocking the page, allowing you to queue takes and monitor generation in real time.
- **Standalone Window:** Click **↗ Pop out** in the console header (or navigate directly to `/logs`) to open a dedicated log viewer window.
- **Terminal Tail:** Logs rotate automatically to `data/logs/yue2studio.log` on the host, where you can follow them live:
  ```bash
  tail -f data/logs/yue2studio.log
  ```

---

## When something is wrong

**The header says the engine is missing.** The app runs without it and will say so. Renders wait.
Check the engine container is up.

**A song will not end.** Usually too much planner strength. Drop the LoRA's Planner to 0.5. The
length cap will stop it regardless.

**A LoRA seems to do nothing.** Check the trigger word is in the Style, and that the strength you
raised is one the file actually holds — the picker greys out the other.

**A take says *Weak render*.** It came out far quieter than usual all the way through, and takes
like that sound thin or distorted. It happens most in covers through a style LoRA trained here. Try
another seed, and keep that LoRA's Sound at 0.5 or below.

**An instrumental sang.** See *When an instrumental sings* above. It is a model failure; a new seed
usually fixes it.

**A take will not render again.** Its recording may have been deleted. Covers keep their audio and
score, but cannot be re-rendered from a recording that is gone.

**Nothing plays, but the waveform moves.** Check the volume slider and that a stem is not selected —
the player follows whatever was last clicked.
