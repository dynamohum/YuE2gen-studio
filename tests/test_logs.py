"""Tests for consolidated logging API and ring buffer."""
import logging
from app import logging_setup


def test_ring_buffer_captures_logs():
    test_logger = logging.getLogger("yue2.test")
    test_logger.info("Test message for logging verification")
    test_logger.warning("Test warning event")
    test_logger.error("Test error event")

    result = logging_setup.get_recent_logs(limit=50)
    assert result["total_available"] > 0
    messages = [entry["message"] for entry in result["logs"]]
    assert "Test message for logging verification" in messages
    assert "Test warning event" in messages
    assert "Test error event" in messages

    # Test level filter
    warn_only = logging_setup.get_recent_logs(level="WARN")
    levels = {entry["level"] for entry in warn_only["logs"]}
    assert levels == {"WARNING"}

    # Test search filter
    search_res = logging_setup.get_recent_logs(search="warning event")
    assert any("Test warning event" in entry["message"] for entry in search_res["logs"])


def test_logs_api(client):
    test_logger = logging.getLogger("yue2.api_test")
    test_logger.info("API log verification entry")

    res = client.get("/api/logs")
    assert res.status_code == 200
    data = res.json()
    assert "logs" in data
    assert "latest_id" in data
    assert any("API log verification entry" in entry["message"] for entry in data["logs"])

    # Test filtering by level
    res_filtered = client.get("/api/logs?level=ERROR")
    assert res_filtered.status_code == 200
    for entry in res_filtered.json()["logs"]:
        assert entry["level"] == "ERROR"


def test_logs_page(client):
    res = client.get("/logs")
    assert res.status_code == 200
    assert "System Logs" in res.text
    assert "logs-console" in res.text


def test_action_logging_emits_logs(client):
    # Creating a song queues a plan and logs it
    res = client.post("/api/songs", json={"style": "rock", "lyrics": "Test lyric lines for action log"})
    assert res.status_code == 200
    take_id = res.json()["id"]

    logs = logging_setup.get_recent_logs(limit=20)["logs"]
    messages = [e["message"] for e in logs]
    assert any("Queued song plan" in m and take_id in m for m in messages)


def test_engine_log_ingestion():
    raw_engine_msg = "\x1b[32m[INFO]\x1b[0m Model YuE2TEModel_ prepared for dynamic VRAM loading."
    logging_setup.log_engine_entry(raw_engine_msg, timestamp="2026-09-22T21:40:00.123456")

    res = logging_setup.get_recent_logs(source="engine", limit=10)
    assert len(res["logs"]) > 0
    latest = res["logs"][-1]
    assert latest["source"] == "engine"
    assert latest["level"] == "INFO"
    assert "Model YuE2TEModel_ prepared for dynamic VRAM loading." in latest["message"]
    assert "\x1b" not in latest["message"]

    # Test filtering by app source excludes engine
    app_res = logging_setup.get_recent_logs(source="app", limit=50)
    for entry in app_res["logs"]:
        assert entry.get("source") == "app"


def test_logs_api_source_filter(client):
    logging_setup.log_engine_entry("[INFO] Prompt executed in 12.34 seconds", timestamp="2026-09-22T22:00:00")

    res_engine = client.get("/api/logs?source=engine")
    assert res_engine.status_code == 200
    for entry in res_engine.json()["logs"]:
        assert entry["source"] == "engine"
    assert any("Prompt executed in 12.34 seconds" in e["message"] for e in res_engine.json()["logs"])

    res_app = client.get("/api/logs?source=app")
    assert res_app.status_code == 200
    for entry in res_app.json()["logs"]:
        assert entry.get("source") == "app"
