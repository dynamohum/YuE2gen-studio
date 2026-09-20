#!/usr/bin/env sh
# How far the engine has drifted from ComfyUI upstream.
#
# The engine is pinned to one ComfyUI commit on purpose: a build that changes
# under you is worse than one that is a little old. But a pin nobody looks at
# quietly becomes a fork, and the YuE2 nodes this app renders through live in
# that repository. Run this before cutting a release.
#
#   sh scripts/check-upstream.sh
#
# Needs the GitHub CLI (gh) to compare; without it, it prints the pin and the
# comparison URL so it can be read by hand.
set -eu

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
python3 "$HERE/scripts/_upstream_report.py" "$tmp" "$PIN" "$REPO"
