"""Tests for the external LLM provider integration."""
from unittest.mock import AsyncMock, patch
import pytest
import httpx

from app import llm, logging_setup
from app.db import get_setting, set_setting, execute, one
from app.jobs import LYRICS, run_job, run_identity_job


def test_llm_defaults():
    set_setting("llm.provider", "local")
    cfg = llm.get_config()
    assert cfg["provider"] == "local"
    assert not llm.is_external_enabled()


def test_llm_custom_config():
    set_setting("llm.provider", "external")
    set_setting("llm.api_url", "https://api.openai.com/v1/")
    set_setting("llm.api_key", "sk-test-12345")
    set_setting("llm.model", "gpt-4o")

    cfg = llm.get_config()
    assert cfg["provider"] == "external"
    assert cfg["api_url"] == "https://api.openai.com/v1"
    assert cfg["api_key"] == "sk-test-12345"
    assert cfg["model"] == "gpt-4o"
    assert llm.is_external_enabled()


def test_gemini_url_normalization_and_default_model():
    endpoint = llm._endpoint_url("https://generativelanguage.googleapis.com")
    assert endpoint == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

    endpoint2 = llm._endpoint_url("https://generativelanguage.googleapis.com/v1beta/openai")
    assert endpoint2 == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

    set_setting("llm.api_url", "https://generativelanguage.googleapis.com")
    set_setting("llm.model", "")
    cfg = llm.get_config()
    assert cfg["model"] == "gemini-flash-latest"


def test_clean_style_tags():
    # 1. Output prefixed with song title
    raw1 = "Like a Rolling Stone - folk rock, Hammond organ, electric guitar, piano, harmonica, loose driving backbeat, defiant"
    assert llm.clean_style_tags(raw1, title="Like a Rolling Stone") == "folk rock, hammond organ, electric guitar, piano, harmonica, loose driving backbeat, defiant"

    # 2. Output with colon after song title
    raw2 = "Song: Like a Rolling Stone: folk rock, organ, harmonica"
    assert llm.clean_style_tags(raw2, title="Like a Rolling Stone") == "folk rock, organ, harmonica"

    # 3. Output as bullet points
    raw3 = "- Folk rock\n- Hammond organ\n- Drums\n- Defiant"
    assert llm.clean_style_tags(raw3) == "folk rock, hammond organ, drums, defiant"

    # 4. Output with preamble and markdown bolding
    raw4 = "Here are the tags:\n**Folk Rock**, **organ**, drums, defiant"
    assert llm.clean_style_tags(raw4) == "folk rock, organ, drums, defiant"

    # 5. Output with deduplication and extra spaces
    raw5 = "folk rock,  Hammond Organ , folk rock , drums"
    assert llm.clean_style_tags(raw5) == "folk rock, hammond organ, drums"


@pytest.mark.anyio
async def test_chat_complete_success():
    set_setting("llm.provider", "external")
    set_setting("llm.api_url", "https://mock.api/v1")
    set_setting("llm.api_key", "mock-key")
    set_setting("llm.model", "test-model")

    mock_resp = httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "Mocked LLM reply"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
        request=httpx.Request("POST", "https://mock.api/v1/chat/completions"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        reply = await llm.chat_complete([{"role": "user", "content": "hello"}])
        assert reply == "Mocked LLM reply"
        assert mock_post.called
        call_kwargs = mock_post.call_args[1]
        assert "Bearer mock-key" in call_kwargs["headers"]["Authorization"]
        assert call_kwargs["json"]["model"] == "test-model"


@pytest.mark.anyio
async def test_test_connection_endpoint(client):
    mock_resp = httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "OK"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1},
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = client.post("/api/settings/test-llm", json={"api_url": "https://api.test/v1", "model": "my-model"})
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["model"] == "my-model"
        assert data["reply"] == "OK"


def test_settings_api_llm_fields(client):
    res = client.get("/api/settings")
    assert res.status_code == 200
    keys = {item["key"] for item in res.json()["settings"]}
    assert "llm.provider" in keys
    assert "llm.api_url" in keys
    assert "llm.api_key" in keys
    assert "llm.model" in keys

    # Put a setting
    put_res = client.put("/api/settings", json={"key": "llm.provider", "value": "external"})
    assert put_res.status_code == 200
    assert get_setting("llm.provider") == "external"

    put_res = client.put("/api/settings", json={"key": "llm.model", "value": "claude-3-5-sonnet"})
    assert put_res.status_code == 200
    assert get_setting("llm.model") == "claude-3-5-sonnet"


@pytest.mark.anyio
async def test_generate_lyrics_external_llm():
    mock_llm_lyrics = (
        "Title: Midnight Train\n\n"
        "[Verse]\n"
        "Walking through the cold dark rain\n"
        "Waiting for the midnight train\n"
        "Shadows dancing on the wall\n"
        "Nothing left for me at all\n\n"
        "[Chorus]\n"
        "Hear that whistle blowing low\n"
        "Nowhere left for me to go\n"
        "Take me down into the night\n"
        "Far away from morning light\n"
    )

    with patch("app.llm.chat_complete", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = mock_llm_lyrics
        res = await llm.generate_lyrics(brief="a blues song about leaving", style="delta blues", structure="verse-chorus")
        assert res["title"] == "Midnight Train"
        assert "[Verse]" in res["lyrics"]
        assert "[Chorus]" in res["lyrics"]


@pytest.mark.anyio
async def test_describe_song_style_external_llm():
    with patch("app.llm.chat_complete", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = "Like a Rolling Stone - folk rock, Hammond organ, electric guitar, loose driving backbeat, defiant"
        tags = await llm.describe_song_style(title="Like a Rolling Stone", artist="Bob Dylan", lyrics_text="Once upon a time...")
        assert tags == "folk rock, hammond organ, electric guitar, loose driving backbeat, defiant"


@pytest.mark.anyio
async def test_lyrics_job_with_external_llm():
    set_setting("llm.provider", "external")
    LYRICS["test-draft-1"] = {
        "id": "test-draft-1",
        "status": "queued",
        "brief": "a road song",
        "style": "rock",
        "structure": "verse-chorus",
        "seed": 42,
        "created_at": 1000.0,
        "title": None,
        "lyrics": None,
        "error": None,
    }

    mock_llm_lyrics = "Title: Open Road\n\n[Verse]\nDriving far into the night\n[Chorus]\nOpen road ahead\n"
    with patch("app.llm.chat_complete", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = mock_llm_lyrics
        await run_job("lyrics", "test-draft-1")

    record = LYRICS["test-draft-1"]
    assert record["status"] == "done"
    assert record["title"] == "Open Road"
    assert "[Verse]" in record["lyrics"]


@pytest.mark.anyio
async def test_identity_style_job_with_external_llm():
    set_setting("llm.provider", "external")

    # Create dummy identity and song
    execute("INSERT INTO identities(id, name, trigger_word, folder, created_at) VALUES('id-1', 'Bob Dylan', 'dylan', '/tmp/dylan', 1000.0)")
    execute(
        "INSERT INTO identity_songs(id, identity_id, file, title, sha256, style_state) VALUES('song-1', 'id-1', 'like.mp3', 'Like a Rolling Stone', 'sha', 'queued')"
    )

    with patch("app.llm.chat_complete", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = "folk rock, hammond organ, telecaster, driving beat, cynical"
        await run_identity_job("identity_style", "song-1")

    row = one("SELECT * FROM identity_songs WHERE id = 'song-1'")
    assert row["style_state"] == "done"
    assert row["style_hint"] == "folk rock, hammond organ, telecaster, driving beat, cynical"


def test_lyrics_available_in_state_when_external_llm_enabled(client):
    set_setting("llm.provider", "external")
    res = client.get("/api/state")
    assert res.status_code == 200
    state = res.json()
    assert state["options"]["lyrics_available"] is True
    assert state["options"]["llm_provider"] == "external"


def test_identity_song_style_endpoints(client, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "TRAINING_ENABLED", True)
    execute("INSERT INTO identities(id, name, trigger_word, folder, created_at) VALUES('id-test', 'Dylan', 'dylan', '/tmp/dylan', 1000.0)")
    execute("INSERT INTO identity_songs(id, identity_id, file, title, sha256) VALUES('song-test', 'id-test', 'test.mp3', 'Song Title', 'sha')")

    # Test editing style_hint
    edit_res = client.put("/api/identities/id-test/songs/song-test", json={"style_hint": "folk rock, acoustic"})
    assert edit_res.status_code == 200
    assert edit_res.json()["style_hint"] == "folk rock, acoustic"

    # Test queueing style analysis via POST /api/identities/{id}/songs/{song_id}/style
    style_res = client.post("/api/identities/id-test/songs/song-test/style")
    assert style_res.status_code == 200
    assert style_res.json()["queued"] is True
    row = one("SELECT style_state FROM identity_songs WHERE id = 'song-test'")
    assert row["style_state"] == "queued"


@pytest.mark.anyio
async def test_llm_actions_are_logged():
    mock_resp = httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "Sample response"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        await llm.chat_complete([{"role": "user", "content": "test logging"}])

    recent = logging_setup.get_recent_logs(search="external llm")
    assert recent["total_available"] > 0
    messages = [entry["message"].lower() for entry in recent["logs"]]
    assert any("external llm reply" in msg or "chat completion" in msg for msg in messages)


@pytest.mark.anyio
async def test_llm_http_error_handling():
    mock_resp = httpx.Response(
        401,
        text="Unauthorized - invalid api key",
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        with pytest.raises(RuntimeError, match="HTTP 401"):
            await llm.chat_complete([{"role": "user", "content": "hello"}])

