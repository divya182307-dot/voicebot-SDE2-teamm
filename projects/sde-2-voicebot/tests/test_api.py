
import json
import logging
from datetime import datetime, timezone, timedelta

from fastapi.testclient import TestClient

from app.main import app, idempotency_store, event_history, JSONFormatter
from app.repository import session_repository
from app.config import settings, load_settings


client = TestClient(app)


def setup_function():
    session_repository.sessions.clear()
    idempotency_store.clear()
    event_history.clear()


def create_session():
    response = client.post("/sessions")
    assert response.status_code == 200
    return response.json()["session"]["id"]


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_readiness():
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["mode"] == "mock"


def test_request_ids():
    response = client.get(
        "/health",
        headers={
            "X-Request-ID": "test-request-123",
            "X-Correlation-ID": "test-correlation-456"
        }
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-123"
    assert response.headers["X-Correlation-ID"] == "test-correlation-456"


def test_error_envelope():
    response = client.get("/unknown")
    assert response.status_code == 404
    assert response.json()["code"] == "HTTP_ERROR"


def test_create_session():
    response = client.post("/sessions")
    assert response.status_code == 200
    assert response.json()["session"]["state"] == "created"


def test_session_transitions():
    session_id = create_session()

    events = [
        ("start", "active"),
        ("pause", "paused"),
        ("resume", "active"),
        ("stop", "stopping"),
        ("complete", "completed"),
    ]

    for event, expected in events:
        response = client.post(
            f"/sessions/{session_id}/events",
            json={"event_type": event}
        )

        assert response.status_code == 200
        assert response.json()["session"]["state"] == expected


def test_invalid_transition():
    session_id = create_session()

    response = client.post(
        f"/sessions/{session_id}/events",
        json={"event_type": "pause"}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "INVALID_SESSION_TRANSITION"


def test_session_not_found():
    response = client.get("/sessions/invalid-id")
    assert response.status_code == 404


def test_invalid_request_error_envelope():
    session_id = create_session()

    response = client.post(
        f"/sessions/{session_id}/events",
        json={"event_type": "jump"}
    )

    assert response.status_code == 422

    data = response.json()

    assert data["code"] == "INVALID_REQUEST"
    assert data["message_safe_for_user"] == (
        "The request contains invalid data."
    )
    assert data["retryable"] is False
    assert data["correlation_id"]
    assert data["details_redacted"] == {}


def test_expire_session():
    session_id = create_session()

    response = client.post(
        f"/sessions/{session_id}/events",
        json={"event_type": "expire"}
    )

    assert response.status_code == 200
    assert response.json()["session"]["state"] == "expired"


def test_error_response_has_ids():
    response = client.get("/unknown")

    assert response.status_code == 404
    assert response.headers.get("X-Request-ID")
    assert response.headers.get("X-Correlation-ID")
    assert response.json()["correlation_id"] == (
        response.headers["X-Correlation-ID"]
    )


# WEEK 2 TESTS


def test_session_expires_automatically():
    session_id = create_session()

    session = session_repository.sessions[session_id]
    session.expires_at = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    )

    response = client.get(f"/sessions/{session_id}")

    assert response.status_code == 200
    assert response.json()["state"] == "expired"


def test_idempotent_command_returns_same_result():
    session_id = create_session()

    headers = {"Idempotency-Key": "start-command-001"}
    payload = {"event_type": "start"}

    first_response = client.post(
        f"/sessions/{session_id}/events",
        json=payload,
        headers=headers
    )

    second_response = client.post(
        f"/sessions/{session_id}/events",
        json=payload,
        headers=headers
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    assert first_response.json() == second_response.json()

    assert len(event_history[session_id]) == 1


def test_idempotency_key_cannot_be_reused_for_different_event():
    session_id = create_session()

    headers = {"Idempotency-Key": "command-002"}

    first_response = client.post(
        f"/sessions/{session_id}/events",
        json={"event_type": "start"},
        headers=headers
    )

    second_response = client.post(
        f"/sessions/{session_id}/events",
        json={"event_type": "pause"},
        headers=headers
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 409


def test_events_are_returned_in_order():
    session_id = create_session()

    for event in ["start", "pause", "resume"]:
        response = client.post(
            f"/sessions/{session_id}/events",
            json={"event_type": event}
        )
        assert response.status_code == 200

    response = client.get(
        f"/sessions/{session_id}/events"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["count"] == 3

    assert [
        event["event_type"] for event in data["events"]
    ] == ["start", "pause", "resume"]

    assert [
        event["event_id"] for event in data["events"]
    ] == [1, 2, 3]


def test_event_stream_returns_server_sent_events():
    session_id = create_session()

    client.post(
        f"/sessions/{session_id}/events",
        json={"event_type": "start"}
    )

    response = client.get(
        f"/sessions/{session_id}/events/stream"
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "text/event-stream"
    )

    assert "event: start" in response.text
    assert "data:" in response.text
    assert "id: 1" in response.text


def test_event_history_session_not_found():
    response = client.get("/sessions/invalid-id/events")
    assert response.status_code == 404


def test_event_stream_session_not_found():
    response = client.get("/sessions/invalid-id/events/stream")
    assert response.status_code == 404


def test_oversized_request_is_rejected():
    response = client.post(
        "/sessions",
        content=b"x",
        headers={
            "Content-Length": str(settings.max_request_bytes + 1)
        }
    )

    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"
    assert response.json()["correlation_id"]
    assert response.headers.get("X-Correlation-ID")


def test_invalid_content_length_is_rejected():
    response = client.post(
        "/sessions",
        content=b"",
        headers={"Content-Length": "invalid"}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_CONTENT_LENGTH"


def test_invalid_app_mode_configuration(monkeypatch):
    monkeypatch.setenv("APP_MODE", "invalid")

    try:
        load_settings()
        assert False, "Expected invalid configuration to fail"
    except RuntimeError as exc:
        assert "APP_MODE" in str(exc)


def test_invalid_session_ttl_configuration(monkeypatch):
    monkeypatch.setenv("SESSION_TTL_SECONDS", "0")

    try:
        load_settings()
        assert False, "Expected invalid TTL to fail"
    except RuntimeError as exc:
        assert "SESSION_TTL_SECONDS" in str(exc)


def test_invalid_payload_limit_configuration(monkeypatch):
    monkeypatch.setenv("MAX_REQUEST_BYTES", "-1")

    try:
        load_settings()
        assert False, "Expected invalid payload limit to fail"
    except RuntimeError as exc:
        assert "MAX_REQUEST_BYTES" in str(exc)


def test_structured_logging_contains_correlation_id():
    formatter = JSONFormatter()

    record = logging.LogRecord(
        name="voicebot",
        level=logging.INFO,
        pathname="test_api.py",
        lineno=1,
        msg="Test log message",
        args=(),
        exc_info=None
    )

    record.correlation_id = "test-correlation-789"

    formatted = formatter.format(record)
    log_data = json.loads(formatted)

    assert log_data["level"] == "INFO"
    assert log_data["message"] == "Test log message"
    assert log_data["correlation_id"] == "test-correlation-789"
    assert "timestamp" in log_data
