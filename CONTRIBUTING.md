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
