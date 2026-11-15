
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

        # Validate declared request payload size.
        content_length = request.headers.get("content-length")

        if content_length is not None:
            try:
                payload_size = int(content_length)
            except ValueError:
                error = create_error(
                    code="INVALID_CONTENT_LENGTH",
                    message="The request contains an invalid content length.",
                    correlation_id=correlation_id,
                    retryable=False
                )
                return JSONResponse(
                    status_code=400,
                    content=error.model_dump(),
                    headers={
                        "X-Request-ID": request_id,
                        "X-Correlation-ID": correlation_id
                    }
                )

            if payload_size < 0:
                error = create_error(
                    code="INVALID_CONTENT_LENGTH",
                    message="The request contains an invalid content length.",
                    correlation_id=correlation_id,
                    retryable=False
                )
                return JSONResponse(
                    status_code=400,
                    content=error.model_dump(),
                    headers={
                        "X-Request-ID": request_id,
                        "X-Correlation-ID": correlation_id
                    }
                )

            if payload_size > settings.max_request_bytes:
                error = create_error(
                    code="PAYLOAD_TOO_LARGE",
                    message="The request payload exceeds the allowed size.",
                    correlation_id=correlation_id,
                    retryable=False,
                    details={
                        "max_request_bytes": settings.max_request_bytes
                    }
                )
                return JSONResponse(
                    status_code=413,
                    content=error.model_dump(),
                    headers={
                        "X-Request-ID": request_id,
                        "X-Correlation-ID": correlation_id
                    }
                )

        response = await call_next(request)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id

        return response
