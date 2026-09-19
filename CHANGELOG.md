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

## 0.0.1 - 2026-09-19

Initial release.
