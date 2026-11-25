import pytest

from fastapi.testclient import TestClient
from app.main import app
from app import middleware
from app.security import LocalAuthorization, RateLimiter


@pytest.fixture
def secured_client(monkeypatch):
    monkeypatch.setenv("LOCAL_AUTH_TOKEN", "test-only-token")

    monkeypatch.setattr(middleware, "auth_enabled", True)
    monkeypatch.setattr(middleware, "rate_limit_enabled", True)

    monkeypatch.setattr(
        middleware,
        "authorization",
        LocalAuthorization()
    )

    monkeypatch.setattr(
        middleware,
        "rate_limiter",
        RateLimiter(max_requests=3, window_seconds=60)
    )

    with TestClient(app) as client:
        yield client


AUTH_HEADERS = {
    "Authorization": "Bearer test-only-token"
}


def test_missing_authorization_is_rejected(secured_client):
    response = secured_client.post("/sessions")

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
    assert response.json()["retryable"] is False
    assert response.json()["correlation_id"]


def test_invalid_token_is_rejected(secured_client):
    response = secured_client.post(
        "/sessions",
        headers={"Authorization": "Bearer wrong-token"}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_valid_token_is_accepted(secured_client):
    response = secured_client.post(
        "/sessions",
        headers=AUTH_HEADERS
    )

    assert response.status_code == 200
    assert response.json()["session"]["id"]


def test_health_endpoint_is_public(secured_client):
    response = secured_client.get("/health")

    assert response.status_code == 200


def test_rate_limit_returns_typed_error(secured_client):
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
    assert response.json()["code"] == "RATE_LIMIT_EXCEEDED"
    assert response.json()["retryable"] is True
    assert response.json()["correlation_id"]
    assert "Retry-After" in response.headers


def test_security_error_preserves_correlation_id(secured_client):
    response = secured_client.post(
        "/sessions",
        headers={"X-Correlation-ID": "week3-security-test"}
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


def test_missing_configured_token_fails_closed(monkeypatch):
    monkeypatch.delenv("LOCAL_AUTH_TOKEN", raising=False)

    authorization = LocalAuthorization()

    assert authorization.is_authorized(
        "Bearer any-token"
    ) is False
