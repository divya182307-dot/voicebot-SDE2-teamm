"""Gateway connecting backend sessions to the reasoning module."""

import logging

from app.reasoning.mock_engine import (
    DeterministicMockReasoningEngine
)

from app.schemas.reasoning import (
    ReasoningRequest,
    ReasoningResult
)


logger = logging.getLogger("voicebot.reasoning_gateway")


class ReasoningGateway:

    def __init__(self):
        self.engine = DeterministicMockReasoningEngine()

    def reason(
        self,
        session_id: str,
        correlation_id: str,
        transcript: str
    ) -> ReasoningResult:

        log_context = {
            "session_id": session_id,
            "correlation_id": correlation_id
        }

        logger.info(
            "Reasoning started",
            extra=log_context
        )

        try:
            request = ReasoningRequest(
                request_id=correlation_id,
                session_id=session_id,
                user_query=transcript
            )

            result = self.engine.reason(request)

            logger.info(
                "Reasoning completed",
                extra=log_context
            )

            return result

        except Exception:
            logger.exception(
                "Reasoning failed",
                extra=log_context
            )

            raise
