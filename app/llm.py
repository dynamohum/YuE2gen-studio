"""External LLM integration for YuE2 Studio.

Provides an OpenAI-compatible client for delegating Gemma's text tasks
(lyric drafting and song musical style analysis) to an external LLM
provider (e.g. OpenAI, Anthropic, Gemini, Groq, OpenRouter, Ollama, LM Studio).

When enabled in Settings, the external LLM takes over:
1. Lyrics generation (brief, style, structure -> parsed lyrics)
2. Musical style tag description for corpus songs (title, artist, lyrics -> comma-separated tags)

All significant actions (requests, completions, token usage, errors, test connections)
are logged to the centralized logging system.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any
import httpx

from app.db import get_setting
import app.lyrics as lyrics

log = logging.getLogger("yue2.llm")

DEFAULT_PROVIDER = "local"
DEFAULT_API_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
REQUEST_TIMEOUT = 60.0


def get_config() -> dict[str, str]:
    """Return the current LLM configuration from the settings store."""
    provider = (get_setting("llm.provider", DEFAULT_PROVIDER) or DEFAULT_PROVIDER).strip().lower()
    api_url = (get_setting("llm.api_url", DEFAULT_API_URL) or DEFAULT_API_URL).strip().rstrip("/")
    api_key = (get_setting("llm.api_key", "") or "").strip()
    raw_model = (get_setting("llm.model", "") or "").strip()
    if not raw_model or (raw_model.lower().startswith("gpt-") and "generativelanguage.googleapis.com" in api_url):
        if "generativelanguage.googleapis.com" in api_url:
            model = "gemini-flash-latest"
        else:
            model = DEFAULT_MODEL
    else:
        model = raw_model
    return {
        "provider": provider,
        "api_url": api_url,
        "api_key": api_key,
        "model": model,
    }


def is_external_enabled() -> bool:
    """Return True if an external LLM provider is active."""
    return get_config()["provider"] == "external"


def _endpoint_url(base_url: str) -> str:
    """Normalize the base URL to point to /chat/completions."""
    cleaned = base_url.strip().rstrip("/")
    if "generativelanguage.googleapis.com" in cleaned:
        if not cleaned.endswith("/chat/completions"):
            if cleaned.endswith("/v1beta/openai") or cleaned.endswith("/v1/openai"):
                return f"{cleaned}/chat/completions"
            return "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        return cleaned

    if cleaned.endswith("/chat/completions"):
        return cleaned
    return f"{cleaned}/chat/completions"


async def chat_complete(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    config_override: dict[str, str] | None = None,
) -> str:
    """Call the OpenAI-compatible chat completions endpoint and return the text reply."""
    cfg = get_config()
    if config_override:
        cfg.update(config_override)
    endpoint = _endpoint_url(cfg["api_url"])
    raw_model = cfg.get("model") or ""
    if not raw_model or (raw_model.lower().startswith("gpt-") and "generativelanguage.googleapis.com" in endpoint):
        model = "gemini-flash-latest" if "generativelanguage.googleapis.com" in endpoint else DEFAULT_MODEL
    else:
        model = raw_model
    api_key = cfg["api_key"]

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "YuE2Studio/0.0.16",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    log.info("Sending chat completion to %s (model: %s, messages: %d)", endpoint, model, len(messages))
    t0 = time.perf_counter()

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        try:
            resp = await client.post(endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            elapsed = time.perf_counter() - t0
            log.error("External LLM request to %s timed out after %.2fs", endpoint, elapsed)
            raise RuntimeError(f"External LLM request timed out after {elapsed:.1f}s") from exc
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            log.error("External LLM request to %s failed after %.2fs: %s", endpoint, elapsed, exc)
            raise RuntimeError(f"External LLM connection failed: {exc}") from exc

    elapsed = time.perf_counter() - t0
    if resp.status_code != 200:
        err_msg = resp.text[:400]
        try:
            err_json = resp.json()
            if isinstance(err_json, list) and err_json and "error" in err_json[0]:
                err_msg = err_json[0]["error"].get("message") or err_msg
            elif isinstance(err_json, dict) and "error" in err_json:
                err_msg = err_json["error"].get("message") or err_msg
        except Exception:
            pass
        if "bidiGenerateContent" in err_msg or "-live" in model.lower():
            flash_alt = model.replace("-live", "-flash")
            err_msg = f"{err_msg} (Tip: '{model}' is a WebSocket streaming-only model. Use '{flash_alt}' for REST completions)."
        log.warning("External LLM error from %s: HTTP %d - %s", endpoint, resp.status_code, err_msg)
        raise RuntimeError(f"External LLM HTTP {resp.status_code}: {err_msg}")

    try:
        data = resp.json()
        choice = data["choices"][0]
        content = choice.get("message", {}).get("content") or ""
    except Exception as exc:
        log.error("Failed to parse JSON response from %s: %s (body: %s)", endpoint, exc, resp.text[:300])
        raise RuntimeError(f"Invalid response from LLM provider: {exc}") from exc

    usage = data.get("usage") or {}
    ptokens = usage.get("prompt_tokens", "?")
    ctokens = usage.get("completion_tokens", "?")
    log.info(
        "External LLM reply from %s (%s) in %.2fs (prompt_tokens=%s, completion_tokens=%s, chars=%d)",
        endpoint, model, elapsed, ptokens, ctokens, len(content),
    )
    return content


async def test_connection(config_override: dict[str, str] | None = None) -> dict[str, Any]:
    """Send a minimal test message to verify the external LLM configuration."""
    cfg = get_config()
    if config_override:
        cfg.update(config_override)
    raw_model = cfg.get("model") or ""
    if not raw_model or (raw_model.lower().startswith("gpt-") and "generativelanguage.googleapis.com" in cfg.get("api_url", "")):
        cfg["model"] = "gemini-flash-latest" if "generativelanguage.googleapis.com" in cfg.get("api_url", "") else DEFAULT_MODEL
    endpoint = _endpoint_url(cfg["api_url"])
    model = cfg["model"]
    log.info("Testing external LLM connection to %s (model: %s)...", endpoint, model)
    t0 = time.perf_counter()
    reply = await chat_complete(
        [
            {"role": "user", "content": "Ping test. Reply with the single word 'OK'."},
        ],
        temperature=0.0,
        max_tokens=120,
        config_override=cfg,
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)
    cleaned_reply = reply.strip()
    log.info("LLM connection test passed: model=%s, latency=%dms, reply='%s'", model, latency_ms, cleaned_reply[:30])
    return {
        "ok": True,
        "model": model,
        "latency_ms": latency_ms,
        "reply": cleaned_reply,
    }


async def generate_lyrics(brief: str, style: str, structure: str) -> dict[str, Any]:
    """Draft original lyrics using the external LLM."""
    prompt = lyrics.build_prompt(brief, style, structure)
    log.info("Starting external LLM lyrics generation (structure=%s, brief='%s')", structure, brief[:50])

    messages = [
        {"role": "system", "content": "You are a professional songwriter and lyricist."},
        {"role": "user", "content": prompt},
    ]

    reply = await chat_complete(messages, temperature=0.8)
    parsed = lyrics.parse(reply)

    if not parsed.get("title"):
        from app.main import guess_title
        parsed["title"] = guess_title(parsed.get("lyrics", "")) or brief[:50] or "Untitled"

    log.info(
        "Finished external LLM lyrics generation: title='%s', sections=%d, problems=%s",
        parsed["title"], len(parsed.get("sections", [])), parsed.get("problems", []),
    )
    return {
        "title": parsed["title"],
        "lyrics": parsed["lyrics"],
        "sections": parsed.get("sections", []),
        "problems": parsed.get("problems", []),
    }


def clean_style_tags(raw: str, title: str = "") -> str:
    """Tidy raw LLM output into a comma-separated line of musical style tags."""
    text = (raw or "").strip().strip("\"'`")
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # If the reply is formatted as bullet points on multiple lines, join them with commas
    if len(lines) > 1 and all(line.startswith(("-", "*", "•")) for line in lines):
        text = ", ".join(line.lstrip("-*• ") for line in lines)
    elif lines:
        # If the first line is an introductory phrase (e.g. "Here are the tags:"), drop it
        if re.match(r"^(?:here (?:are|is)|tags?|style|output)\b", lines[0], re.IGNORECASE) and len(lines) > 1:
            text = lines[1]
        else:
            text = lines[0]

    # Strip song title prefix like "Like a Rolling Stone - " or "Like a Rolling Stone:"
    if title:
        pattern = re.compile(rf"^(?:song\s*:\s*)?{re.escape(title)}\s*[-:–—]\s*", re.IGNORECASE)
        text = pattern.sub("", text)

    # Strip generic label prefixes like "Tags:" or "Style:"
    text = re.sub(r"^(?:tags|style|musical style|genre)\s*:\s*", "", text, flags=re.IGNORECASE)

    # Strip markdown emphasis
    text = text.replace("**", "").replace("*", "").replace("`", "")

    # Split, clean, deduplicate while preserving order
    seen = set()
    cleaned_tags = []
    for tag in text.split(","):
        clean_tag = " ".join(tag.split()).lower()
        if clean_tag and clean_tag not in seen:
            seen.add(clean_tag)
            cleaned_tags.append(clean_tag)

    return ", ".join(cleaned_tags)[:300]


async def describe_song_style(title: str, artist: str = "", lyrics_text: str = "") -> str:
    """Describe a corpus song's musical style as comma-separated tags using external LLM."""
    log.info("Starting external LLM style description for '%s' (artist: '%s')", title, artist or "unknown")

    user_content = [
        "Describe the musical style of the following song for a music generator as one line of comma-separated tags: genre, lead instruments, drums and mood. Output only the tags.",
        f"\nSong: {title}",
    ]
    if artist:
        user_content.append(f"Artist: {artist}")
    if lyrics_text and lyrics_text.strip():
        user_content.append(f"Lyrics excerpt:\n{lyrics_text.strip()[:600]}")

    user_prompt = "\n".join(user_content)

    messages = [
        {"role": "system", "content": "You are an expert musicologist and audio prompt engineer for an AI music generator. Output only the requested comma-separated tags."},
        {"role": "user", "content": user_prompt},
    ]

    reply = await chat_complete(messages, temperature=0.5, max_tokens=150)
    tags = clean_style_tags(reply, title=title)
    log.info("Finished external LLM style description for '%s': %s", title, tags)
    return tags


def _models_url(base_url: str) -> str:
    """Normalize the base URL to point to /models endpoint."""
    cleaned = base_url.strip().rstrip("/")
    if "generativelanguage.googleapis.com" in cleaned:
        return "https://generativelanguage.googleapis.com/v1beta/openai/models"
    if cleaned.endswith("/chat/completions"):
        cleaned = cleaned[:-17].rstrip("/")
    if cleaned.endswith("/models"):
        return cleaned
    return f"{cleaned}/models"


async def fetch_models(config_override: dict[str, str] | None = None) -> list[dict[str, str]]:
    """Query the provider's /models endpoint to discover available text/chat models."""
    cfg = get_config()
    if config_override:
        cfg.update(config_override)
    models_url = _models_url(cfg["api_url"])
    api_key = cfg["api_key"]
    log.info("Fetching available models from %s...", models_url)

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "YuE2Studio/0.0.16",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(models_url, headers=headers)
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            log.warning("Failed to fetch models from %s after %.2fs: %s", models_url, elapsed, exc)
            raise RuntimeError(f"Could not reach {models_url}: {exc}") from exc

    elapsed = time.perf_counter() - t0
    if resp.status_code != 200:
        err_msg = resp.text[:300]
        try:
            err_json = resp.json()
            if isinstance(err_json, dict) and "error" in err_json:
                err_msg = err_json["error"].get("message") or err_msg
        except Exception:
            pass
        log.warning("Models endpoint %s returned HTTP %d: %s", models_url, resp.status_code, err_msg)
        raise RuntimeError(f"HTTP {resp.status_code}: {err_msg}")

    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"Invalid JSON from models endpoint: {exc}") from exc

    raw_items = data.get("data") or data.get("models") or []
    excluded = (
        "embedding", "tts", "transcribe", "video", "veo", "audio", "lyria",
        "robotics", "image", "imagen", "dall-e", "whisper", "clip", "aqa",
        "babbage", "davinci", "moderation", "similarity", "search",
        "live", "bidi", "computer-use", "realtime", "omni", "deep-research",
        "antigravity", "customtools", "gemini-2.5-flash", "gemini-2.5-pro",
    )

    results: list[dict[str, str]] = []
    seen = set()
    for item in raw_items:
        mid = str(item.get("id") or item.get("name") or "").strip()
        if not mid:
            continue
        if mid.startswith("models/"):
            mid = mid[7:]
        if any(ex in mid.lower() for ex in excluded):
            continue
        if mid in seen:
            continue
        seen.add(mid)
        display_name = item.get("display_name") or item.get("name") or mid
        if display_name.startswith("models/"):
            display_name = display_name[7:]
        label = f"{display_name} ({mid})" if display_name != mid else mid
        results.append({"id": mid, "name": display_name, "label": label})

    # Sort models nicely: prioritize latest fast models, then flash, pro, mini, others
    def sort_key(m: dict[str, str]) -> tuple[int, str]:
        mid = m["id"].lower()
        if "3.8-flash" in mid or "flash-latest" in mid:
            priority = 0
        elif "flash" in mid:
            priority = 1
        elif "pro" in mid or "gpt-4o" in mid:
            priority = 2
        elif "mini" in mid:
            priority = 3
        else:
            priority = 4
        return (priority, mid)

    results.sort(key=sort_key)
    log.info("Discovered %d models from %s in %.2fs", len(results), models_url, elapsed)
    return results
