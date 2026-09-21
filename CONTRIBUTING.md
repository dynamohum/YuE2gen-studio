# Contributing

## Branches, and trying a change before it lands

Work on a branch, and use the test instance rather than production:

1. `git worktree add ~/scratch/yue2studio-<name> -b feature/<name>` from `master`.
2. `CODE=~/scratch/yue2studio-<name> sh ~/scratch/yue2-persona/refresh-test-instance.sh` brings it up
   on <http://localhost:8092>, on the production image with its own copy of the library.
3. Merge to `master` and redeploy once the change has been used and approved.

## Before pushing

```sh
docker run --rm -v "$PWD":/src -w /src --user 1000:1000 -e HOME=/tmp yue2studio-app:latest \
  sh -c "pip install -q --user -r requirements-dev.txt && python -m pytest -q tests"
npx eslint@9 app/static/app.js
node tools/selection-harness.mjs
```

## Commit messages

Say what the change does, in a sentence or two. Describe the code, not the conversation that led to
it: no references to earlier work, and no account of what was changed from.

## Releases

The procedure is at the top of [CHANGELOG.md](CHANGELOG.md). Every deployed change bumps `VERSION`;
a tag, a changelog entry and a push to the GitHub remote are for a release. `origin` is the
author's own server and takes every commit.

## Tests

The tests run in the app image, which already has ffmpeg and the pinned packages:

```sh
docker run --rm -v "$PWD":/src -w /src --user 1000:1000 -e HOME=/tmp yue2studio-app:latest \
  sh -c "pip install -q --user -r requirements-dev.txt && python -m pytest -q tests"
npx eslint@9 app/static/app.js
```

They need no GPU and no engine: the job lanes run against a fake engine.


## Versioning and where it is pushed

- `VERSION` holds the version, and the app shows it in the header, so a running container can be
  identified without guessing.
- Releases are git tags on `master`, each with an entry in `CHANGELOG.md`.
- `origin` is the author's own git server. Commits go there by default and nowhere else.
- `github` points at <https://github.com/dynamohum/YuE2gen-studio>. Nothing is pushed there unless it is
  asked for:

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


## The engine pin

The engine is built from one pinned ComfyUI commit (`ARG COMFYUI_REF` in
`engine/Dockerfile`), because a build that changes underneath you is worse than one
that is slightly old. To see what has changed upstream since, and whether any of it
touches the YuE2 or audio code this app renders through:

```sh
sh scripts/check-upstream.sh
```

It prints the pin, upstream's latest commit and release, how many commits behind the
pin is, and the ritual for moving it: build the candidate beside the live engine,
render a cover, a song, an instrumental and a lyric draft against it, then move the
pin in a commit that says what was checked.

