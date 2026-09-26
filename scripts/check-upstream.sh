#!/usr/bin/env sh
# How far the engine has drifted from what it is built on:
#
#   - ComfyUI, pinned in engine/Dockerfile. The YuE2 nodes this app renders
#     through live there.
#   - FS_Audio Suite, the trainer, pinned there too.
#   - The model repositories on Hugging Face that scripts/fetch-models.sh
#     downloads from, and the YuE2 authors' own (m-a-p), where a new version
#     appears first.
#
# The pins are on purpose: a build that changes under you is worse than one that
# is a little old. But a pin nobody looks at quietly becomes a fork. Run this
# before cutting a release.
#
#   sh scripts/check-upstream.sh                  report
#   sh scripts/check-upstream.sh --show-details   also list each commit with its
#                                                 description (ComfyUI's in full only
#                                                 where they touch our code)
#   sh scripts/check-upstream.sh --reviewed       also record the model repositories
#                                                 as reviewed at their current revision
#
# Needs the GitHub CLI (gh) to compare the pins; without it, it prints each pin and
# its comparison URL so it can be read by hand.
set -eu

DETAILS=
for arg in "$@"; do
  case "$arg" in
    --show-details) DETAILS=--show-details ;;
    --reviewed) ;;
    *) echo "unknown option: $arg (use --show-details or --reviewed)" >&2; exit 2 ;;
  esac
done

REPO=comfyanonymous/ComfyUI
HERE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PIN=$(sed -n 's/^ARG COMFYUI_REF=\(.*\)$/\1/p' "$HERE/engine/Dockerfile")

if [ -z "$PIN" ]; then
  echo "Could not find COMFYUI_REF in engine/Dockerfile." >&2
  exit 1
fi
echo "engine pinned to $REPO @ $PIN"

if ! command -v gh >/dev/null 2>&1; then
  echo
  echo "gh is not installed, so the comparison is up to you:"
  echo "  https://github.com/$REPO/compare/$PIN...master"
  exit 0
fi

echo "upstream master  $(gh api "repos/$REPO/commits?per_page=1" \
  --jq '.[0].sha[0:8] + "   " + .[0].commit.author.date' 2>/dev/null || echo unknown)"
echo "latest release   $(gh api "repos/$REPO/releases/latest" \
  --jq '.tag_name + "   " + .published_at' 2>/dev/null || echo none)"

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
if ! gh api "repos/$REPO/compare/$PIN...master" > "$tmp" 2>/dev/null; then
  echo "Could not compare; check the network or the pin." >&2
  exit 1
fi

# Only the files this app renders through are worth reading about.
python3 "$HERE/scripts/_upstream_report.py" comfy "$tmp" "$PIN" "$REPO" $DETAILS

# The trainer: every change matters, since the whole repository is the trainer.
FS_REPO=KytraScript/ComfyUI-FS_Audio_Suite
FS_PIN=$(sed -n 's/^ARG FS_AUDIO_REF=\(.*\)$/\1/p' "$HERE/engine/Dockerfile")
echo
echo "trainer pinned to $FS_REPO @ $(printf %.8s "$FS_PIN")"
if gh api "repos/$FS_REPO/compare/$FS_PIN...HEAD" > "$tmp" 2>/dev/null; then
  python3 "$HERE/scripts/_upstream_report.py" trainer "$tmp" "$FS_PIN" "$FS_REPO" $DETAILS
else
  echo "Could not compare the trainer; check the network or the pin." >&2
fi

python3 "$HERE/scripts/_models_report.py" "$@"
