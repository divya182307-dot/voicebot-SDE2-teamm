"""Automated test suite for Timeouts, Bounded Retries, and Error Normalization (Days 12–13 Milestone).

Verifies:
1. Bounded retry policy with exponential backoff and jitter.
2. Differentiating retryable transient errors vs non-retryable errors.
3. Timeout policy enforcement on slow operations.
4. Error normalizer translating raw vendor/socket/HTTP exceptions into domain errors.
5. Verification that no raw exceptions leak upstream.
6. ResilientTranscriberWrapper applying retries, timeouts, and error event emission.
7. Orchestrator integration with audio preprocessing and resilience layers.
"""

from __future__ import annotations

import asyncio
from typing import Any, List
import pytest

from src.voice.adapter import BaseTranscriber, TranscriberConfig
from src.voice.exceptions import (
    AudioPreprocessingError,
    TranscriberAudioError,
    TranscriberAuthenticationError,
    TranscriberConnectionError,
    TranscriberError,
    TranscriberRateLimitError,
    TranscriberServiceUnavailableError,
    TranscriberTimeoutError,
)
from src.voice.fake_transcriber import FakeTranscriber
from src.voice.orchestrator import OrchestratorConfig, TranscriptionOrchestrator
from src.voice.preprocessing import AudioPreprocessorConfig
from src.voice.resilience import (
    ErrorNormalizer,
    ResilienceMetrics,
    ResilientTranscriberWrapper,
    RetryConfig,
    RetryPolicy,
    TimeoutConfig,
    TimeoutPolicy,
)
from src.voice.schemas import TranscriptError, TranscriptEvent, TranscriptEventType


class TestRetryPolicy:
    """Validate bounded exponential backoff retries."""

    def test_transient_failure_recovers_on_retry(self):
        async def _run():
            attempts = 0
            metrics = ResilienceMetrics()
            policy = RetryPolicy(config=RetryConfig(max_retries=3, initial_delay_seconds=0.001))

            async def _flaky_operation():
                nonlocal attempts
                attempts += 1
                if attempts < 2:
                    raise ConnectionResetError("Simulated temporary connection drop")
                return "success"

            result = await policy.execute(_flaky_operation, metrics=metrics)
            assert result == "success"
            assert attempts == 2
            assert metrics.retries_attempted == 1
            assert metrics.retries_succeeded == 1
            assert metrics.retries_exhausted == 0

        asyncio.run(_run())

    def test_exhausted_retries_raises_normalized_error(self):
        async def _run():
            attempts = 0
            metrics = ResilienceMetrics()
            policy = RetryPolicy(config=RetryConfig(max_retries=2, initial_delay_seconds=0.001))

            async def _always_failing():
                nonlocal attempts
                attempts += 1
                raise ConnectionRefusedError("Simulated permanent server failure")

            with pytest.raises(TranscriberConnectionError, match="connection dropped or refused"):
                await policy.execute(_always_failing, metrics=metrics)

            assert attempts == 3  # initial + 2 retries
            assert metrics.retries_attempted == 2
            assert metrics.retries_exhausted == 1
            assert metrics.retries_succeeded == 0

        asyncio.run(_run())

    def test_non_retryable_error_fails_immediately(self):
        async def _run():
            attempts = 0
            metrics = ResilienceMetrics()
            policy = RetryPolicy(config=RetryConfig(max_retries=3, initial_delay_seconds=0.001))

            async def _auth_failure():
                nonlocal attempts
                attempts += 1
                raise ValueError("HTTP 401 Unauthorized: Invalid API key")

            with pytest.raises(TranscriberAuthenticationError, match="authentication or authorization failed"):
                await policy.execute(_auth_failure, metrics=metrics)

            # Must fail immediately on attempt 1 without retrying
            assert attempts == 1
            assert metrics.retries_attempted == 0
            assert metrics.retries_exhausted == 0

        asyncio.run(_run())

    def test_calculate_delay_bounds(self):
        policy = RetryPolicy(
            config=RetryConfig(
                max_retries=5,
                initial_delay_seconds=0.1,
                backoff_factor=2.0,
                max_delay_seconds=1.0,
                jitter=False,
            )
        )
        assert policy.calculate_delay(1) == 0.1
        assert policy.calculate_delay(2) == 0.2
        assert policy.calculate_delay(3) == 0.4
        assert policy.calculate_delay(4) == 0.8
        assert policy.calculate_delay(5) == 1.0  # capped at max_delay_seconds


class TestTimeoutPolicy:
    """Validate operation and chunk timeout enforcement."""

    def test_operation_within_deadline_succeeds(self):
        async def _run():
            policy = TimeoutPolicy(config=TimeoutConfig(chunk_timeout_seconds=0.5))

            async def _fast_op():
                await asyncio.sleep(0.01)
                return "done"

            result = await policy.execute(_fast_op, timeout_seconds=0.5)
            assert result == "done"

        asyncio.run(_run())

    def test_operation_exceeding_deadline_raises_timeout_error(self):
        async def _run():
            metrics = ResilienceMetrics()
            policy = TimeoutPolicy()

            async def _slow_op():
                await asyncio.sleep(0.2)
                return "done"

            with pytest.raises(TranscriberTimeoutError, match="exceeded configured timeout"):
                await policy.execute(_slow_op, timeout_seconds=0.01, metrics=metrics)

            assert metrics.timeouts_encountered == 1
            assert metrics.errors_normalized == 1

        asyncio.run(_run())


class TestErrorNormalizer:
    """Validate translation of raw system/vendor exceptions into domain taxonomy."""

    def test_normalize_socket_and_connection_errors(self):
        err = ErrorNormalizer.normalize_exception(ConnectionResetError("Socket reset by peer"))
        assert isinstance(err, TranscriberConnectionError)
        assert "Socket reset by peer" in err.message

    def test_normalize_asyncio_timeout(self):
        err = ErrorNormalizer.normalize_exception(asyncio.TimeoutError())
        assert isinstance(err, TranscriberTimeoutError)
        assert "timed out" in err.message

    def test_normalize_http_rate_limit_429(self):
        err = ErrorNormalizer.normalize_exception(RuntimeError("HTTP 429 Too Many Requests: Rate limit exceeded"))
        assert isinstance(err, TranscriberRateLimitError)

    def test_normalize_http_auth_401_403(self):
        err = ErrorNormalizer.normalize_exception(RuntimeError("ClientResponseError 403 Forbidden: Invalid token"))
        assert isinstance(err, TranscriberAuthenticationError)

    def test_normalize_service_unavailable_503(self):
        err = ErrorNormalizer.normalize_exception(RuntimeError("503 Service Unavailable: upstream overloaded"))
        assert isinstance(err, TranscriberServiceUnavailableError)

    def test_normalize_unknown_vendor_exception_never_leaks(self):
        class VendorWeirdException(Exception):
            pass

        err = ErrorNormalizer.normalize_exception(VendorWeirdException("Internal vendor engine failure"))
        assert isinstance(err, TranscriberError)
        assert "Internal vendor engine failure" in err.message

    def test_to_transcript_error_model(self):
        exc = ConnectionRefusedError("Port closed")
        t_err = ErrorNormalizer.to_transcript_error(exc)
        assert isinstance(t_err, TranscriptError)
        assert t_err.code == "CONNECTION_FAILED"
        assert "Port closed" in t_err.message

    def test_to_error_event_generation(self):
        exc = TimeoutError("Deadline reached")
        event = ErrorNormalizer.to_error_event(session_id="test-sess", exc=exc)
        assert isinstance(event, TranscriptEvent)
        assert event.event_type == TranscriptEventType.ERROR
        assert event.session_id == "test-sess"
        assert event.error is not None
        assert event.error.code == "TRANSCRIBER_TIMEOUT"


class DummyFailingTranscriber(BaseTranscriber):
    """Test transcriber with controllable failure simulation."""

    def __init__(self, session_id: str = "fail-sim"):
        super().__init__(session_id=session_id)
        self.chunk_attempts = 0

    async def _on_start(self) -> None:
        pass

    async def _on_stop(self) -> None:
        pass

    async def _process_audio_chunk(self, chunk: bytes) -> None:
        self.chunk_attempts += 1
        if self.chunk_attempts <= 2:
            raise ConnectionResetError("Transient network drop during chunk push")

    async def _on_finish_audio(self) -> None:
        pass


class TestResilientTranscriberWrapper:
    """Validate ResilientTranscriberWrapper behavior."""

    def test_wrapper_recovers_intermittent_chunk_failure(self):
        async def _run():
            dummy = DummyFailingTranscriber("wrap-01")
            wrapper = ResilientTranscriberWrapper(
                target_transcriber=dummy,
                retry_config=RetryConfig(max_retries=3, initial_delay_seconds=0.001),
                timeout_config=TimeoutConfig(chunk_timeout_seconds=1.0),
            )

            await wrapper.start()
            # Push chunk that fails twice and succeeds on 3rd attempt
            await wrapper.push_audio(b"\x00" * 3200)
            await wrapper.stop()

            assert dummy.chunk_attempts == 3
            assert wrapper.metrics.retries_attempted == 2
            assert wrapper.metrics.retries_succeeded == 1

        asyncio.run(_run())


class TestOrchestratorResilienceAndPreprocessingIntegration:
    """Validate full end-to-end integration of preprocessing & resilience in orchestrator."""

    def test_orchestrator_preprocesses_48k_audio_to_16k(self):
        async def _run():
            config = OrchestratorConfig(
                enable_preprocessing=True,
                preprocessor_config=AudioPreprocessorConfig(
                    target_sample_rate=16000,
                    enable_resampling=True,
                    enable_normalization=True,
                    normalization_method="peak",
                ),
            )
            orch = TranscriptionOrchestrator(
                session_id="prep-orch-01",
                script="Audio preprocessing integration test.",
                config=config,
            )
            await orch.start()

            # Push 48kHz audio (100ms at 48kHz = 4,800 samples = 9,600 bytes)
            raw_48k = b"\x10\x00" * 4800
            for _ in range(10):
                await orch.push_audio(raw_48k, sample_rate=48000)

            await orch.finish_audio()
            await orch.stop()

            # Verify preprocessing metric
            assert orch.metrics.chunks_preprocessed == 10
            # Transcriber received 16kHz audio and finalized speech
            assert orch.metrics.speech_turns_detected >= 1
            assert "Audio preprocessing" in orch.get_final_text()

        asyncio.run(_run())

    def test_orchestrator_normalizes_provider_error_without_leaking(self):
        """When provider fails, error is normalized into a TranscriptEvent(ERROR) without crashing."""
        async def _run():
            # Inject failure in FakeTranscriber after 3 chunks
            stt = FakeTranscriber(session_id="err-leak-test", error_after_chunks=3)
            orch = TranscriptionOrchestrator(
                session_id="err-leak-test",
                transcriber=stt,
            )
            await orch.start()

            chunk = b"\x00" * 3200
            for _ in range(5):
                await orch.push_audio(chunk)

            await orch.finish_audio()
            await orch.stop()

            # Error event must be in history
            error_events = [e for e in orch.events_history if e.event_type == TranscriptEventType.ERROR]
            assert len(error_events) >= 1
            assert error_events[0].error is not None
            assert error_events[0].error.code in ("SIMULATED_TRANSCRIBER_ERROR", "PROVIDER_ERROR")
            assert len(orch.accumulator.errors) >= 1

        asyncio.run(_run())

