"""Tests for W1 Audio Events, AudioStreamReorderer, and W5 BackendEventStream Integration (Days 19-20).

Validates:
1. W1 AudioEvent data model and lifecycle factory methods.
2. AudioStreamReorderer out-of-order resolution, missing chunk gap detection, synthetic silence fill,
   stale chunk suppression, and stream flushing.
3. W5 BackendEventStream asynchronous pub/sub multiplexing, filtering, callbacks, and graceful close.
4. TranscriptionOrchestrator end-to-end integration:
   - Ingestion of AudioEvent lifecycle (started, chunk, ended).
   - Reordering of out-of-order audio packets before speech recognition.
   - Resilient handling of dropped/missing audio chunks.
   - Real-time forwarding of reconciled transcript events to connected BackendEventStream.
   - Strict session matching and in-flight cancellation propagation.
"""

from __future__ import annotations

import asyncio
import pytest

from src.voice.adapter import AudioConfig
from src.voice.event_stream import (
    AudioEvent,
    AudioEventType,
    AudioReordererMetrics,
    AudioStreamReorderer,
    BackendEventStream,
)
from src.voice.exceptions import (
    SessionMismatchError,
    TranscriberQuotaExceededError,
)
from src.voice.fake_transcriber import FakeTranscriber
from src.voice.orchestrator import (
    OrchestratorConfig,
    TranscriptionOrchestrator,
)
from src.voice.schemas import (
    TranscriptEventType,
)


# ==============================================================================
# 1. W1 AudioEvent Models & Factories
# ==============================================================================

class TestAudioEventModels:
    """Unit tests for AudioEvent schema definition and factory constructors."""

    def test_audio_event_started_factory(self) -> None:
        event = AudioEvent.started(session_id="sess-001", sample_rate=16000, channels=1)
        assert event.session_id == "sess-001"
        assert event.event_type == AudioEventType.AUDIO_STARTED
        assert event.sample_rate == 16000
        assert event.channels == 1
        assert event.data is None
        assert event.chunk_index is None

    def test_audio_event_chunk_factory(self) -> None:
        payload = b"\x01\x00" * 160
        event = AudioEvent.chunk(
            session_id="sess-001",
            data=payload,
            chunk_index=3,
            timestamp_ms=150,
            is_last=False,
        )
        assert event.session_id == "sess-001"
        assert event.event_type == AudioEventType.AUDIO_CHUNK
        assert event.data == payload
        assert event.chunk_index == 3
        assert event.timestamp_ms == 150
        assert event.is_last is False

    def test_audio_event_ended_factory(self) -> None:
        event = AudioEvent.ended(session_id="sess-001", metadata={"reason": "eof"})
        assert event.session_id == "sess-001"
        assert event.event_type == AudioEventType.AUDIO_ENDED
        assert event.metadata == {"reason": "eof"}

    def test_extra_attributes_forbidden(self) -> None:
        with pytest.raises(Exception):
            AudioEvent(
                session_id="sess-001",
                event_type=AudioEventType.AUDIO_STARTED,
                unexpected_field="disallowed",  # type: ignore
            )


# ==============================================================================
# 2. AudioStreamReorderer Unit Tests
# ==============================================================================

class TestAudioStreamReorderer:
    """Unit tests for sliding-window out-of-order resolution and missing chunk handling."""

    def test_in_order_delivery(self) -> None:
        reorderer = AudioStreamReorderer(reorder_window=5)
        c0 = AudioEvent.chunk("sess-1", b"chunk-0", chunk_index=0)
        c1 = AudioEvent.chunk("sess-1", b"chunk-1", chunk_index=1)
        c2 = AudioEvent.chunk("sess-1", b"chunk-2", chunk_index=2)

        out0 = reorderer.ingest_chunk(c0)
        assert out0 == [c0]
        out1 = reorderer.ingest_chunk(c1)
        assert out1 == [c1]
        out2 = reorderer.ingest_chunk(c2)
        assert out2 == [c2]

        m = reorderer.metrics
        assert m.chunks_received == 3
        assert m.chunks_delivered == 3
        assert m.out_of_order_resolved == 0
        assert m.missing_chunks_detected == 0

    def test_out_of_order_resolution_simple(self) -> None:
        """Arrival order: 0, 2, 1, 3. Chunks 1 and 2 must be delivered in proper order."""
        reorderer = AudioStreamReorderer(reorder_window=5)
        c0 = AudioEvent.chunk("sess-1", b"chunk-0", chunk_index=0)
        c1 = AudioEvent.chunk("sess-1", b"chunk-1", chunk_index=1)
        c2 = AudioEvent.chunk("sess-1", b"chunk-2", chunk_index=2)
        c3 = AudioEvent.chunk("sess-1", b"chunk-3", chunk_index=3)

        out0 = reorderer.ingest_chunk(c0)
        assert out0 == [c0]

        # Chunk 2 arrives early (buffered)
        out2 = reorderer.ingest_chunk(c2)
        assert out2 == []

        # Chunk 1 arrives (triggers delivery of 1 followed by 2)
        out1 = reorderer.ingest_chunk(c1)
        assert out1 == [c1, c2]

        out3 = reorderer.ingest_chunk(c3)
        assert out3 == [c3]

        m = reorderer.metrics
        assert m.chunks_received == 4
        assert m.chunks_delivered == 4
        assert m.out_of_order_resolved == 1
        assert m.missing_chunks_detected == 0

    def test_complex_shuffle_reordering(self) -> None:
        """Arrival order: [0, 3, 1, 4, 2]. All 5 chunks delivered in sequence [0, 1, 2, 3, 4]."""
        reorderer = AudioStreamReorderer(reorder_window=5)
        chunks = [AudioEvent.chunk("sess-1", f"chunk-{i}".encode(), chunk_index=i) for i in range(5)]

        delivered: list[AudioEvent] = []
        for idx in [0, 3, 1, 4, 2]:
            delivered.extend(reorderer.ingest_chunk(chunks[idx]))

        assert [c.chunk_index for c in delivered] == [0, 1, 2, 3, 4]
        assert reorderer.metrics.chunks_delivered == 5
        assert reorderer.metrics.out_of_order_resolved >= 2

    def test_missing_chunk_gap_detection_with_silence_fill(self) -> None:
        """Arrival order: [0, 2, 3, 4] with window=2. Chunk 1 is permanently dropped."""
        reorderer = AudioStreamReorderer(reorder_window=2, fill_missing_chunks=True)
        c0 = AudioEvent.chunk("sess-1", b"chunk-0", chunk_index=0)
        c2 = AudioEvent.chunk("sess-1", b"chunk-2", chunk_index=2)
        c3 = AudioEvent.chunk("sess-1", b"chunk-3", chunk_index=3)

        delivered: list[AudioEvent] = []
        delivered.extend(reorderer.ingest_chunk(c0))
        delivered.extend(reorderer.ingest_chunk(c2))  # buffered, gap=1 < window(2)
        assert len(delivered) == 1

        # Chunk 3 triggers gap advance (gap = 3 - 1 = 2 >= window)
        delivered.extend(reorderer.ingest_chunk(c3))

        indices = [c.chunk_index for c in delivered]
        assert indices == [0, 1, 2, 3]  # Chunk 1 was synthetically filled
        assert delivered[1].metadata is not None
        assert delivered[1].metadata.get("synthetic_fill") is True
        assert reorderer.metrics.missing_chunks_detected == 1

    def test_stale_chunk_dropping(self) -> None:
        """Arrival of a chunk whose sequence was already advanced is discarded as stale."""
        reorderer = AudioStreamReorderer(reorder_window=2, fill_missing_chunks=True)
        c0 = AudioEvent.chunk("sess-1", b"chunk-0", chunk_index=0)
        c2 = AudioEvent.chunk("sess-1", b"chunk-2", chunk_index=2)
        c3 = AudioEvent.chunk("sess-1", b"chunk-3", chunk_index=3)
        c1 = AudioEvent.chunk("sess-1", b"chunk-1", chunk_index=1)  # arrives late

        reorderer.ingest_chunk(c0)
        reorderer.ingest_chunk(c2)
        reorderer.ingest_chunk(c3)  # advances past index 1

        # Now chunk 1 arrives late
        stale_out = reorderer.ingest_chunk(c1)
        assert stale_out == []
        assert reorderer.metrics.stale_chunks_dropped == 1

    def test_flush_delivers_remaining_buffer(self) -> None:
        reorderer = AudioStreamReorderer(reorder_window=10)
        c0 = AudioEvent.chunk("sess-1", b"chunk-0", chunk_index=0)
        c2 = AudioEvent.chunk("sess-1", b"chunk-2", chunk_index=2)

        reorderer.ingest_chunk(c0)
        reorderer.ingest_chunk(c2)  # buffered, gap=1 < window(10)

        flushed = reorderer.flush()
        # chunk 1 filled synthetically and chunk 2 delivered
        assert [c.chunk_index for c in flushed] == [1, 2]
        assert reorderer.expected_chunk_index == 3


# ==============================================================================
# 3. W5 BackendEventStream Unit Tests
# ==============================================================================

class TestBackendEventStream:
    """Unit tests for asynchronous pub/sub event stream multiplexing."""

    @pytest.mark.anyio
    async def test_publish_and_consume(self) -> None:
        stream = BackendEventStream(session_id="sess-bus-1")
        collected: list[str] = []

        async def _consumer() -> None:
            async for ev in stream.consume():
                if ev.segment and ev.segment.text:
                    collected.append(ev.segment.text)

        consumer_task = asyncio.create_task(_consumer())
        await asyncio.sleep(0.01)

        fake = FakeTranscriber(session_id="sess-bus-1", script="Integration event stream active.")
        await fake.start()
        # Feed events through stream
        fake.add_event_listener(lambda ev: stream.publish_nowait(ev))
        await fake.push_audio(b"\x00" * 3200)
        await fake.finish_audio()
        await fake.stop()

        await stream.close()
        await consumer_task

        assert len(collected) > 0
        assert any("Integration" in text for text in collected)
        assert stream.events_published > 0
        assert len(stream.history) == stream.events_published

    @pytest.mark.anyio
    async def test_consume_with_type_filter(self) -> None:
        stream = BackendEventStream(session_id="sess-filter")
        finals_only: list[TranscriptEventType] = []

        async def _consumer() -> None:
            async for ev in stream.consume(filter_types={TranscriptEventType.FINAL_TRANSCRIPT}):
                finals_only.append(ev.event_type)

        consumer_task = asyncio.create_task(_consumer())
        await asyncio.sleep(0.01)

        fake = FakeTranscriber(session_id="sess-filter", script="Filter check.")
        await fake.start()
        fake.add_event_listener(lambda ev: stream.publish_nowait(ev))
        await fake.push_audio(b"\x00" * 3200)
        await fake.finish_audio()
        await fake.stop()

        await stream.close()
        await consumer_task

        assert len(finals_only) >= 1
        assert all(t == TranscriptEventType.FINAL_TRANSCRIPT for t in finals_only)

    @pytest.mark.anyio
    async def test_callback_consumer(self) -> None:
        stream = BackendEventStream(session_id="sess-cb")
        received: list[TranscriptEventType] = []

        def _sync_cb(ev):
            received.append(ev.event_type)

        stream.add_consumer(_sync_cb)

        fake = FakeTranscriber(session_id="sess-cb", script="Callback check.")
        await fake.start()
        fake.add_event_listener(lambda ev: stream.publish_nowait(ev))
        await fake.push_audio(b"\x00" * 3200)
        await fake.finish_audio()
        await fake.stop()

        assert len(received) > 0
        stream.remove_consumer(_sync_cb)


# ==============================================================================
# 4. TranscriptionOrchestrator End-to-End Integration Tests
# ==============================================================================

class TestOrchestratorEventStreamIntegration:
    """Full end-to-end integration tests connecting AudioEvents and BackendEventStream."""

    @pytest.mark.anyio
    async def test_push_audio_event_lifecycle(self) -> None:
        """Push AUDIO_STARTED, AUDIO_CHUNK, and AUDIO_ENDED packets."""
        session_id = "sess-audio-event-lifecycle"
        orch = TranscriptionOrchestrator(
            session_id=session_id,
            script="Audio event streaming working.",
        )

        backend_stream = BackendEventStream(session_id=session_id)
        orch.connect_backend_stream(backend_stream)

        # 1. Start event
        await orch.push_audio_event(AudioEvent.started(session_id))
        assert orch.is_running
        assert orch.metrics.audio_events_received == 1

        # 2. Chunk events
        chunk_data = b"\x01\x00" * 1600
        for i in range(3):
            await orch.push_audio_event(AudioEvent.chunk(session_id, chunk_data, chunk_index=i))

        # 3. Ended event
        await orch.push_audio_event(AudioEvent.ended(session_id))
        await orch.stop()

        m = orch.metrics
        assert m.audio_events_received == 5
        assert m.backend_events_published > 0
        assert backend_stream.events_published == m.backend_events_published
        assert orch.get_full_text() != ""

    @pytest.mark.anyio
    async def test_out_of_order_audio_chunks_in_orchestrator(self) -> None:
        """Feed out-of-order audio chunks [0, 2, 1, 3] to orchestrator."""
        session_id = "sess-ooo-audio"
        orch = TranscriptionOrchestrator(
            session_id=session_id,
            script="Out of order audio correctly reordered.",
            config=OrchestratorConfig(enable_audio_reordering=True, audio_reorder_window=5),
        )

        chunk_data = b"\x02\x00" * 1600
        await orch.push_audio_event(AudioEvent.started(session_id))

        # Ingest chunks out of order: 0, 2, 1, 3
        await orch.push_audio_event(AudioEvent.chunk(session_id, chunk_data, chunk_index=0))
        await orch.push_audio_event(AudioEvent.chunk(session_id, chunk_data, chunk_index=2))
        await orch.push_audio_event(AudioEvent.chunk(session_id, chunk_data, chunk_index=1))
        await orch.push_audio_event(AudioEvent.chunk(session_id, chunk_data, chunk_index=3))

        await orch.push_audio_event(AudioEvent.ended(session_id))
        await orch.stop()

        m = orch.metrics
        assert m.audio_chunks_reordered >= 1
        assert m.chunks_ingested == 4
        assert "reordered" in orch.get_full_text().lower()

    @pytest.mark.anyio
    async def test_missing_audio_chunks_in_orchestrator(self) -> None:
        """Feed chunks [0, 2, 3, 4] with missing chunk 1."""
        session_id = "sess-missing-chunks"
        orch = TranscriptionOrchestrator(
            session_id=session_id,
            script="Missing chunk compensated smoothly.",
            config=OrchestratorConfig(
                enable_audio_reordering=True,
                audio_reorder_window=2,
                fill_missing_audio_gaps=True,
            ),
        )

        chunk_data = b"\x03\x00" * 1600
        await orch.push_audio_event(AudioEvent.started(session_id))

        # Chunk 1 is skipped
        await orch.push_audio_event(AudioEvent.chunk(session_id, chunk_data, chunk_index=0))
        await orch.push_audio_event(AudioEvent.chunk(session_id, chunk_data, chunk_index=2))
        await orch.push_audio_event(AudioEvent.chunk(session_id, chunk_data, chunk_index=3))
        await orch.push_audio_event(AudioEvent.chunk(session_id, chunk_data, chunk_index=4))

        await orch.push_audio_event(AudioEvent.ended(session_id))
        await orch.stop()

        m = orch.metrics
        assert m.missing_audio_chunks_detected >= 1
        # 4 original chunks + 1 synthetic silence chunk = 5 chunks ingested
        assert m.chunks_ingested == 5
        assert orch.get_full_text() != ""

    @pytest.mark.anyio
    async def test_backend_stream_pubsub_multiplexing(self) -> None:
        """Ensure multiple downstream consumers on BackendEventStream receive all events."""
        session_id = "sess-multi-consumer"
        orch = TranscriptionOrchestrator(
            session_id=session_id,
            script="Downstream multiplexing verification.",
        )
        stream = BackendEventStream(session_id=session_id)
        orch.connect_backend_stream(stream)

        consumer_1_events: list[TranscriptEventType] = []
        consumer_2_events: list[TranscriptEventType] = []

        async def _run_consumer_1():
            async for ev in stream.consume():
                consumer_1_events.append(ev.event_type)

        async def _run_consumer_2():
            async for ev in stream.consume():
                consumer_2_events.append(ev.event_type)

        t1 = asyncio.create_task(_run_consumer_1())
        t2 = asyncio.create_task(_run_consumer_2())
        await asyncio.sleep(0.01)

        chunk_data = b"\x00" * 3200
        await orch.push_audio_event(AudioEvent.started(session_id))
        await orch.push_audio_event(AudioEvent.chunk(session_id, chunk_data, chunk_index=0))
        await orch.push_audio_event(AudioEvent.ended(session_id))
        await orch.stop()

        await t1
        await t2

        assert len(consumer_1_events) > 0
        assert consumer_1_events == consumer_2_events
        assert stream.is_closed

    def test_session_mismatch_rejection(self) -> None:
        """Verify that mismatched session IDs on AudioEvent or BackendEventStream raise SessionMismatchError."""
        orch = TranscriptionOrchestrator(session_id="correct-session")

        # Mismatched BackendEventStream
        foreign_stream = BackendEventStream(session_id="foreign-session")
        with pytest.raises(SessionMismatchError):
            orch.connect_backend_stream(foreign_stream)

    @pytest.mark.anyio
    async def test_audio_event_session_mismatch(self) -> None:
        orch = TranscriptionOrchestrator(session_id="correct-session")
        foreign_event = AudioEvent.started(session_id="foreign-session")
        with pytest.raises(SessionMismatchError):
            await orch.push_audio_event(foreign_event)

    @pytest.mark.anyio
    async def test_cancellation_propagates_to_backend_stream(self) -> None:
        session_id = "sess-cancel-propagate"
        orch = TranscriptionOrchestrator(session_id=session_id)
        stream = BackendEventStream(session_id=session_id)
        orch.connect_backend_stream(stream)

        await orch.start()
        assert not stream.is_closed

        await orch.cancel(reason="User barge-in")
        assert orch.is_cancelled
        assert stream.is_closed

    @pytest.mark.anyio
    async def test_mock_fallback_emits_to_backend_stream(self) -> None:
        """When provider fails and falls back to mock, normalized error reaches BackendEventStream."""
        session_id = "sess-fallback-stream"

        class FailingTranscriber(FakeTranscriber):
            async def push_audio(self, chunk: bytes) -> None:
                raise TranscriberQuotaExceededError("Rate limit / quota exceeded (HTTP 429)")

        failing = FailingTranscriber(session_id=session_id)
        orch = TranscriptionOrchestrator(
            session_id=session_id,
            transcriber=failing,
            config=OrchestratorConfig(enable_mock_fallback=True),
        )
        stream = BackendEventStream(session_id=session_id)
        orch.connect_backend_stream(stream)

        await orch.start()
        await orch.push_audio(b"\x00" * 3200)
        await asyncio.sleep(0.1)
        await orch.finish_audio()
        await orch.stop()

        assert orch.is_fallback_active
        stream_event_types = [ev.event_type for ev in stream.history]
        assert TranscriptEventType.ERROR in stream_event_types
        assert TranscriptEventType.FINAL_TRANSCRIPT in stream_event_types
