
from pydantic import BaseModel
from typing import Any


class ErrorEnvelope(BaseModel):
    code: str
    message_safe_for_user: str
    retryable: bool
    correlation_id: str
    details_redacted: dict[str, Any]


def create_error(
    code: str,
    message: str,
    correlation_id: str,
    retryable: bool = False,
    details: dict | None = None
):
    return ErrorEnvelope(
        code=code,
        message_safe_for_user=message,
        retryable=retryable,
        correlation_id=correlation_id,
        details_redacted=details or {}
    )
