#!/bin/sh
# Fetch the YuE2 checkpoints into ./models.
#
#   sh scripts/fetch-models.sh          # INT8 checkpoint + the SheetSage2 encoder, about 5 GB
#   sh scripts/fetch-models.sh --bf16   # also the unquantised checkpoint, about 13 GB total
#
# It also creates data/ and engine-state/output/, which the app needs to own.
#
# INT8 is the default because it is what ComfyUI's own YuE2 blueprints use, and
# it peaks around 10 GB of VRAM.  The BF16 checkpoint sounds slightly better and
# peaks around 14.6 GB, which is tight on a 16 GB card.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
BASE=https://huggingface.co/Comfy-Org/YuE2/resolve/main

mkdir -p "$ROOT/models/checkpoints" "$ROOT/models/audio_encoders"
# The folders compose.yml mounts into the app.  Created here, as you, because a
# folder Docker creates for a mount belongs to root, and the app cannot write to it.
mkdir -p "$ROOT/data" "$ROOT/engine-state/output"

fetch() {
  url="$1"; dest="$2"
  if [ -s "$dest" ]; then
    echo "have  $(basename "$dest")"
    return 0
  fi
  echo "fetch $(basename "$dest")"
  curl -L --fail --retry 5 --retry-all-errors -C - -o "$dest" "$url"
}

fetch "$BASE/checkpoints/yue2_3b_int8_convrot.safetensors" \
      "$ROOT/models/checkpoints/yue2_3b_int8_convrot.safetensors"

fetch "$BASE/audio_encoders/sheetsage2_bf16.safetensors" \
      "$ROOT/models/audio_encoders/sheetsage2_bf16.safetensors"

for arg in "$@"; do
  case "$arg" in
    --bf16)
      fetch "$BASE/checkpoints/yue2_3b_bf16.safetensors" \
            "$ROOT/models/checkpoints/yue2_3b_bf16.safetensors"
      ;;
  esac
done

echo "done.  models/ now holds:"
ls -la "$ROOT/models/checkpoints" "$ROOT/models/audio_encoders" | grep -v '^total' | grep -v '^d'
