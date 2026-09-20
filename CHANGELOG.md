# Changelog

Versions are git tags on `master`. The number lives in `VERSION`, which is copied into the
app image and shown in the header, so a running container can be identified at a glance.

To cut a release:

1. Bump `VERSION`.
2. Add an entry here, newest first.
3. `git commit -am "Release vX.Y.Z" && git tag vX.Y.Z`
4. `git push origin master --tags`   (homer only, unless GitHub is wanted)
5. For a public release: `git push github master --tags` and
   `gh release create vX.Y.Z --title vX.Y.Z --notes "..."`

Release notes live in two places and neither is a file in this repository: this changelog holds the
history, and each GitHub release holds its published notes. `RELEASE-NOTES-*.md` is ignored so it
cannot creep back in.

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
