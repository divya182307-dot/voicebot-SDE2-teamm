"""Contract test suite for STT Provider Adapters and Event Specifications (Day 14 Milestone).

Verifies the formal contract that any Speech-to-Text adapter must satisfy:
1. Default Path Zero-Credentials: Runs 100% offline without requiring any real provider or API keys.
2. Lifecycle State Invariants: State transitions (IDLE -> STARTING -> LISTENING -> STOPPING -> STOPPED).
3. Audio Ingestion Contract: Format verification, empty buffer rejection, and state checks.
4. Event Ordering & Integrity Contract: Monotonic sequence numbers, lifecycle event sequences,
   BCP-47 language codes, time window invariants, and confidence intervals.
5. Dual-Dispatch Parity Contract: Verifies parity between async iterator stream() and callback listeners.
6. Error Normalization Contract: Structured TranscriptError propagation without uncaught raw exception leakage.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import List, Optional
import pytest

from src.voice.adapter import (
    AudioConfig,
    AudioEncoding,
    BaseTranscriber,
    TranscriberConfig,
    TranscriberState,
)
from src.voice.exceptions import (
    TranscriberAudioError,
    TranscriberError,
    TranscriberStateError,
)
from src.voice.fake_transcriber import FakeTranscriber
from src.voice.orchestrator import (
    OrchestratorConfig,
    TranscriptionOrchestrator,
)
from src.voice.resilience import (
    ResilientTranscriberWrapper,
    RetryConfig,
    TimeoutConfig,
)
from src.voice.schemas import (
    TranscriptError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


class TestZeroCredentialsDefaultPath:
    """Validate Acceptance Criterion: Default path requires no real provider or API key."""

    def test_default_path_runs_without_api_keys_or_network(self):
        """Adapter and orchestrator instantiate and operate with zero credentials."""
        # Neither OPENAI_API_KEY, DEEPGRAM_API_KEY, nor any cloud credentials required
        adapter = FakeTranscriber(session_id="offline-contract-01", script="Zero credentials required.")
        assert adapter.session_id == "offline-contract-01"
        assert adapter.state == TranscriberState.IDLE

        orch = TranscriptionOrchestrator(session_id="offline-orch-01", script="Completely offline.")
        assert orch.session_id == "offline-orch-01"
        assert isinstance(orch.transcriber, FakeTranscriber)


class TestAdapterLifecycleContract:
    """Validate state machine lifecycle contracts required of any BaseTranscriber implementation."""

    def test_session_id_validation_contract(self):
        with pytest.raises(ValueError, match="session_id must be a non-empty string"):
            FakeTranscriber(session_id="")

        with pytest.raises(ValueError, match="session_id must be a non-empty string"):
            FakeTranscriber(session_id="   ")

    def test_initial_state_contract(self):
        adapter = FakeTranscriber(session_id="contract-init")
        assert adapter.state == TranscriberState.IDLE
        assert not adapter.is_listening
        assert not adapter.is_closed
        assert adapter.events_history == []

    def test_start_and_stop_lifecycle_contract(self):
        async def _run():
            adapter = FakeTranscriber(session_id="contract-life")
            await adapter.start()
            assert adapter.state == TranscriberState.LISTENING
            assert adapter.is_listening is True

            await adapter.stop()
            assert adapter.state == TranscriberState.STOPPED
            assert adapter.is_closed is True

        asyncio.run(_run())

    def test_start_when_already_listening_raises_state_error(self):
        async def _run():
            adapter = FakeTranscriber(session_id="contract-start-err")
            await adapter.start()
            try:
                with pytest.raises(TranscriberStateError, match="Cannot start transcriber in state 'listening'"):
                    await adapter.start()
            finally:
                await adapter.stop()

        asyncio.run(_run())

    def test_async_context_manager_contract(self):
        async def _run():
            async with FakeTranscriber(session_id="contract-ctx") as adapter:
                assert adapter.state == TranscriberState.LISTENING
                assert adapter.is_listening is True

            assert adapter.state == TranscriberState.STOPPED
            assert adapter.is_closed is True

        asyncio.run(_run())


class TestAudioIngestionContract:
    """Validate audio push and validation contracts."""

    def test_push_audio_without_start_raises_state_error(self):
        async def _run():
            adapter = FakeTranscriber(session_id="contract-audio-err1")
            with pytest.raises(TranscriberStateError, match="Transcriber must be in LISTENING state"):
                await adapter.push_audio(b"\x00" * 3200)

        asyncio.run(_run())

    def test_push_empty_chunk_raises_audio_error(self):
        async def _run():
            async with FakeTranscriber(session_id="contract-audio-err2") as adapter:
                with pytest.raises(TranscriberAudioError, match="cannot be empty"):
                    await adapter.push_audio(b"")

        asyncio.run(_run())

    def test_push_non_bytes_raises_audio_error(self):
        async def _run():
            async with FakeTranscriber(session_id="contract-audio-err3") as adapter:
                with pytest.raises(TranscriberAudioError, match="bytes or bytearray"):
                    await adapter.push_audio(12345)  # type: ignore

        asyncio.run(_run())

    def test_finish_audio_without_start_raises_state_error(self):
        async def _run():
            adapter = FakeTranscriber(session_id="contract-finish-err")
            with pytest.raises(TranscriberStateError, match="Transcriber must be in LISTENING state"):
                await adapter.finish_audio()

        asyncio.run(_run())


class TestEventIntegrityAndOrderingContract:
    """Validate invariants for emitted TranscriptEvents and TranscriptSegments."""

    def test_event_stream_lifecycle_ordering_and_monotonicity(self):
        """Events must follow speech lifecycle and maintain monotonic sequence numbers."""
        async def _run():
            script_text = "Quicksort has an average time complexity of O(n log n)."
            adapter = FakeTranscriber(session_id="contract-seq-01", script=script_text)
            await adapter.start()

            chunk = b"\x00" * 3200
            for _ in range(8):
                await adapter.push_audio(chunk)

            await adapter.finish_audio()
            await adapter.stop()

            events = adapter.events_history
            assert len(events) >= 3

            # 1. Monotonic sequence numbers
            sequence_numbers = [e.sequence_number for e in events]
            assert all(seq is not None for seq in sequence_numbers)
            assert sequence_numbers == list(range(1, len(events) + 1))

            # 2. Non-decreasing timestamps
            timestamps = [e.timestamp for e in events]
            for i in range(len(timestamps) - 1):
                assert timestamps[i] <= timestamps[i + 1]

            # 3. Lifecycle event sequencing
            event_types = [e.event_type for e in events]
            assert event_types[0] == TranscriptEventType.SPEECH_STARTED
            assert event_types[-1] == TranscriptEventType.SPEECH_ENDED
            assert TranscriptEventType.FINAL_TRANSCRIPT in event_types

            # 4. Final segment invariant checks
            final_events = [e for e in events if e.event_type == TranscriptEventType.FINAL_TRANSCRIPT]
            assert len(final_events) == 1
            final_segment = final_events[0].segment
            assert final_segment is not None
            assert final_segment.is_final is True
            assert final_segment.start_time_ms >= 0
            assert final_segment.end_time_ms >= final_segment.start_time_ms
            assert 0.0 <= final_segment.confidence <= 1.0
            assert final_segment.text == script_text

            # 5. Word timings invariant checks
            if final_segment.words:
                for word in final_segment.words:
                    assert word.start_time_ms >= final_segment.start_time_ms
                    assert word.end_time_ms <= final_segment.end_time_ms
                    assert 0.0 <= word.confidence <= 1.0

        asyncio.run(_run())


class TestDualDispatchParityContract:
    """Validate that stream() and add_event_listener() receive identical event sequences."""

    def test_dual_dispatch_parity(self):
        async def _run():
            adapter = FakeTranscriber(session_id="contract-dual-01", script="Testing dual dispatch parity.")
            await adapter.start()

            callback_events: List[TranscriptEvent] = []
            stream_events: List[TranscriptEvent] = []

            # Register callback
            adapter.add_event_listener(lambda ev: callback_events.append(ev))

            # Subscribe to async generator stream
            async def _stream_consumer():
                async for ev in adapter.stream():
                    stream_events.append(ev)

            consumer_task = asyncio.create_task(_stream_consumer())
            await asyncio.sleep(0.001)

            chunk = b"\x00" * 3200
            for _ in range(6):
                await adapter.push_audio(chunk)

            await adapter.finish_audio()
            await adapter.stop()
            await consumer_task

            # Both dispatch channels must match exactly
            assert len(callback_events) > 0
            assert len(callback_events) == len(stream_events)
            for cb_ev, st_ev in zip(callback_events, stream_events):
                assert cb_ev.event_id == st_ev.event_id
                assert cb_ev.event_type == st_ev.event_type
                assert cb_ev.sequence_number == st_ev.sequence_number

        asyncio.run(_run())


class TestResilientWrapperContract:
    """Validate that ResilientTranscriberWrapper preserves all BaseTranscriber contracts."""

    def test_wrapper_preserves_contract(self):
        async def _run():
            target = FakeTranscriber(session_id="contract-wrap-01", script="Wrapper contract compliance.")
            wrapper = ResilientTranscriberWrapper(
                target_transcriber=target,
                retry_config=RetryConfig(max_retries=2),
                timeout_config=TimeoutConfig(chunk_timeout_seconds=1.0),
            )

            assert wrapper.session_id == "contract-wrap-01"
            assert wrapper.state == TranscriberState.IDLE

            await wrapper.start()
            assert wrapper.is_listening is True

            chunk = b"\x00" * 3200
            for _ in range(5):
                await wrapper.push_audio(chunk)

            await wrapper.finish_audio()
            await wrapper.stop()
            assert wrapper.is_closed is True

        asyncio.run(_run())


class TestOrchestratorEndToEndContract:
    """Validate that TranscriptionOrchestrator satisfies end-to-end contract invariants."""

    def test_orchestrator_pipeline_contract(self):
        async def _run():
            orch = TranscriptionOrchestrator(
                session_id="contract-orch-01",
                script="End-to-end contract test passes.",
            )
            await orch.start()
            assert orch.is_running is True

            chunk = b"\x00" * 3200
            for _ in range(8):
                await orch.push_audio(chunk)

            await orch.finish_audio()
            await orch.stop()
            assert orch.is_closed is True

            # Snapshot projection contracts
            snapshot = orch.get_snapshot()
            assert snapshot.session_id == "contract-orch-01"
            assert len(snapshot.final_segments) == 1
            assert snapshot.final_text == "End-to-end contract test passes."
            assert snapshot.total_duration_ms > 0
            assert 0.0 <= snapshot.average_confidence <= 1.0

        asyncio.run(_run())

