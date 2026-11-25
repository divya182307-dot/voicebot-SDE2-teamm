
"""Local authorization and rate limiting for Week 3."""

import os
import secrets
import time

from collections import defaultdict, deque
from threading import Lock


class LocalAuthorization:

    def __init__(self):
        self.token = os.getenv(
            "LOCAL_AUTH_TOKEN", ""
        ).strip()

    def is_authorized(
        self,
        authorization: str | None
    ) -> bool:

        if not self.token:
            return False

        if not authorization:
            return False

        scheme, _, token = authorization.partition(" ")

        if scheme.lower() != "bearer":
            return False

        return secrets.compare_digest(
            token.encode("utf-8"),
            self.token.encode("utf-8")
        )


class RateLimiter:

    def __init__(
        self,
        max_requests: int = 60,
        window_seconds: int = 60
    ):
        if max_requests <= 0 or window_seconds <= 0:
            raise ValueError(
                "Rate limit settings must be positive."
            )

        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = defaultdict(deque)
        self.lock = Lock()

    def allow(self, client_id: str) -> bool:

        now = time.monotonic()

        with self.lock:
            timestamps = self.requests[client_id]

            while timestamps and (
                now - timestamps[0]
                >= self.window_seconds
            ):
                timestamps.popleft()

            if len(timestamps) >= self.max_requests:
                return False

            timestamps.append(now)

            return True
