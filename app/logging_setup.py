"""Centralized logging for YuE2 Studio: rotating file sink + in-memory ring buffer for the web UI."""
from __future__ import annotations

import collections
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import threading
from typing import Any

# In-memory ring buffer holding recent structured log entries
MAX_BUFFER = 2000
_LOCK = threading.Lock()
_SEQUENCE = 0
LOG_BUFFER: collections.deque[dict[str, Any]] = collections.deque(maxlen=MAX_BUFFER)
LOG_FILE_PATH: Path | None = None

FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


import re

ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')


def clean_ansi(text: str) -> str:
    """Strip ANSI escape sequences from terminal output."""
    return ANSI_ESCAPE_RE.sub("", text)


# Nothing shaped like a key reaches a log line: not in a URL's query, not as a bearer
# token, not bare.  Applied to every handler, so it holds whichever logger wrote it.
_REDACTIONS = [
    (re.compile(r"([?&](?:key|api_key|apikey|access_token|token|secret)=)[^&\s\"']+", re.I), r"\1***"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=\-]{8,}", re.I), r"\1***"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{35}"), "***"),
    (re.compile(r"AQ\.[0-9A-Za-z_\-]{30,}"), "***"),
    (re.compile(r"sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}"), "***"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), "***"),
    (re.compile(r"hf_[A-Za-z0-9]{30,}"), "***"),
]


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        clean = redact(message)
        if clean != message:
            record.msg, record.args = clean, None
        if record.exc_info and not record.exc_text:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
        return True


_REDACT = RedactFilter()


class RingBufferHandler(logging.Handler):
    """Stores structured log events in memory so the web client can query / live-tail."""

    def emit(self, record: logging.LogRecord) -> None:
        global _SEQUENCE
        try:
            msg = self.format(record)
            with _LOCK:
                _SEQUENCE += 1
                LOG_BUFFER.append({
                    "id": _SEQUENCE,
                    "timestamp": self.formatter.formatTime(record, DATE_FORMAT) if self.formatter else record.asctime,
                    "level": record.levelname,
                    "source": getattr(record, "source", "app"),
                    "logger": record.name,
                    "message": record.getMessage(),
                    "raw": msg,
                })
        except Exception:
            self.handleError(record)


def log_engine_entry(
    message: str,
    timestamp: str | None = None,
    level: str | None = None,
) -> None:
    """Ingest a log line from the engine container into the ring buffer and file."""
    global _SEQUENCE
    cleaned = clean_ansi(message).strip("\r\n")
    if not cleaned or not cleaned.strip():
        return

    # Handle multiline messages line-by-line
    lines = [clean_ansi(l).strip("\r") for l in message.split("\n")]
    lines = [l for l in lines if l.strip()]
    if not lines:
        return

    t_str = timestamp
    if not t_str:
        import datetime
        t_str = datetime.datetime.now().strftime(DATE_FORMAT)
    elif "T" in t_str:
        try:
            date_part, time_part = t_str.split("T", 1)
            time_part = time_part.split(".")[0]
            t_str = f"{date_part} {time_part}"
        except Exception:
            pass

    for line in lines:
        cleaned_line = line.strip()
        if not cleaned_line:
            continue

        line_level = level
        if not line_level:
            upper = cleaned_line.upper()
            if "[ERROR]" in upper or "ERROR:" in upper or "TRACEBACK" in upper or "EXCEPTION" in upper:
                line_level = "ERROR"
            elif "[WARNING]" in upper or "WARNING:" in upper or "[WARN]" in upper:
                line_level = "WARNING"
            elif "[DEBUG]" in upper:
                line_level = "DEBUG"
            else:
                line_level = "INFO"

        msg = redact(re.sub(r"^\[(INFO|WARNING|WARN|ERROR|DEBUG)\]\s*", "", cleaned_line))

        with _LOCK:
            is_progress = "%|" in msg or "sampling:" in msg.lower() or msg.startswith("100%|")
            if (is_progress and LOG_BUFFER and LOG_BUFFER[-1].get("source") == "engine"
                    and ("%|" in LOG_BUFFER[-1]["message"] or "sampling:" in LOG_BUFFER[-1]["message"].lower())):
                LOG_BUFFER[-1]["message"] = msg
                LOG_BUFFER[-1]["timestamp"] = t_str
                LOG_BUFFER[-1]["level"] = line_level
                LOG_BUFFER[-1]["raw"] = f"{t_str} {line_level:<5} [engine] {msg}"
            else:
                _SEQUENCE += 1
                entry = {
                    "id": _SEQUENCE,
                    "timestamp": t_str,
                    "level": line_level,
                    "source": "engine",
                    "logger": "engine",
                    "message": msg,
                    "raw": f"{t_str} {line_level:<5} [engine] {msg}",
                }
                LOG_BUFFER.append(entry)

                if LOG_FILE_PATH:
                    try:
                        with LOG_FILE_PATH.open("a", encoding="utf-8") as f:
                            f.write(entry["raw"] + "\n")
                    except Exception:
                        pass


class WindowsDisconnectNoise(logging.Filter):
    """On Windows, asyncio logs a traceback whenever a browser drops a connection (a
    reload, a closed tab): ConnectionResetError from _call_connection_lost.  Nothing
    failed, so it is left out."""

    def filter(self, record: logging.LogRecord) -> bool:
        error = record.exc_info[1] if record.exc_info else None
        return not (isinstance(error, ConnectionResetError) and "_call_connection_lost" in record.getMessage())


def setup_logging(logs_dir: Path | str | None = None) -> Path | None:
    """Configure console, rotating file, and in-memory ring buffer logging."""
    global LOG_FILE_PATH
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    formatter = logging.Formatter(FORMAT, datefmt=DATE_FORMAT)

    # 1. Console stream handler (if not already attached)
    has_stream = any(isinstance(h, logging.StreamHandler) and not isinstance(h, (RotatingFileHandler, RingBufferHandler))
                     for h in root.handlers)
    if not has_stream:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        root.addHandler(console)
    for h in root.handlers:
        if _REDACT not in h.filters:
            h.addFilter(_REDACT)

    # 2. Ring buffer handler (for web UI)
    ring = None
    for h in root.handlers:
        if isinstance(h, RingBufferHandler):
            ring = h
            break
    if not ring:
        ring = RingBufferHandler()
        ring.setFormatter(formatter)
        ring.addFilter(_REDACT)
        root.addHandler(ring)

    # 3. Rotating file handler (for CLI tailing)
    if logs_dir:
        path = Path(logs_dir)
        try:
            path.mkdir(parents=True, exist_ok=True)
            log_file = path / "yue2studio.log"
            LOG_FILE_PATH = log_file
            has_file = any(isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", None) == str(log_file)
                           for h in root.handlers)
            if not has_file:
                file_handler = RotatingFileHandler(
                    log_file, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
                )
                file_handler.setFormatter(formatter)
                file_handler.addFilter(_REDACT)
                root.addHandler(file_handler)
        except OSError as exc:
            logging.getLogger("yue2").warning("could not set up log file in %s: %s", path, exc)

    # A crash in a route is logged by uvicorn to "uvicorn.error", whose parent does not
    # propagate, so its traceback reached the container's output and nothing else.  The
    # ring buffer and the file get it too; uvicorn keeps its own console line.
    uvicorn_errors = logging.getLogger("uvicorn.error")
    for h in root.handlers:
        if isinstance(h, (RingBufferHandler, RotatingFileHandler)) and h not in uvicorn_errors.handlers:
            uvicorn_errors.addHandler(h)

    logging.getLogger("asyncio").addFilter(WindowsDisconnectNoise())

    # Suppress verbose third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

    return LOG_FILE_PATH


def get_recent_logs(
    level: str | None = None,
    search: str | None = None,
    source: str | None = None,
    limit: int = 200,
    since_id: int | None = None,
) -> dict[str, Any]:
    """Query recent logs from the in-memory ring buffer with filtering."""
    with _LOCK:
        items = list(LOG_BUFFER)
        latest_id = _SEQUENCE

    if since_id is not None:
        items = [item for item in items if item["id"] > since_id]

    if source and source.upper() != "ALL":
        target_src = source.lower()
        items = [item for item in items if item.get("source", "app").lower() == target_src]

    if level and level.upper() != "ALL":
        target = level.upper()
        if target == "WARN":
            target = "WARNING"
        items = [item for item in items if item["level"] == target]

    if search:
        query = search.lower()
        items = [
            item for item in items
            if query in item["message"].lower() or query in item["logger"].lower() or query in item.get("source", "app").lower() or query in item["raw"].lower()
        ]

    limit = max(1, min(1000, limit))
    sliced = items[-limit:]

    return {
        "logs": sliced,
        "total_available": len(items),
        "latest_id": latest_id,
        "file": str(LOG_FILE_PATH) if LOG_FILE_PATH and LOG_FILE_PATH.exists() else None,
    }


# Ensure ring buffer is active immediately on import
setup_logging()
