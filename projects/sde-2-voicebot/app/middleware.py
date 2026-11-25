
import os
import uuid
import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings
from app.errors import create_error
from app.security import LocalAuthorization, RateLimiter


# Week 3 security configuration
auth_enabled = (
    os.getenv("LOCAL_AUTH_ENABLED", "true").lower()
    == "true"
)

rate_limit_enabled = (
    os.getenv("RATE_LIMIT_ENABLED", "true").lower()
    == "true"
)

authorization = LocalAuthorization()

rate_limiter = RateLimiter(
    max_requests=int(
        os.getenv("RATE_LIMIT_MAX_REQUESTS", "60")
    ),
    window_seconds=int(
        os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")
    )
)

PUBLIC_PATHS = {
    "/",
    "/health",
    "/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
}


def get_valid_id(value: str | None) -> str:
    if value and re.fullmatch(
        r"[a-zA-Z0-9_-]{1,128}", value
    ):
        return value

    return str(uuid.uuid4())


class RequestIDMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):

        request_id = get_valid_id(
            request.headers.get("X-Request-ID")
        )

        correlation_id = get_valid_id(
            request.headers.get("X-Correlation-ID")
        )

        request.state.request_id = request_id
        request.state.correlation_id = correlation_id

        response_headers = {
            "X-Request-ID": request_id,
            "X-Correlation-ID": correlation_id,
        }

        def error_response(
            status_code,
            code,
            message,
            details=None,
            retryable=False,
            extra_headers=None
        ):
            error = create_error(
                code=code,
                message=message,
                correlation_id=correlation_id,
                retryable=retryable,
                details=details,
            )

            headers = {
                **response_headers,
                **(extra_headers or {})
            }

            return JSONResponse(
                status_code=status_code,
                content=error.model_dump(),
                headers=headers,
            )

        # Week 3: Local authorization
        if (
            auth_enabled
            and request.url.path not in PUBLIC_PATHS
        ):
            auth_header = request.headers.get(
                "Authorization"
            )

            if not authorization.is_authorized(
                auth_header
            ):
                return error_response(
                    401,
                    "UNAUTHORIZED",
                    "Authorization is required.",
                    extra_headers={
                        "WWW-Authenticate": "Bearer"
                    }
                )

        # Week 3: Rate limiting
        if (
            rate_limit_enabled
            and request.url.path not in PUBLIC_PATHS
        ):
            client_id = (
                request.client.host
                if request.client
                else "unknown"
            )

            if not rate_limiter.allow(client_id):
                return error_response(
                    429,
                    "RATE_LIMIT_EXCEEDED",
                    "Too many requests. Please try again later.",
                    details={
                        "max_requests":
                            rate_limiter.max_requests,
                        "window_seconds":
                            rate_limiter.window_seconds
                    },
                    retryable=True,
                    extra_headers={
                        "Retry-After": str(
                            rate_limiter.window_seconds
                        )
                    }
                )

        # Existing Week 2 payload protection
        content_length = request.headers.get(
            "content-length"
        )

        if content_length is not None:
            try:
                payload_size = int(content_length)

            except ValueError:
                return error_response(
                    400,
                    "INVALID_CONTENT_LENGTH",
                    "The request contains an invalid content length."
                )

            if payload_size < 0:
                return error_response(
                    400,
                    "INVALID_CONTENT_LENGTH",
                    "The request contains an invalid content length."
                )

            if payload_size > settings.max_request_bytes:
                return error_response(
                    413,
                    "PAYLOAD_TOO_LARGE",
                    "The request payload exceeds the allowed size.",
                    details={
                        "max_request_bytes":
                            settings.max_request_bytes
                    }
                )

        # Validate actual request body size
        body = await request.body()

        if len(body) > settings.max_request_bytes:
            return error_response(
                413,
                "PAYLOAD_TOO_LARGE",
                "The request payload exceeds the allowed size.",
                details={
                    "max_request_bytes":
                        settings.max_request_bytes
                }
            )

        response = await call_next(request)

        response.headers["X-Request-ID"] = request_id

        response.headers[
            "X-Correlation-ID"
        ] = correlation_id

        return response
