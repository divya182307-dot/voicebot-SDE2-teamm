"""Resilience layer: Timeouts, bounded retries, and error normalization.

This module provides fault-tolerance primitives for Speech-to-Text operations:
1. Bounded exponential backoff retries with jitter.
2. Configurable timeouts for connection, chunk processing, and operations.
3. Strict error normalization: translates raw vendor, socket, and system exceptions
   into domain TranscriberError exceptions and TranscriptError event models so that
   no raw vendor exceptions ever leak upstream.
4. Resilient adapter wrapper decorating any BaseTranscriber implementation.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
import random
import sys
import time
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    Type,
    Union,
)

from pydantic import BaseModel, ConfigDict, Field

from src.voice.adapter import BaseTranscriber, TranscriberConfig, TranscriberState
from src.voice.exceptions import (
    RetryExhaustedError,
    TranscriberAudioError,
    TranscriberAuthenticationError,
    TranscriberConnectionError,
    TranscriberError,
    TranscriberRateLimitError,
    TranscriberServiceUnavailableError,
    TranscriberStateError,
    TranscriberTimeoutError,
    VoiceError,
)
from src.voice.schemas import (
    TranscriptError,
    TranscriptEvent,
    TranscriptEventType,
)

logger = logging.getLogger(__name__)


# Standard transient network & socket exception types across platforms
RETRYABLE_SYSTEM_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    asyncio.TimeoutError,
    TimeoutError,
    ConnectionRefusedError,
    ConnectionResetError,
    ConnectionAbortedError,
    BrokenPipeError,
    OSError,
)


class RetryConfig(BaseModel):
    """Configuration for bounded exponential backoff retries."""

    model_config = ConfigDict(extra="forbid")

    max_retries: int = Field(default=3, ge=0, le=10, description="Maximum number of retry attempts")
    initial_delay_seconds: float = Field(default=0.05, ge=0.001, le=10.0, description="Base delay before first retry")
    max_delay_seconds: float = Field(default=1.0, ge=0.01, le=60.0, description="Maximum delay cap for backoff")
    backoff_factor: float = Field(default=2.0, ge=1.0, le=10.0, description="Multiplicative exponential backoff multiplier")
    jitter: bool = Field(default=True, description="Add random uniform jitter to delay to avoid thundering herds")


class TimeoutConfig(BaseModel):
    """Configuration for operation, connection, and streaming chunk timeouts."""

    model_config = ConfigDict(extra="forbid")

    connect_timeout_seconds: float = Field(default=3.0, ge=0.1, le=60.0, description="Max seconds to connect/handshake")
    chunk_timeout_seconds: float = Field(default=1.5, ge=0.05, le=30.0, description="Max seconds to process an audio chunk")
    operation_timeout_seconds: float = Field(default=10.0, ge=0.5, le=300.0, description="Max seconds for complete batch transcription")


class ResilienceMetrics(BaseModel):
    """Telemetry tracking retry attempts, timeouts, and normalized exceptions."""

    model_config = ConfigDict(extra="forbid")

    retries_attempted: int = Field(default=0, ge=0, description="Total retry attempts executed")
    retries_succeeded: int = Field(default=0, ge=0, description="Total operations that succeeded after retry")
    retries_exhausted: int = Field(default=0, ge=0, description="Total operations where all retries failed")
    timeouts_encountered: int = Field(default=0, ge=0, description="Count of timeout events caught")
    errors_normalized: int = Field(default=0, ge=0, description="Count of raw exceptions normalized into domain models")


class ErrorNormalizer:
    """Normalizes raw system, network, HTTP, and vendor exceptions into domain errors.

    Ensures that raw provider exceptions (e.g., ConnectionResetError, asyncio.TimeoutError,
    vendor 429 ClientResponseError, etc.) are strictly translated into our domain taxonomy
    without ever leaking unhandled raw exceptions upstream.
    """

    @classmethod
    def normalize_exception(
        cls,
        exc: Exception,
        context: Optional[dict[str, Any]] = None,
    ) -> TranscriberError:
        """Translate an arbitrary exception into a strongly-typed TranscriberError subclass.

        Args:
            exc: The caught raw exception.
            context: Optional diagnostic dictionary (session_id, chunk_index, etc.).

        Returns:
            A normalized TranscriberError subclass instance.
        """
        details = dict(context or {})
        details["original_error_type"] = type(exc).__name__
        details["original_error_message"] = str(exc)

        # 1. Already a typed domain TranscriberError
        if isinstance(exc, TranscriberError):
            if context and hasattr(exc, "details"):
                exc.details.update(context)
            return exc

        # 2. Timeout errors
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            return TranscriberTimeoutError(
                f"STT operation timed out: {exc or 'operation exceeded deadline'}",
                details=details,
            )

        # 3. Connection and socket errors
        if isinstance(exc, (ConnectionRefusedError, ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return TranscriberConnectionError(
                f"STT provider connection dropped or refused: {exc}",
                details=details,
            )

        # 4. Check message / string signatures for HTTP status codes and vendor errors
        msg_lower = str(exc).lower()
        err_type_lower = type(exc).__name__.lower()

        # Rate limit (HTTP 429 / quota exceeded)
        if "429" in msg_lower or "rate limit" in msg_lower or "quota" in msg_lower:
            return TranscriberRateLimitError(
                f"STT provider rate limit or quota exceeded: {exc}",
                details=details,
            )

        # Authentication / Authorization (HTTP 401 / 403 / unauthorized)
        if "401" in msg_lower or "403" in msg_lower or "unauthorized" in msg_lower or "auth" in msg_lower or "api key" in msg_lower:
            return TranscriberAuthenticationError(
                f"STT provider authentication or authorization failed: {exc}",
                details=details,
            )

        # Service unavailable / 5xx server errors
        if any(code in msg_lower for code in ("500", "502", "503", "504")) or "unavailable" in msg_lower or "bad gateway" in msg_lower:
            return TranscriberServiceUnavailableError(
                f"STT provider service is temporarily unavailable: {exc}",
                details=details,
            )

        # Audio format / data validation errors
        if isinstance(exc, (ValueError, TypeError)) and any(term in msg_lower for term in ("audio", "sample", "format", "pcm", "channel")):
            return TranscriberAudioError(
                f"Invalid or malformed audio data: {exc}",
                details=details,
            )

        # Generic socket / OS errors
        if isinstance(exc, OSError):
            return TranscriberConnectionError(
                f"STT transport/socket I/O error: {exc}",
                details=details,
            )

        # 5. Fallback catch-all: wrap in base TranscriberError so raw exception NEVER leaks
        return TranscriberError(
            f"STT provider operation failed: {exc}",
            details=details,
        )

    @classmethod
    def to_transcript_error(
        cls,
        exc: Exception,
        context: Optional[dict[str, Any]] = None,
    ) -> TranscriptError:
        """Convert any caught exception into a standardized TranscriptError schema model."""
        norm_exc = cls.normalize_exception(exc, context)

        # Determine standardized machine-readable error code
        if isinstance(norm_exc, TranscriberTimeoutError):
            code = "TRANSCRIBER_TIMEOUT"
        elif isinstance(norm_exc, TranscriberRateLimitError):
            code = "RATE_LIMIT_EXCEEDED"
        elif isinstance(norm_exc, TranscriberAuthenticationError):
            code = "AUTHENTICATION_FAILED"
        elif isinstance(norm_exc, TranscriberServiceUnavailableError):
            code = "SERVICE_UNAVAILABLE"
        elif isinstance(norm_exc, TranscriberConnectionError):
            code = "CONNECTION_FAILED"
        elif isinstance(norm_exc, TranscriberAudioError):
            code = "AUDIO_MALFORMED"
        elif isinstance(norm_exc, TranscriberStateError):
            code = "INVALID_STATE"
        else:
            code = "PROVIDER_ERROR"

        return TranscriptError(
            code=code,
            message=norm_exc.message,
            details=norm_exc.details if norm_exc.details else None,
        )

    @classmethod
    def to_error_event(
        cls,
        session_id: str,
        exc: Exception,
        event_id: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> TranscriptEvent:
        """Create a canonical TranscriptEvent with event_type=ERROR from an exception."""
        import uuid
        error_payload = cls.to_transcript_error(exc, context)
        return TranscriptEvent(
            event_id=event_id or f"err-{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            event_type=TranscriptEventType.ERROR,
            error=error_payload,
        )


class RetryPolicy:
    """Bounded exponential backoff retry executor with jitter."""

    def __init__(
        self,
        config: Optional[RetryConfig] = None,
        retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
    ) -> None:
        """Initialize retry policy.

        Args:
            config: Optional retry configuration flags.
            retryable_exceptions: Optional tuple of exception types that should trigger a retry.
        """
        self._config: RetryConfig = config or RetryConfig()
        self._retryable_exceptions: Tuple[Type[Exception], ...] = (
            retryable_exceptions
            if retryable_exceptions is not None
            else (
                RETRYABLE_SYSTEM_EXCEPTIONS
                + (
                    TranscriberConnectionError,
                    TranscriberTimeoutError,
                    TranscriberRateLimitError,
                    TranscriberServiceUnavailableError,
                )
            )
        )

    @property
    def config(self) -> RetryConfig:
        return self._config

    def is_retryable(self, exc: Exception) -> bool:
        """Return True if exception represents a transient failure eligible for retry."""
        # Non-retryable domain errors: Auth failures and audio format bugs should never retry
        if isinstance(exc, (TranscriberAuthenticationError, TranscriberAudioError, TranscriberStateError)):
            return False

        # First check direct exception types
        if isinstance(exc, self._retryable_exceptions):
            return True

        # Check normalized representation
        normalized = ErrorNormalizer.normalize_exception(exc)
        if isinstance(normalized, (TranscriberConnectionError, TranscriberTimeoutError,
                                   TranscriberRateLimitError, TranscriberServiceUnavailableError)):
            return True

        return False

    def calculate_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay for given retry attempt (1-indexed)."""
        backoff = self._config.initial_delay_seconds * (self._config.backoff_factor ** (attempt - 1))
        capped = min(backoff, self._config.max_delay_seconds)
        if self._config.jitter:
            # Full jitter: random uniform between 0 and capped delay
            return random.uniform(0.5 * capped, capped)
        return capped

    async def execute(
        self,
        coro_fn: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        metrics: Optional[ResilienceMetrics] = None,
        context: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """Execute an asynchronous coroutine function with bounded retries.

        Args:
            coro_fn: The async function to call.
            args: Positional arguments for coro_fn.
            metrics: Optional telemetry metrics object to update.
            context: Diagnostic details for error normalization.
            kwargs: Keyword arguments for coro_fn.

        Returns:
            The return value of coro_fn upon success.

        Raises:
            TranscriberError: Normalized domain error if retries are exhausted or non-retryable.
        """
        attempt = 0
        last_exception: Optional[Exception] = None

        while True:
            try:
                result = await coro_fn(*args, **kwargs)
                if attempt > 0 and metrics:
                    metrics.retries_succeeded += 1
                return result

            except Exception as exc:
                last_exception = exc
                if metrics:
                    metrics.errors_normalized += 1

                # Normalize to check retry eligibility
                normalized = ErrorNormalizer.normalize_exception(exc, context)

                if attempt >= self._config.max_retries or not self.is_retryable(normalized):
                    if attempt >= self._config.max_retries and metrics:
                        metrics.retries_exhausted += 1
                    logger.error(
                        "Operation '%s' failed (attempt %d/%d, retryable=%s): %s",
                        getattr(coro_fn, "__name__", str(coro_fn)),
                        attempt + 1,
                        self._config.max_retries + 1,
                        self.is_retryable(normalized),
                        normalized,
                    )
                    raise normalized from exc

                attempt += 1
                if metrics:
                    metrics.retries_attempted += 1

                delay = self.calculate_delay(attempt)
                logger.warning(
                    "Operation '%s' failed on attempt %d with %s. Retrying in %.3fs...",
                    getattr(coro_fn, "__name__", str(coro_fn)),
                    attempt,
                    type(exc).__name__,
                    delay,
                )
                await asyncio.sleep(delay)


class TimeoutPolicy:
    """Execution wrapper enforcing bounded execution time limits."""

    def __init__(self, config: Optional[TimeoutConfig] = None) -> None:
        self._config: TimeoutConfig = config or TimeoutConfig()

    @property
    def config(self) -> TimeoutConfig:
        return self._config

    async def execute(
        self,
        coro_fn: Callable[..., Coroutine[Any, Any, Any]],
        timeout_seconds: float,
        *args: Any,
        metrics: Optional[ResilienceMetrics] = None,
        context: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """Run coroutine wrapped in an asyncio.wait_for timeout.

        Raises:
            TranscriberTimeoutError: If operation exceeds timeout_seconds.
        """
        try:
            return await asyncio.wait_for(coro_fn(*args, **kwargs), timeout=timeout_seconds)
        except (asyncio.TimeoutError, TimeoutError) as exc:
            if metrics:
                metrics.timeouts_encountered += 1
                metrics.errors_normalized += 1
            details = dict(context or {})
            details["timeout_seconds"] = timeout_seconds
            norm_err = TranscriberTimeoutError(
                f"Operation exceeded configured timeout of {timeout_seconds:.2f}s",
                details=details,
            )
            raise norm_err from exc


class ResilientTranscriberWrapper(BaseTranscriber):
    """Fault-tolerant adapter wrapper applying timeouts, retries, and error normalization.

    Wraps any BaseTranscriber (including FakeTranscriber or vendor adapters), ensuring:
    - Bounded retries on transient connection or transport errors.
    - Timeouts on start, push_audio, and finish_audio.
    - Zero leaked raw exceptions: all failures are normalized and emitted as TranscriptEvent(ERROR).
    """

    def __init__(
        self,
        target_transcriber: BaseTranscriber,
        retry_config: Optional[RetryConfig] = None,
        timeout_config: Optional[TimeoutConfig] = None,
    ) -> None:
        super().__init__(
            session_id=target_transcriber.session_id,
            config=target_transcriber.config,
        )
        self._target: BaseTranscriber = target_transcriber
        self._retry_policy = RetryPolicy(config=retry_config)
        self._timeout_policy = TimeoutPolicy(config=timeout_config)
        self._metrics: ResilienceMetrics = ResilienceMetrics()

        # Wire target events directly into our listeners/subscribers
        self._target.add_event_listener(self._on_target_event)

    @property
    def target(self) -> BaseTranscriber:
        return self._target

    @property
    def metrics(self) -> ResilienceMetrics:
        return self._metrics.model_copy()

    @property
    def retry_policy(self) -> RetryPolicy:
        return self._retry_policy

    @property
    def timeout_policy(self) -> TimeoutPolicy:
        return self._timeout_policy

    def _on_target_event(self, event: TranscriptEvent) -> None:
        """Forward target transcriber events out through our broadcaster."""
        asyncio.create_task(self._emit_event(event))

    async def _on_start(self) -> None:
        """Start target adapter with timeout and bounded retries."""
        timeout = self._timeout_policy.config.connect_timeout_seconds

        async def _do_start() -> None:
            await self._timeout_policy.execute(
                self._target.start,
                timeout_seconds=timeout,
                metrics=self._metrics,
                context={"action": "start", "session_id": self._session_id},
            )

        try:
            await self._retry_policy.execute(
                _do_start,
                metrics=self._metrics,
                context={"action": "start", "session_id": self._session_id},
            )
        except Exception as exc:
            # Emit normalized error event
            error_event = ErrorNormalizer.to_error_event(
                session_id=self._session_id,
                exc=exc,
                context={"phase": "start"},
            )
            await self._emit_event(error_event)
            raise

    async def _on_stop(self) -> None:
        """Stop target adapter."""
        if not self._target.is_closed:
            await self._target.stop()

    async def _process_audio_chunk(self, chunk: bytes) -> None:
        """Push chunk to target adapter guarded by timeout and retries."""
        timeout = self._timeout_policy.config.chunk_timeout_seconds

        async def _do_push() -> None:
            await self._timeout_policy.execute(
                self._target.push_audio,
                timeout_seconds=timeout,
                chunk=chunk,
                metrics=self._metrics,
                context={"action": "push_audio", "chunk_len": len(chunk)},
            )

        try:
            await self._retry_policy.execute(
                _do_push,
                metrics=self._metrics,
                context={"action": "push_audio", "chunk_len": len(chunk)},
            )
        except Exception as exc:
            # Emit normalized error event
            error_event = ErrorNormalizer.to_error_event(
                session_id=self._session_id,
                exc=exc,
                context={"phase": "push_audio", "chunk_len": len(chunk)},
            )
            await self._emit_event(error_event)
            raise

    async def _on_finish_audio(self) -> None:
        """Signal finish to target adapter."""
        timeout = self._timeout_policy.config.operation_timeout_seconds

        async def _do_finish() -> None:
            await self._timeout_policy.execute(
                self._target.finish_audio,
                timeout_seconds=timeout,
                metrics=self._metrics,
                context={"action": "finish_audio"},
            )

        try:
            await self._retry_policy.execute(
                _do_finish,
                metrics=self._metrics,
                context={"action": "finish_audio"},
            )
        except Exception as exc:
            error_event = ErrorNormalizer.to_error_event(
                session_id=self._session_id,
                exc=exc,
                context={"phase": "finish_audio"},
            )
            await self._emit_event(error_event)
            raise

