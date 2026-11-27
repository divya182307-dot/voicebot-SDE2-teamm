"""Shared test fixtures for authenticated backend API tests."""

import pytest

from fastapi.testclient import TestClient

from app.main import app
from app import middleware
from app.security import LocalAuthorization, RateLimiter


TEST_TOKEN = "test-only-token"


@pytest.fixture
def auth_headers():
    return {
        "Authorization": f"Bearer {TEST_TOKEN}"
    }


@pytest.fixture
def authenticated_client(monkeypatch, auth_headers):
    """Provide an authenticated client with isolated security state."""

    monkeypatch.setenv("LOCAL_AUTH_TOKEN", TEST_TOKEN)

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
        RateLimiter(
            max_requests=60,
            window_seconds=60
        )
    )

    with TestClient(app, headers=auth_headers) as client:
        yield client
