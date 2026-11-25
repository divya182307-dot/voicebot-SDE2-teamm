
import uuid
import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings
from app.errors import create_error


def get_valid_id(value: str | None) -> str:
    if value and re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", value):
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

        def error_response(status_code, code, message, details=None):
            error = create_error(
                code=code,
                message=message,
                correlation_id=correlation_id,
                retryable=False,
                details=details,
            )
            return JSONResponse(
                status_code=status_code,
                content=error.model_dump(),
                headers=response_headers,
            )

        content_length = request.headers.get("content-length")

        if content_length is not None:
            try:
                payload_size = int(content_length)
            except ValueError:
                return error_response(
                    400,
                    "INVALID_CONTENT_LENGTH",
                    "The request contains an invalid content length.",
                )

            if payload_size < 0:
                return error_response(
                    400,
                    "INVALID_CONTENT_LENGTH",
                    "The request contains an invalid content length.",
                )

            if payload_size > settings.max_request_bytes:
                return error_response(
                    413,
                    "PAYLOAD_TOO_LARGE",
                    "The request payload exceeds the allowed size.",
                    {"max_request_bytes": settings.max_request_bytes},
                )

        # Read the body and enforce the limit against actual bytes.
        body = await request.body()

        if len(body) > settings.max_request_bytes:
            return error_response(
                413,
                "PAYLOAD_TOO_LARGE",
                "The request payload exceeds the allowed size.",
                {"max_request_bytes": settings.max_request_bytes},
            )

        response = await call_next(request)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id

        return response
