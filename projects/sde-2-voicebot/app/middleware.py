import uuid
import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


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

        response = await call_next(request)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id

        return response