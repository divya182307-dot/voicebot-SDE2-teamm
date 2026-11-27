
from fastapi.testclient import TestClient

from app.main import app


import pytest


@pytest.fixture(autouse=True)
def configure_authenticated_client(authenticated_client):
    global client
    client = authenticated_client


def create_test_session():
    response = client.post("/sessions")

    assert response.status_code == 200

    return response.json()["session"]["id"]


def publish_event(session_id, event_type):
    response = client.post(
        f"/sessions/{session_id}/events",
        json={"event_type": event_type}
    )

    assert response.status_code == 200

    return response.json()


def extract_event_ids(response):
    return [
        int(line.split(":", 1)[1].strip())
        for line in response.text.splitlines()
        if line.startswith("id:")
    ]


def test_replay_returns_only_missed_events():
    session_id = create_test_session()

    publish_event(session_id, "start")
    publish_event(session_id, "pause")
    publish_event(session_id, "resume")

    response = client.get(
        f"/sessions/{session_id}/events/stream",
        params={
            "last_event_id": 1,
            "max_events": 2,
            "timeout": 2
        }
    )

    assert response.status_code == 200
    assert extract_event_ids(response) == [2, 3]


def test_reconnect_using_last_event_id_header():
    session_id = create_test_session()

    publish_event(session_id, "start")
    publish_event(session_id, "pause")
    publish_event(session_id, "resume")

    response = client.get(
        f"/sessions/{session_id}/events/stream",
        headers={"Last-Event-ID": "2"},
        params={
            "max_events": 1,
            "timeout": 2
        }
    )

    assert response.status_code == 200
    assert extract_event_ids(response) == [3]


def test_replay_has_no_gaps_or_duplicates():
    session_id = create_test_session()

    publish_event(session_id, "start")
    publish_event(session_id, "pause")

    first_response = client.get(
        f"/sessions/{session_id}/events/stream",
        params={
            "max_events": 2,
            "timeout": 2
        }
    )

    assert first_response.status_code == 200

    first_ids = extract_event_ids(first_response)

    publish_event(session_id, "resume")
    publish_event(session_id, "stop")
    publish_event(session_id, "complete")

    second_response = client.get(
        f"/sessions/{session_id}/events/stream",
        headers={
            "Last-Event-ID": str(first_ids[-1])
        },
        params={
            "max_events": 3,
            "timeout": 2
        }
    )

    assert second_response.status_code == 200

    all_ids = first_ids + extract_event_ids(
        second_response
    )

    assert all_ids == [1, 2, 3, 4, 5]
    assert len(all_ids) == len(set(all_ids))


def test_invalid_future_event_cursor():
    session_id = create_test_session()

    publish_event(session_id, "start")

    response = client.get(
        f"/sessions/{session_id}/events/stream",
        params={
            "last_event_id": 100,
            "timeout": 1
        }
    )

    assert response.status_code == 400

    error = response.json()

    assert error["code"] == "INVALID_EVENT_CURSOR"
    assert error["retryable"] is False
    assert error["correlation_id"]


def test_reconnect_when_no_events_are_missing():
    session_id = create_test_session()

    publish_event(session_id, "start")

    response = client.get(
        f"/sessions/{session_id}/events/stream",
        headers={"Last-Event-ID": "1"},
        params={"timeout": 0.2}
    )

    assert response.status_code == 200
    assert extract_event_ids(response) == []


def test_reconnect_header_takes_precedence():
    session_id = create_test_session()

    publish_event(session_id, "start")
    publish_event(session_id, "pause")
    publish_event(session_id, "resume")

    response = client.get(
        f"/sessions/{session_id}/events/stream",
        headers={"Last-Event-ID": "2"},
        params={
            "last_event_id": 1,
            "max_events": 1,
            "timeout": 2
        }
    )

    assert response.status_code == 200
    assert extract_event_ids(response) == [3]

"""Week 3 authorization and rate-limit tests."""

import pytest

from fastapi.testclient import TestClient

from app.main import app
from app import middleware
from app.security import LocalAuthorization, RateLimiter


@pytest.fixture
def secured_client(monkeypatch):
    # Test-only token, not a real application secret.
    monkeypatch.setenv(
        "LOCAL_AUTH_TOKEN",
        "test-only-token"
    )

    monkeypatch.setattr(
        middleware,
        "auth_enabled",
        True
    )

    monkeypatch.setattr(
        middleware,
        "rate_limit_enabled",
        True
    )

    monkeypatch.setattr(
        middleware,
        "authorization",
        LocalAuthorization()
    )

    monkeypatch.setattr(
        middleware,
        "rate_limiter",
        RateLimiter(
            max_requests=3,
            window_seconds=60
        )
    )

    with TestClient(app) as client:
        yield client


AUTH_HEADERS = {
    "Authorization": "Bearer test-only-token"
}


def test_missing_authorization_is_rejected(
    secured_client
):
    response = secured_client.post("/sessions")

    assert response.status_code == 401

    error = response.json()

    assert error["code"] == "UNAUTHORIZED"
    assert error["retryable"] is False
    assert error["correlation_id"]


def test_invalid_token_is_rejected(
    secured_client
):
    response = secured_client.post(
        "/sessions",
        headers={
            "Authorization": "Bearer wrong-token"
        }
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_valid_token_is_accepted(
    secured_client
):
    response = secured_client.post(
        "/sessions",
        headers=AUTH_HEADERS
    )

    assert response.status_code == 200
    assert response.json()["session"]["id"]


def test_health_endpoint_is_public(
    secured_client
):
    response = secured_client.get("/health")

    assert response.status_code == 200


def test_rate_limit_returns_typed_error(
    secured_client
):
    for _ in range(3):
        response = secured_client.post(
            "/sessions",
            headers=AUTH_HEADERS
        )

        assert response.status_code == 200

    response = secured_client.post(
        "/sessions",
        headers=AUTH_HEADERS
    )

    assert response.status_code == 429

    error = response.json()

    assert error["code"] == "RATE_LIMIT_EXCEEDED"
    assert error["retryable"] is True
    assert error["correlation_id"]
    assert "Retry-After" in response.headers


def test_security_error_preserves_correlation_id(
    secured_client
):
    response = secured_client.post(
        "/sessions",
        headers={
            "X-Correlation-ID": "week3-security-test"
        }
    )

    assert response.status_code == 401

    assert (
        response.json()["correlation_id"]
        == "week3-security-test"
    )

    assert (
        response.headers["X-Correlation-ID"]
        == "week3-security-test"
    )


def test_rate_limiter_separates_clients():
    limiter = RateLimiter(
        max_requests=2,
        window_seconds=60
    )

    assert limiter.allow("client-a") is True
    assert limiter.allow("client-a") is True
    assert limiter.allow("client-a") is False

    assert limiter.allow("client-b") is True


def test_missing_configured_token_fails_closed(
    monkeypatch
):
    monkeypatch.delenv(
        "LOCAL_AUTH_TOKEN",
        raising=False
    )

    authorization = LocalAuthorization()

    assert authorization.is_authorized(
        "Bearer any-token"
    ) is False
