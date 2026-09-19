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
