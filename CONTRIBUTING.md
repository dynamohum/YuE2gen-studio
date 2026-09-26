# Contributing

Start with [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the pieces fit together.

## Branches, and trying a change before it lands

Work on a branch, and use the test instance rather than production:

1. `git worktree add ~/scratch/yue2studio-<name> -b feature/<name>` from `master`.
2. `CODE=~/scratch/yue2studio-<name> sh ~/scratch/yue2-persona/refresh-test-instance.sh` brings it up
   on <http://localhost:8092>, on the production image with its own copy of the library.
3. Merge to `master` and redeploy once the change has been used and approved.

## Tests

They run in the app image, which already has ffmpeg and the pinned packages. No GPU and no engine
are needed: the job lanes run against a fake engine.

```sh
docker run --rm -v "$PWD":/src -w /src --user 1000:1000 -e HOME=/tmp yue2studio-app:latest \
  sh -c "pip install -q --user -r requirements-dev.txt && python -m pytest -q tests"
npx eslint@9 app/static/app.js
node tools/selection-harness.mjs
```

`tools/selection-harness.mjs` checks who owns the left column after each way of changing it, offline,
in about a second. `tools/ui-harness.mjs` drives the real page against a running deployment and
creates takes, so delete them afterwards.

## Keys never go into git

Run `sh tools/install-hooks.sh` once in each checkout. It points git at `tools/git-hooks`, whose
pre-commit hook refuses a commit carrying a key: any key stored in this install's settings (even in part, and whatever its
format), or anything shaped like a Google, OpenAI, Anthropic, GitHub or Hugging Face key or a
private key. The pre-push hook runs the same check over the whole history before anything goes to GitHub, and
`python3 tools/check_secrets.py --all` runs it by hand. GitHub's
secret scanning and push protection are on for the public repository as a second line.

## Commit messages

Say what the change does, in a sentence or two. Describe the code, not the conversation that led to
it: no references to earlier work, and no account of what was changed from.

## Releases and pushing

`VERSION` holds the version and the app shows it in the header, so a running container can be
identified without guessing. It moves for a feature release: a new capability, or a change to how
the app works. A fix, a layout change or a colour does not move it.

Note that `VERSION` also busts the browser cache, because the page asks for its scripts and
stylesheets as `app.js?v=<VERSION>`. A deploy that does not move it can leave a browser on the old
files, so check with a hard refresh after one.

A release is a tag on `master`, an entry in [CHANGELOG.md](CHANGELOG.md) and a push to GitHub. The
procedure is at the top of that file. `origin` is the author's own git server: commits go there by
default and nowhere else.

```sh
git push origin master --tags     # the default
git push github master --tags     # only when a public release is wanted
gh release create vX.Y.Z --title vX.Y.Z --notes-file notes.md
```

PDFs in the top-level folder are git ignored and never go to GitHub: a pre-push hook refuses a
GitHub push carrying a commit with one. Enable the hook once per clone:

```sh
git config core.hooksPath tools/git-hooks
```

## Screenshots

The README screenshots must not show a real library: the takes in one are someone's work in
progress, and an Identity holds their own songs. `tools/demo-library.py` writes a separate data
folder of invented takes, an invented Identity and one recording to cover, hard linking real
rendered audio in so the waveforms, lengths and the player are genuine. It only ever reads the
library you point it at.

```sh
python3 tools/demo-library.py --from data --to ~/scratch/yue2-docs/data
```

Run the app against that folder on a spare port, shoot the pages, then save each one twice: the
full size into `docs/screenshots/full/`, and the same image at half size next to it, which is what
the README shows inline and links to the full one from.

## The engine pin

The engine is built from one pinned ComfyUI commit (`ARG COMFYUI_REF` in `engine/Dockerfile`),
because a build that changes underneath you is worse than one that is slightly old. To see what has
changed upstream since, and whether any of it touches the YuE2 or audio code this app renders
through:

```sh
sh scripts/check-upstream.sh
```

It prints the pin, upstream's latest commit and release, how many commits behind the pin is, and the
ritual for moving it: build the candidate beside the live engine, render a cover, a song, an
instrumental and a lyric draft against it, then move the pin in a commit that says what was checked.

It also reports:

- **The trainer:** the commits to FS_Audio Suite since its pin (`ARG FS_AUDIO_REF`). Bump it by
  moving the pin, rebuilding the engine, and training a short run on a small corpus.
- **The models:** each Hugging Face repository `scripts/fetch-models.sh` downloads from, and the YuE2
  authors' own (m-a-p), where a new version appears first. These aren't pinned: a fresh install
  takes whatever is on `main`. So `scripts/upstream-reviewed.json` records the revision each one was
  at when last looked at, and the report marks any that have changed since. Read what changed, and
  when done, record it with `sh scripts/check-upstream.sh --reviewed`.
