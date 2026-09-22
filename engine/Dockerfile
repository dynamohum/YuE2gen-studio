# YuE2 engine: ComfyUI with the native YuE2 and SheetSage2 nodes, on CUDA.
#
# Pinned to the ComfyUI commit this project was built and tested against.
# The model files are NOT baked in.  They are bind mounted at /app/models so the
# image stays around 10 GB instead of 25 GB, and so a rebuild never re-downloads
# 13 GB of weights.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Europe/London

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates curl ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# The master commit that added native YuE2 support and that we validated end to end.
ARG COMFYUI_REF=36da3ff7

WORKDIR /app
RUN git clone --quiet https://github.com/comfyanonymous/ComfyUI.git /app \
    && git checkout --quiet ${COMFYUI_REF}

# CUDA build of torch first, then ComfyUI's own pinned requirements, so pip does
# not pull a CPU-only torch over the top.
# torch, torchvision and torchaudio must move together.  Pinning only torch let
# pip pull torchaudio 2.11 against torch 2.9, and torchaudio then failed to load
# its own extension at import time.
RUN pip install "torch==2.9.*" "torchvision==0.24.*" "torchaudio==2.9.*" \
        --index-url https://download.pytorch.org/whl/cu128 \
    && pip install -r requirements.txt

# LoRA training, so a corpus built in the app can be trained from it.
# Dual-branch training using ComfyUI-FS_Audio_Suite (joint planner LoRA and decoder LoRA).
# Standalone: applies to ComfyUI's own YuE2 weights; no other checkpoint is downloaded.
# Pinned to the commit this was tested against.
#
# librosa, scipy and soundfile are required for audio tokenization and latent storage.
#
# EXPERIMENTAL, AND LEFT OUT BY DEFAULT.
# To build it in:   docker compose build --build-arg WITH_TRAINER=1 engine
# and run the app with TRAINING_ENABLED=1.  Both are needed: the app hides the
# button unless the node is present *and* the flag is set.
ARG WITH_TRAINER=0
ARG FS_AUDIO_REF=26fe2e91d20ebf3531cf053c0c654fd3b849e5de
RUN if [ "${WITH_TRAINER}" = "1" ]; then \
        git clone --quiet https://github.com/KytraScript/ComfyUI-FS_Audio_Suite.git \
            /app/custom_nodes/ComfyUI-FS_Audio_Suite \
        && git -C /app/custom_nodes/ComfyUI-FS_Audio_Suite checkout --quiet ${FS_AUDIO_REF} \
        && rm -rf /app/custom_nodes/ComfyUI-FS_Audio_Suite/.git \
        && sed -i 's/scale": "1.0 (no alpha)".*})/&; os.chmod(path, 0o644)/' \
            /app/custom_nodes/ComfyUI-FS_Audio_Suite/fs_train/artist.py \
        && pip install "soundfile>=0.12" "librosa>=0.10" "scipy"; \
    else \
        echo "trainer left out: build with --build-arg WITH_TRAINER=1 to include it"; \
    fi

# YuE2 Studio's own node: the Harmony control for score plans.  Copied after the
# slow installs, so a change to it rebuilds in seconds.
COPY custom_nodes/yue2_harmony /app/custom_nodes/yue2_harmony

EXPOSE 8188

# Localhost only in dev.  The app container will reach it by service name.
CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188"]
