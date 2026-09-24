#!/bin/sh
# Build the Windows installer: windows/dist/YuE2Studio-Setup-<version>.exe
#
# It stages what the installer carries (the app, our engine node, the scripts and the
# notices), then runs NSIS.  makensis on the PATH is used when there is one (Linux:
# apt install nsis; CI).  Otherwise, from WSL, the Windows NSIS in $NSIS_DIR, which
# is the zip from nsis.sourceforge.io unpacked; nothing needs installing.
#
#   sh windows/build.sh
#   NSIS_DIR=/mnt/c/tools/nsis-3.12 sh windows/build.sh
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(cat "$ROOT/VERSION")
OUT="$ROOT/windows/dist"
STAGE="$OUT/stage"

rm -rf "$STAGE"
mkdir -p "$STAGE/studio/engine-nodes"
# The app, less caches and the page-test harnesses.
tar -C "$ROOT" --exclude='__pycache__' --exclude='static/__*' -cf - app | tar -C "$STAGE/studio" -xf -
cp "$ROOT/VERSION" "$ROOT/requirements.txt" "$STAGE/studio/"
tar -C "$ROOT/engine/custom_nodes" --exclude='__pycache__' -cf - yue2_harmony | tar -C "$STAGE/studio/engine-nodes" -xf -
cp "$ROOT/windows/setup.ps1" "$ROOT/windows/launcher.py" "$ROOT/windows/yue2studio.ico" \
   "$ROOT/windows/terms.txt" "$ROOT/LICENSE" "$ROOT/THIRD_PARTY_NOTICES.md" "$STAGE/"

EXE="YuE2Studio-Setup-$VERSION${TEST_BUILD:+-test}.exe"
# TEST_BUILD=1 makes an installer whose setup skips the 18 GB of models.
EXTRA=${TEST_BUILD:+-DSETUP_ARGS=${TEST_ARGS:--SkipModels}}
if command -v makensis >/dev/null 2>&1; then
  makensis -V2 $EXTRA -DVERSION="$VERSION" -DSTAGE="$STAGE" -DOUTFILE="$OUT/$EXE" "$ROOT/windows/installer.nsi"
else
  NSIS_DIR=${NSIS_DIR:-/mnt/c/Users/Public/yue2-build/nsis-3.12}
  if [ ! -x "$NSIS_DIR/makensis.exe" ]; then
    echo "No makensis found. Install NSIS (apt install nsis), or unpack the NSIS zip and set NSIS_DIR." >&2
    exit 1
  fi
  # Windows NSIS reads Windows paths, and cannot read the WSL filesystem reliably, so
  # the staged files and the script are copied next to it first.
  WORK="$NSIS_DIR/../yue2-installer-work"
  rm -rf "$WORK"
  mkdir -p "$WORK"
  cp -r "$STAGE" "$WORK/stage"
  cp "$ROOT/windows/installer.nsi" "$WORK/"
  (cd "$WORK" && "$NSIS_DIR/makensis.exe" -V2 $EXTRA -DVERSION="$VERSION" -DSTAGE="$(wslpath -w "$WORK/stage")" \
      -DOUTFILE="$(wslpath -w "$WORK/$EXE")" "$(wslpath -w "$WORK/installer.nsi")")
  cp "$WORK/$EXE" "$OUT/$EXE"
  rm -rf "$WORK"
fi
echo "Built $OUT/$EXE ($(du -h "$OUT/$EXE" | cut -f1))"
