"""Unit and integration tests for TranscriptionOrchestrator (Day 8–9 Milestone).

Verifies:
1. Orchestrator initialization, configuration, and session validation.
2. End-to-end mock mode flow with FakeTranscriber (chunk to transcript events).
3. Lifecycle state transitions (IDLE -> STARTING -> RUNNING -> STOPPED).
4. Audio validation and auto-start mechanics.
5. Asynchronous streaming generator (`orchestrator.stream()`).
6. Synchronous and asynchronous event callback listeners.
7. Telemetry metrics accounting.
8. Live SegmentAccumulator projections (`get_final_text`, `get_snapshot`).
9. Asynchronous context manager integration (`async with`).
10. Batch processing convenience helper (`process_audio`).
"""

from __future__ import annotations

import asyncio
from typing import List
import pytest

from src.voice.adapter import AudioConfig, TranscriberConfig
from src.voice.exceptions import (
    OrchestratorError,
    OrchestratorStateError,
    TranscriberAudioError,
)
from src.voice.fake_transcriber import FakeTranscriber
from src.voice.orchestrator import (
    OrchestratorConfig,
    OrchestratorMetrics,
    OrchestratorState,
    TranscriptionOrchestrator,
)
from src.voice.schemas import TranscriptEvent, TranscriptEventType


class TestOrchestratorInitialization:
    """Validate initialization and configuration handling."""

    def test_init_with_valid_session_id(self):
        orch = TranscriptionOrchestrator(session_id="test-session-1")
        assert orch.session_id == "test-session-1"
        assert orch.state == OrchestratorState.IDLE
        assert isinstance(orch.transcriber, FakeTranscriber)
        assert orch.accumulator.session_id == "test-session-1"
        assert orch.metrics.chunks_ingested == 0

    def test_init_rejects_empty_session_id(self):
        with pytest.raises(ValueError, match="session_id must be a non-empty string"):
            TranscriptionOrchestrator(session_id="")

        with pytest.raises(ValueError, match="session_id must be a non-empty string"):
            TranscriptionOrchestrator(session_id="   ")

    def test_init_with_custom_transcriber(self):
        custom_transcriber = FakeTranscriber(session_id="custom-stt", script="Hello world")
        orch = TranscriptionOrchestrator(session_id="custom-stt", transcriber=custom_transcriber)
        assert orch.transcriber is custom_transcriber


class TestOrchestratorLifecycle:
    """Validate lifecycle transitions and state invariants."""

    def test_start_and_stop_lifecycle(self):
        async def _run():
            orch = TranscriptionOrchestrator(session_id="life-01")
            assert orch.state == OrchestratorState.IDLE

            await orch.start()
            assert orch.state == OrchestratorState.RUNNING
            assert orch.is_running is True

            await orch.stop()
            assert orch.state == OrchestratorState.STOPPED
            assert orch.is_closed is True

        asyncio.run(_run())

    def test_double_start_raises_error(self):
        async def _run():
            orch = TranscriptionOrchestrator(session_id="double-start")
            await orch.start()
            try:
                with pytest.raises(OrchestratorStateError, match="Cannot start orchestrator"):
                    await orch.start()
            finally:
                await orch.stop()

        asyncio.run(_run())

    def test_context_manager_lifecycle(self):
        async def _run():
            async with TranscriptionOrchestrator(session_id="ctx-01") as orch:
                assert orch.state == OrchestratorState.RUNNING
                assert orch.is_running is True

            assert orch.state == OrchestratorState.STOPPED
            assert orch.is_closed is True

        asyncio.run(_run())


class TestAudioIngestionValidation:
    """Validate audio chunk push mechanics and validation rules."""

    def test_push_empty_chunk_raises_audio_error(self):
        async def _run():
            orch = TranscriptionOrchestrator(session_id="audio-val-1")
            await orch.start()
            try:
                with pytest.raises(TranscriberAudioError, match="cannot be empty"):
                    await orch.push_audio(b"")
            finally:
                await orch.stop()

        asyncio.run(_run())

    def test_push_non_bytes_raises_audio_error(self):
        async def _run():
            orch = TranscriptionOrchestrator(session_id="audio-val-2")
            await orch.start()
            try:
                with pytest.raises(TranscriberAudioError, match="bytes or bytearray"):
                    await orch.push_audio("not-bytes")  # type: ignore
            finally:
                await orch.stop()

        asyncio.run(_run())

    def test_push_when_stopped_raises_state_error(self):
        async def _run():
            orch = TranscriptionOrchestrator(session_id="audio-val-3")
            await orch.start()
            await orch.stop()

            with pytest.raises(OrchestratorStateError, match="Cannot push audio in state 'stopped'"):
                await orch.push_audio(b"\x00" * 3200)

        asyncio.run(_run())

    def test_auto_start_on_push_audio(self):
        async def _run():
            orch = TranscriptionOrchestrator(
                session_id="auto-start-01",
                config=OrchestratorConfig(auto_start=True),
            )
            assert orch.state == OrchestratorState.IDLE

            chunk = b"\x00" * 3200
            await orch.push_audio(chunk)
            assert orch.state == OrchestratorState.RUNNING
            assert orch.metrics.chunks_ingested == 1
            assert orch.metrics.bytes_ingested == 3200

            await orch.stop()

        asyncio.run(_run())


class TestEndToEndMockFlow:
    """Validate full end-to-end chunk to transcript events in mock mode."""

    def test_chunk_to_transcript_events_end_to_end(self):
        async def _run():
            script_text = "What is the worst case time complexity of quicksort?"
            orch = TranscriptionOrchestrator(
                session_id="e2e-01",
                script=script_text,
            )

            chunk = b"\x00" * 3200
            for _ in range(12):
                await orch.push_audio(chunk)

            await orch.finish_audio()
            await orch.stop()

            events = orch.events_history
            assert len(events) > 0

            event_types = [e.event_type for e in events]
            assert TranscriptEventType.SPEECH_STARTED in event_types
            assert TranscriptEventType.FINAL_TRANSCRIPT in event_types
            assert TranscriptEventType.SPEECH_ENDED in event_types

            # Verify accumulator captured the final utterance
            final_text = orch.get_final_text()
            assert script_text in final_text

            # Verify telemetry metrics
            metrics = orch.metrics
            assert metrics.chunks_ingested == 12
            assert metrics.bytes_ingested == 12 * 3200
            assert metrics.events_emitted == len(events)
            assert metrics.speech_turns_detected >= 1
            assert metrics.final_segments_count >= 1

        asyncio.run(_run())

    def test_async_stream_subscription(self):
        async def _run():
            script_text = "Binary search runs in logarithmic time."
            orch = TranscriptionOrchestrator(
                session_id="stream-sub-01",
                script=script_text,
            )
            await orch.start()

            streamed_events: List[TranscriptEvent] = []

            async def _consume():
                async for ev in orch.stream():
                    streamed_events.append(ev)

            consumer_task = asyncio.create_task(_consume())
            # Yield control to allow subscriber task to enter stream()
            await asyncio.sleep(0.001)

            chunk = b"\x00" * 3200
            for _ in range(10):
                await orch.push_audio(chunk)

            await orch.finish_audio()
            await orch.stop()
            await consumer_task

            assert len(streamed_events) > 0
            final_events = [e for e in streamed_events if e.event_type == TranscriptEventType.FINAL_TRANSCRIPT]
            assert len(final_events) == 1
            assert final_events[0].segment is not None
            assert final_events[0].segment.text == script_text

        asyncio.run(_run())

    def test_async_stream_with_replay_existing(self):
        async def _run():
            script_text = "Hash tables provide average constant time lookups."
            orch = TranscriptionOrchestrator(
                session_id="replay-01",
                script=script_text,
            )
            await orch.start()

            chunk = b"\x00" * 3200
            for _ in range(10):
                await orch.push_audio(chunk)

            await orch.finish_audio()

            # Now subscribe with replay_existing=True
            replayed_events: List[TranscriptEvent] = []

            async def _consume():
                async for ev in orch.stream(replay_existing=True):
                    replayed_events.append(ev)

            consumer_task = asyncio.create_task(_consume())
            await asyncio.sleep(0.001)
            await orch.stop()
            await consumer_task

            assert len(replayed_events) == len(orch.events_history)
            final_events = [e for e in replayed_events if e.event_type == TranscriptEventType.FINAL_TRANSCRIPT]
            assert len(final_events) == 1
            assert final_events[0].segment.text == script_text

        asyncio.run(_run())

    def test_event_listeners(self):
        async def _run():
            received_sync: List[TranscriptEvent] = []
            received_async: List[TranscriptEvent] = []

            def sync_listener(event: TranscriptEvent):
                received_sync.append(event)

            async def async_listener(event: TranscriptEvent):
                received_async.append(event)

            orch = TranscriptionOrchestrator(
                session_id="listener-01",
                script="Testing event listener callbacks.",
            )
            orch.add_event_listener(sync_listener)
            orch.add_event_listener(async_listener)

            chunk = b"\x00" * 3200
            for _ in range(8):
                await orch.push_audio(chunk)

            await orch.finish_audio()
            await orch.stop()

            assert len(received_sync) == len(orch.events_history)
            assert len(received_async) == len(orch.events_history)

            orch.remove_event_listener(sync_listener)
            assert sync_listener not in orch._listeners

        asyncio.run(_run())


class TestProjectionsAndBatchProcessing:
    """Validate snapshot projections and batch processing helper."""

    def test_accumulator_snapshot_projections(self):
        async def _run():
            orch = TranscriptionOrchestrator(
                session_id="proj-01",
                script="Dynamic programming solves overlapping subproblems.",
            )

            chunk = b"\x00" * 3200
            for _ in range(10):
                await orch.push_audio(chunk)

            await orch.finish_audio()
            await orch.stop()

            snapshot = orch.get_snapshot()
            assert snapshot.session_id == "proj-01"
            assert len(snapshot.final_segments) == 1
            assert "Dynamic programming" in snapshot.final_text
            assert snapshot.word_count > 0
            assert snapshot.average_confidence > 0.0

        asyncio.run(_run())

    def test_batch_process_audio(self):
        async def _run():
            orch = TranscriptionOrchestrator(
                session_id="batch-01",
                script="Batch audio processing works smoothly.",
            )

            # Buffer of 8 chunks of 3200 bytes
            audio_buffer = b"\x00" * (3200 * 8)
            events = await orch.process_audio(audio_buffer)

            assert len(events) > 0
            final_text = orch.get_final_text()
            assert "Batch audio processing works smoothly." in final_text
            assert orch.state == OrchestratorState.STOPPED

        asyncio.run(_run())
