
from fastapi.testclient import TestClient
from app.main import app
from app.repository import session_repository

client = TestClient(app)


def setup_function():
    session_repository.sessions.clear()


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
    response = client.post("/sessions")
    session_id = response.json()["session"]["id"]

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
    response = client.post("/sessions")
    session_id = response.json()["session"]["id"]

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
    response = client.post(
        "/sessions",
    )

    session_id = response.json()["session"]["id"]

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
    response = client.post("/sessions")
    session_id = response.json()["session"]["id"]

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