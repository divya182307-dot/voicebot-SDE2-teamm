
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_mode: str
    session_ttl_seconds: int
    max_request_bytes: int
    log_level: str


def load_settings() -> Settings:
    app_mode = os.getenv("APP_MODE", "mock").strip().lower()
    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()

    try:
        session_ttl = int(os.getenv("SESSION_TTL_SECONDS", "1800"))
        max_request_bytes = int(os.getenv("MAX_REQUEST_BYTES", "1048576"))
    except ValueError as exc:
        raise RuntimeError(
            "SESSION_TTL_SECONDS and MAX_REQUEST_BYTES must be integers."
        ) from exc

    if app_mode not in {"mock", "provider"}:
        raise RuntimeError(
            "APP_MODE must be either 'mock' or 'provider'."
        )

    if session_ttl <= 0:
        raise RuntimeError(
            "SESSION_TTL_SECONDS must be greater than zero."
        )

    if max_request_bytes <= 0:
        raise RuntimeError(
            "MAX_REQUEST_BYTES must be greater than zero."
        )

    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise RuntimeError(
            "LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL."
        )

    return Settings(
        app_mode=app_mode,
        session_ttl_seconds=session_ttl,
        max_request_bytes=max_request_bytes,
        log_level=log_level,
    )


settings = load_settings()
