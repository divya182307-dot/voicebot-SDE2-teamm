"""Tests for Day 17-18: In-flight cancellation and automatic fallback to mock provider.

Verifies:
1. Clean in-flight transcription cancellation (state transitions, queue draining, subscriber termination).
2. Automatic fallback to FakeTranscriber mock provider upon quota (429) exhaustion.
3. Automatic fallback upon network failures (connection drops, resets, timeouts).
4. Error normalization guarantee: zero raw vendor exceptions leak.
5. Component-level fallback in ResilientTranscriberWrapper.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, List, Optional
import pytest

from src.voice.adapter import AudioConfig, BaseTranscriber, TranscriberConfig
from src.voice.exceptions import (
    OrchestratorStateError,
    TranscriberConnectionError,
    TranscriberError,
    TranscriberQuotaExceededError,
    TranscriberRateLimitError,
    TranscriberTimeoutError,
)
from src.voice.fake_transcriber import FakeTranscriber
from src.voice.orchestrator import OrchestratorConfig, OrchestratorState, TranscriptionOrchestrator
from src.voice.resilience import ResilientTranscriberWrapper, RetryConfig, TimeoutConfig
from src.voice.schemas import TranscriptEvent, TranscriptEventType


# ==============================================================================
# Failing Provider Mock for Chaos / Failure Injection
# ==============================================================================

class ChaosTranscriber(BaseTranscriber):
    """Synthetic transcriber that injects quota, network, or timeout failures for resilience testing."""

    def __init__(
        self,
        session_id: str = "chaos-session",
        fail_on_start: Optional[Exception] = None,
        fail_on_push_after_chunks: int = -1,
        fail_on_push_exc: Optional[Exception] = None,
        fail_on_finish: Optional[Exception] = None,
        config: Optional[TranscriberConfig] = None,
    ) -> None:
        super().__init__(session_id=session_id, config=config)
        self.fail_on_start = fail_on_start
        self.fail_on_push_after_chunks = fail_on_push_after_chunks
        self.fail_on_push_exc = fail_on_push_exc
        self.fail_on_finish = fail_on_finish
        self.chunks_received: int = 0

    async def _on_start(self) -> None:
        if self.fail_on_start:
            raise self.fail_on_start

    async def _on_stop(self) -> None:
        pass

    async def _process_audio_chunk(self, chunk: bytes) -> None:
        self.chunks_received += 1
        if self.fail_on_push_after_chunks >= 0 and self.chunks_received >= self.fail_on_push_after_chunks:
            exc = self.fail_on_push_exc or ConnectionResetError("Remote STT provider reset peer connection")
            raise exc

    async def _on_finish_audio(self) -> None:
        if self.fail_on_finish:
            raise self.fail_on_finish


# ==============================================================================
# 1. Clean Cancellation Tests
# ==============================================================================

class TestTranscriptionCancellation:
    """Validate in-flight cancellation lifecycle, queue draining, and subscriber clean-up."""

    @pytest.mark.anyio
    async def test_clean_cancellation_in_running_state(self):
        orch = TranscriptionOrchestrator(
            session_id="cancel-session-1",
            script="This speech will be cancelled mid-stream.",
        )
        await orch.start()
        assert orch.state == OrchestratorState.RUNNING

        # Push some audio chunks
        chunk = b"\x00" * 3200
        for _ in range(3):
            await orch.push_audio(chunk)

        # Cancel in-flight transcription
        await orch.cancel(reason="User pressed stop button")

        assert orch.state == OrchestratorState.CANCELLED
        assert orch.is_cancelled is True
        assert orch.is_closed is True
        assert orch.metrics.cancellations_count == 1

    @pytest.mark.anyio
    async def test_cancellation_is_idempotent(self):
        orch = TranscriptionOrchestrator(session_id="cancel-session-2")
        await orch.start()

        await orch.cancel(reason="First cancel call")
        assert orch.state == OrchestratorState.CANCELLED

        # Second call must not raise and must keep state unchanged
        await orch.cancel(reason="Duplicate cancel call")
        assert orch.state == OrchestratorState.CANCELLED
        assert orch.metrics.cancellations_count == 1

    @pytest.mark.anyio
    async def test_push_audio_after_cancellation_raises_error(self):
        orch = TranscriptionOrchestrator(session_id="cancel-session-3")
        await orch.start()
        await orch.cancel()

        chunk = b"\x00" * 3200
        with pytest.raises(OrchestratorStateError, match="cancelled"):
            await orch.push_audio(chunk)

    @pytest.mark.anyio
    async def test_finish_audio_after_cancellation_raises_error(self):
        orch = TranscriptionOrchestrator(session_id="cancel-session-4")
        await orch.start()
        await orch.cancel()

        with pytest.raises(OrchestratorStateError, match="cancelled"):
            await orch.finish_audio()

    @pytest.mark.anyio
    async def test_cancel_terminates_stream_subscriber_without_hanging(self):
        orch = TranscriptionOrchestrator(
            session_id="cancel-session-5",
            script="Subscriber termination test.",
        )
        await orch.start()

        consumed_events = []

        async def _consumer():
            async for event in orch.stream():
                consumed_events.append(event)

        consumer_task = asyncio.create_task(_consumer())

        # Push one chunk
        await orch.push_audio(b"\x00" * 3200)
        await asyncio.sleep(0.05)

        # Cancel orchestrator
        await orch.cancel(reason="Stream aborted")

        # Consumer loop must exit promptly without hanging
        await asyncio.wait_for(consumer_task, timeout=2.0)
        assert orch.is_cancelled is True


# ==============================================================================
# 2. Quota Failure Fallback Tests
# ==============================================================================

class TestQuotaFailureFallback:
    """Validate automatic fallback to mock provider when primary provider hits quota limits."""

    @pytest.mark.anyio
    async def test_quota_429_on_push_falls_back_to_mock_provider(self):
        # Setup chaos provider that fails on 2nd chunk with HTTP 429 quota exhausted
        primary = ChaosTranscriber(
            session_id="quota-fallback-1",
            fail_on_push_after_chunks=2,
            fail_on_push_exc=Exception("HTTP 429: monthly quota limit exceeded for speech-to-text API"),
        )

        cfg = OrchestratorConfig(
            enable_mock_fallback=True,
            fallback_script="Recovered using synthetic mock provider.",
            retry_config=RetryConfig(max_retries=1, initial_delay_seconds=0.01),
        )

        orch = TranscriptionOrchestrator(
            session_id="quota-fallback-1",
            transcriber=primary,
            config=cfg,
        )

        await orch.start()

        # Push chunks
        chunk = b"\x00" * 3200
        for _ in range(5):
            await orch.push_audio(chunk)

        await orch.finish_audio()
        await orch.stop()

        # Verify fallback was triggered
        assert orch.is_fallback_active is True
        assert orch.metrics.fallbacks_triggered == 1

        # Verify normalized error event was emitted without leaking raw exception
        events = orch.events_history
        error_events = [e for e in events if e.event_type == TranscriptEventType.ERROR]
        assert len(error_events) >= 1
        err_payload = error_events[0].error
        assert err_payload is not None
        assert err_payload.code in ("QUOTA_EXCEEDED", "RATE_LIMIT_EXCEEDED")
        assert "quota" in err_payload.message.lower()

        # Verify transcript events continued and finished cleanly via fallback
        final_events = [e for e in events if e.event_type == TranscriptEventType.FINAL_TRANSCRIPT]
        assert len(final_events) >= 1
        assert "synthetic mock provider" in orch.get_final_text().lower()

    @pytest.mark.anyio
    async def test_quota_failure_on_startup_falls_back(self):
        primary = ChaosTranscriber(
            session_id="quota-start-1",
            fail_on_start=TranscriberQuotaExceededError("Account quota has run out on connect"),
        )

        cfg = OrchestratorConfig(
            enable_mock_fallback=True,
            fallback_script="Startup quota fallback success.",
            retry_config=RetryConfig(max_retries=0),
        )

        orch = TranscriptionOrchestrator(
            session_id="quota-start-1",
            transcriber=primary,
            config=cfg,
        )

        # Should NOT raise; fallback recovers during startup
        await orch.start()
        assert orch.state == OrchestratorState.RUNNING
        assert orch.is_fallback_active is True
        assert orch.metrics.fallbacks_triggered == 1

        # Feed audio and conclude
        chunk = b"\x00" * 3200
        for _ in range(3):
            await orch.push_audio(chunk)
        await orch.finish_audio()
        await orch.stop()

        assert "startup quota fallback success" in orch.get_final_text().lower()


# ==============================================================================
# 3. Network Failure Fallback Tests
# ==============================================================================

class TestNetworkFailureFallback:
    """Validate automatic fallback upon socket drops, connection resets, and timeouts."""

    @pytest.mark.anyio
    async def test_connection_reset_falls_back_to_mock_provider(self):
        primary = ChaosTranscriber(
            session_id="net-fallback-1",
            fail_on_push_after_chunks=1,
            fail_on_push_exc=ConnectionResetError("Socket connection forcibly closed by peer"),
        )

        cfg = OrchestratorConfig(
            enable_mock_fallback=True,
            fallback_script="Network recovery via mock transcriber.",
            retry_config=RetryConfig(max_retries=1, initial_delay_seconds=0.01),
        )

        orch = TranscriptionOrchestrator(
            session_id="net-fallback-1",
            transcriber=primary,
            config=cfg,
        )

        await orch.start()
        chunk = b"\x00" * 3200
        for _ in range(4):
            await orch.push_audio(chunk)
        await orch.finish_audio()
        await orch.stop()

        assert orch.is_fallback_active is True
        assert orch.metrics.fallbacks_triggered == 1

        # Check that error event is normalized (CONNECTION_FAILED)
        error_events = [e for e in orch.events_history if e.event_type == TranscriptEventType.ERROR]
        assert len(error_events) >= 1
        assert error_events[0].error.code == "CONNECTION_FAILED"
        assert "recovery" in orch.get_final_text().lower()

    @pytest.mark.anyio
    async def test_timeout_failure_falls_back_to_mock_provider(self):
        primary = ChaosTranscriber(
            session_id="timeout-fallback-1",
            fail_on_push_after_chunks=1,
            fail_on_push_exc=asyncio.TimeoutError("Upstream STT chunk processing timed out"),
        )

        cfg = OrchestratorConfig(
            enable_mock_fallback=True,
            fallback_script="Timeout fallback succeeded.",
            retry_config=RetryConfig(max_retries=1, initial_delay_seconds=0.01),
            timeout_config=TimeoutConfig(chunk_timeout_seconds=0.5),
        )

        orch = TranscriptionOrchestrator(
            session_id="timeout-fallback-1",
            transcriber=primary,
            config=cfg,
        )

        await orch.start()
        chunk = b"\x00" * 3200
        for _ in range(4):
            await orch.push_audio(chunk)
        await orch.finish_audio()
        await orch.stop()

        assert orch.is_fallback_active is True
        assert orch.metrics.fallbacks_triggered == 1
        assert "timeout fallback succeeded" in orch.get_final_text().lower()

    @pytest.mark.anyio
    async def test_fallback_disabled_raises_normalized_error_and_transitions_to_error_state(self):
        primary = ChaosTranscriber(
            session_id="fallback-disabled-1",
            fail_on_start=ConnectionRefusedError("Provider port unreachable"),
        )

        cfg = OrchestratorConfig(
            enable_mock_fallback=False,  # Fallback disabled
            retry_config=RetryConfig(max_retries=0),
        )

        orch = TranscriptionOrchestrator(
            session_id="fallback-disabled-1",
            transcriber=primary,
            config=cfg,
        )

        # Must raise normalized TranscriberConnectionError, NEVER raw ConnectionRefusedError
        with pytest.raises(TranscriberConnectionError):
            await orch.start()

        assert orch.state == OrchestratorState.ERROR
        assert orch.is_fallback_active is False


# ==============================================================================
# 4. ResilientTranscriberWrapper Fallback Component Tests
# ==============================================================================

class TestResilientWrapperFallback:
    """Validate component-level fallback inside ResilientTranscriberWrapper."""

    @pytest.mark.anyio
    async def test_wrapper_switches_to_fallback_on_quota_failure(self):
        primary = ChaosTranscriber(
            session_id="wrap-fallback-1",
            fail_on_push_after_chunks=1,
            fail_on_push_exc=TranscriberQuotaExceededError("Vendor quota exhausted"),
        )
        fallback = FakeTranscriber(
            session_id="wrap-fallback-1",
            script="Wrapper fallback worked.",
        )

        wrapper = ResilientTranscriberWrapper(
            target_transcriber=primary,
            fallback_transcriber=fallback,
            enable_fallback=True,
            retry_config=RetryConfig(max_retries=0),
        )

        await wrapper.start()
        chunk = b"\x00" * 3200

        # Push chunk that triggers quota failure
        await wrapper.push_audio(chunk)

        # Verify wrapper switched to fallback
        assert wrapper.is_fallback_active is True
        assert wrapper.metrics.fallbacks_triggered == 1
        assert wrapper.target == fallback

        await wrapper.finish_audio()
        await wrapper.stop()
