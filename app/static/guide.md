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

The plan is ABC notation: a compact text score. You do not need to read music to work with it.

- **Expand** opens a full-size editor with three views below it: a **chord chart**, real **staff
  notation**, and the **lyrics with each section's chords**.
- Chord symbols sit in double quotes, like `"Am"`. **Find and replace** fixes one everywhere, or
  you can change the harmony of a single section by hand.
- The header lines matter: `Q:` is the tempo, `K:` the key, `M:` the metre, and `V:` starts a voice.

If you edit the plan, the render uses what you edited. Repairing a plan is usually faster than
rerolling until one comes out right.

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

## Voices and Identities

The **Vocal** chips set the singer's sex and character by writing into the style.

An **Identity** is a voice trained from a corpus of songs, attached as a LoRA. Choosing one:

- puts its **trigger word** at the front of the style, which is how the model knows to use it;
- offers its **checkpoints** (Best, Step 250…) if it has more than one;
- shows a **Planner** strength beside them.

**Planner** deserves an explanation. A trained LoRA holds two halves. The *decoder* half is the
voice — how that singer sounds — and it is what an Identity has always applied. The *planner* half
is how that singer's songs are **written**: their forms, harmonies and phrasing. Planner is that
half, and it starts at **0**.

| Planner | What happens |
|---|---|
| 0 | Their voice, on a song structured however you asked. |
| 0.3–0.5 | Their writing colours the plan without taking it over. |
| 1.0 | It writes like its corpus. Expect longer plans, and watch for ones that will not end. |

---

## Style LoRAs

A LoRA is a small file that leans the model towards a sound. Put one in `models/loras/`, restart the
engine, and it appears in the **Style LoRA** list.

Like an Identity, a style LoRA has two halves, and the picker shows which ones a file holds:

- **Planner** shapes the score plan — form, harmony, phrasing. Applied when the plan is written.
- **Sound** shapes the audio — timbre and production.

A strength the file cannot use is greyed out, and a file this engine cannot load at all is named as
such rather than failing quietly inside a render.

### Trigger words

Most style LoRAs are trained on captions that **begin** with a trigger word, and do very little
without it. The app handles this: choosing a LoRA puts its trigger at the front of the Style,
changing to another swaps it, choosing None removes it, and a render puts it back if it was
deleted. You will see the word appear in the Style box — it is yours to edit or move.

### Descriptions

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

### Using one with an Identity

They work together: the Identity supplies the voice, the style LoRA the writing and the production.
Two things to watch, because both halves stack:

- **Two planner strengths add up.** Style 1.0 plus Identity 1.0 is where plans start running away.
  Style 1.0 with Identity 0.3, or 0.5 each, is a safer shape.
- **Two sound strengths add up too**, and a style LoRA at full Sound can bury the voice you chose
  the Identity for. Try Sound around 0.3–0.5 and let the Identity own the timbre.

Your own Identities do not appear in the style list — they have their own control, with the same two
strengths, so one file is never applied twice.

---

## Stems

Press **Stems** on any take, or beside a recording. Choose a model, tick the parts you want — vocals,
drums, bass, other, and guitar and piano on some models — and run.

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

## When something is wrong

**The header says the engine is missing.** The app runs without it and will say so. Renders wait.
Check the engine container is up.

**A song will not end.** Usually too much planner strength. Drop the LoRA's Planner to 0.5. The
length cap will stop it regardless.

**A LoRA seems to do nothing.** Check the trigger word is in the Style, and that the strength you
raised is one the file actually holds — the picker greys out the other.

**An instrumental sang.** See *When an instrumental sings* above. It is a model failure; a new seed
usually fixes it.

**A take will not render again.** Its recording may have been deleted. Covers keep their audio and
score, but cannot be re-rendered from a recording that is gone.

**Nothing plays, but the waveform moves.** Check the volume slider and that a stem is not selected —
the player follows whatever was last clicked.
