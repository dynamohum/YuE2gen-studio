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

# LoRA training, so a corpus built in the app can be trained from it.  Standalone:
# it bundles the YuE2 model code it needs and asks for no other custom node.  Pinned
# to the commit this was tested against, the same way ComfyUI is.
#
# soundfile is required, not optional: this image's torchaudio cannot decode the
# FLAC a training set is written as, and the pack falls back to soundfile.  Its other
# dependency, matplotlib, is only for its optional training-curve node, so it is not
# installed.
#
# EXPERIMENTAL, AND LEFT OUT BY DEFAULT.  What this pack trains does not sound like
# the corpus it was trained on, for a reason no setting fixes: it adapts only the
# acoustic branch and conditions it on an empty semantic span, while generation gives
# that branch the semantic tokens the planner wrote.  The measurements are in
# IDEAS.md and the reasoning is in app/config.py next to TRAINING_ENABLED.
#
# To build it in:   docker compose build --build-arg WITH_TRAINER=1 engine
# and run the app with TRAINING_ENABLED=1.  Both are needed: the app hides the
# button unless the node is present *and* the flag is set.
ARG WITH_TRAINER=0
ARG YUE2_TRAINER_REF=4578039513304149fdfd1c00a22783f06812997f
RUN if [ "${WITH_TRAINER}" = "1" ]; then \
        git clone --quiet https://github.com/Starnodes2024/ComfyUI-YuE2-Trainer.git \
            /app/custom_nodes/ComfyUI-YuE2-Trainer \
        && git -C /app/custom_nodes/ComfyUI-YuE2-Trainer checkout --quiet ${YUE2_TRAINER_REF} \
        && rm -rf /app/custom_nodes/ComfyUI-YuE2-Trainer/.git \
        && pip install "soundfile>=0.12"; \
    else \
        echo "trainer left out: build with --build-arg WITH_TRAINER=1 to include it"; \
    fi

# YuE2 Studio's own node: the Harmony control for score plans.  Copied after the
# slow installs, so a change to it rebuilds in seconds.
COPY custom_nodes/yue2_harmony /app/custom_nodes/yue2_harmony

EXPOSE 8188

# Localhost only in dev.  The app container will reach it by service name.
CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188"]
