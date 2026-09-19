FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/London

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Stems.  CPU build of torch on purpose: the GPU belongs to YuE2, and demucs runs
# at about 1.3x realtime on four CPU threads, so a four minute song takes roughly
# three minutes with no VRAM contention at all.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "torch==2.9.1" "torchaudio==2.9.1" \
         --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir demucs==4.1.0

# VERSION changes on every release, so it must come AFTER the slow installs.
# With it above them, a version bump invalidated both pip layers and cost three
# minutes of re-downloading torch and demucs for a one character change.
COPY VERSION ./VERSION
COPY app ./app

# The image runs as a non-root user, so the code must be world readable.  Files
# written by some editors land as mode 0600, which breaks that at import time.
RUN chmod -R a+rX /app

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8090/api/health', timeout=4).read()"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090", "--no-access-log"]
