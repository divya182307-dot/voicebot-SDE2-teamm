import pytest

from fastapi.testclient import TestClient
from app.main import app
from app import middleware
from app.security import LocalAuthorization, RateLimiter


def test_mock_session_pipeline(monkeypatch):
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
        RateLimiter(max_requests=60, window_seconds=60)
    )

    headers = {
        "Authorization": "Bearer test-only-token",
        "X-Correlation-ID": "integration-test"
    }

    with TestClient(app) as client:
        response = client.post("/sessions", headers=headers)

        assert response.status_code == 200

        session_id = response.json()["session"]["id"]

        response = client.post(
            f"/sessions/{session_id}/run",
            headers=headers
        )

        assert response.status_code == 200

        result = response.json()

        assert result["session_id"] == session_id
        assert result["correlation_id"] == "integration-test"
        assert result["status"] == "completed"
        assert result["audio_chunks"] > 0
        assert result["transcript"]
        assert result["reasoning"]["session_id"] == session_id
        assert result["reasoning"]["request_id"] == "integration-test"
        assert result["requires_user_approval"] is False
