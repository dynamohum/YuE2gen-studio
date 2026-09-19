#!/bin/sh
# Fetch the models into ./models, about 17 GB:
#
#   checkpoints/yue2_3b_bf16.safetensors                 YuE2, plans and renders       7.8 GB
#   audio_encoders/sheetsage2_bf16.safetensors           SheetSage2, transcription      1.4 GB
#   text_encoders/gemma4_e4b_it_int8_convrot.safetensors Gemma 4 E4B, lyric drafts      8.1 GB
#
#   sh scripts/fetch-models.sh
#
# A file that is already there is kept, and an interrupted download resumes.
# It also creates data/ and engine-state/output/, which the app needs to own.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
YUE2=https://huggingface.co/Comfy-Org/YuE2/resolve/main
GEMMA=https://huggingface.co/Comfy-Org/gemma-4/resolve/main

mkdir -p "$ROOT/models/checkpoints" "$ROOT/models/audio_encoders" "$ROOT/models/text_encoders"
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
  curl -L --fail --retry 5 --retry-all-errors -C - -o "$dest.part" "$url"
  mv "$dest.part" "$dest"
}

fetch "$YUE2/checkpoints/yue2_3b_bf16.safetensors" \
      "$ROOT/models/checkpoints/yue2_3b_bf16.safetensors"

fetch "$YUE2/audio_encoders/sheetsage2_bf16.safetensors" \
      "$ROOT/models/audio_encoders/sheetsage2_bf16.safetensors"

fetch "$GEMMA/text_encoders/gemma4_e4b_it_int8_convrot.safetensors" \
      "$ROOT/models/text_encoders/gemma4_e4b_it_int8_convrot.safetensors"

echo "done.  models/ now holds:"
ls -la "$ROOT/models/checkpoints" "$ROOT/models/audio_encoders" "$ROOT/models/text_encoders" | grep -v '^total' | grep -v '^d'
