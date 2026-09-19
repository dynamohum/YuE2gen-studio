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

## 0.0.2 - 2026-09-19

- **Write lyrics.** In *Song from a prompt*, say what the song is about and pick a structure. Gemma 4
  E4B writes a draft on the engine in about 40 seconds, and it lands in the lyrics box, with a title
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
