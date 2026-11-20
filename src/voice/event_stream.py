"""Integration layer for W1 Audio Events and W5 Backend Event Stream.

This module provides:
1. W1 Audio Event Models:
   - AudioEventType: AUDIO_STARTED, AUDIO_CHUNK, AUDIO_ENDED.
   - AudioEvent: Structured audio packet containing session ID, chunk index,
     payload bytes, timestamps, and sample parameters.
2. AudioStreamReorderer:
   - Resolves network jitter and out-of-order audio chunk delivery.
   - Detects missing audio chunks (gaps in sequence numbers) and provides
     automatic silence fill or timeline compensation.
3. BackendEventStream:
   - High-throughput asynchronous event distribution bus bridging the
     TranscriptionOrchestrator to downstream W5 backend consumers (dialog manager,
     reasoning agents, UI gateways).
"""

from __future__ import annotations

import asyncio
from enum import Enum
import inspect
import logging
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Union,
)

from pydantic import BaseModel, ConfigDict, Field

from src.voice.schemas import TranscriptEvent, TranscriptEventType

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. W1 Audio Event Models
# ==============================================================================

class AudioEventType(str, Enum):
    """Enumeration of upstream audio capture and stream events (Week 1 contracts)."""

    AUDIO_STARTED = "audio_started"
    AUDIO_CHUNK = "audio_chunk"
    AUDIO_ENDED = "audio_ended"


class AudioEvent(BaseModel):
    """Canonical audio event packet emitted by audio capture pipeline.

    Fields:
        session_id: Correlated interaction session ID.
        event_type: Classification (AUDIO_STARTED, AUDIO_CHUNK, AUDIO_ENDED).
        chunk_index: Sequential chunk index (0-based) for ordering and gap detection.
        data: Raw 16-bit PCM audio bytes (required for AUDIO_CHUNK).
        timestamp_ms: Stream-relative timestamp in milliseconds.
        sample_rate: Audio sampling rate in Hz (default: 16,000).
        channels: Channel count (1 for mono, 2 for stereo).
        is_last: Flag indicating if this is the final chunk of speech.
        metadata: Optional telemetry or provider attributes.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(..., min_length=1, description="Bound session identifier")
    event_type: AudioEventType = Field(..., description="Audio event classification")
    chunk_index: Optional[int] = Field(default=None, ge=0, description="Sequential chunk counter")
    data: Optional[bytes] = Field(default=None, description="PCM audio payload")
    timestamp_ms: Optional[int] = Field(default=None, ge=0, description="Stream-relative offset in ms")
    sample_rate: int = Field(default=16000, ge=8000, le=48000, description="Sampling rate in Hz")
    channels: int = Field(default=1, ge=1, le=2, description="Channel count")
    is_last: bool = Field(default=False, description="True if final chunk of utterance")
    metadata: Optional[dict[str, Any]] = Field(default=None, description="Diagnostic metadata")

    @classmethod
    def started(
        cls,
        session_id: str,
        sample_rate: int = 16000,
        channels: int = 1,
        metadata: Optional[dict[str, Any]] = None,
    ) -> AudioEvent:
        """Construct an AUDIO_STARTED lifecycle event."""
        return cls(
            session_id=session_id,
            event_type=AudioEventType.AUDIO_STARTED,
            sample_rate=sample_rate,
            channels=channels,
            metadata=metadata,
        )

    @classmethod
    def chunk(
        cls,
        session_id: str,
        data: bytes,
        chunk_index: int,
        timestamp_ms: Optional[int] = None,
        sample_rate: int = 16000,
        channels: int = 1,
        is_last: bool = False,
        metadata: Optional[dict[str, Any]] = None,
    ) -> AudioEvent:
        """Construct an AUDIO_CHUNK event with audio payload."""
        return cls(
            session_id=session_id,
            event_type=AudioEventType.AUDIO_CHUNK,
            data=data,
            chunk_index=chunk_index,
            timestamp_ms=timestamp_ms,
            sample_rate=sample_rate,
            channels=channels,
            is_last=is_last,
            metadata=metadata,
        )

    @classmethod
    def ended(
        cls,
        session_id: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> AudioEvent:
        """Construct an AUDIO_ENDED lifecycle event."""
        return cls(
            session_id=session_id,
            event_type=AudioEventType.AUDIO_ENDED,
            metadata=metadata,
        )


# ==============================================================================
# 2. Audio Stream Reorderer & Missing Chunk Resilience
# ==============================================================================

class AudioReordererMetrics(BaseModel):
    """Telemetry tracking chunk ordering and missing packet resolution."""

    model_config = ConfigDict(extra="forbid")

    chunks_received: int = Field(default=0, ge=0, description="Total audio chunks ingested")
    chunks_delivered: int = Field(default=0, ge=0, description="Total audio chunks delivered in-order")
    out_of_order_resolved: int = Field(default=0, ge=0, description="Out-of-order chunks successfully sorted")
    missing_chunks_detected: int = Field(default=0, ge=0, description="Detected sequence gaps / dropped packets")
    stale_chunks_dropped: int = Field(default=0, ge=0, description="Late chunks arriving after gap advancement")


class AudioStreamReorderer:
    """Buffers, re-sequences, and handles gaps in streaming audio chunk delivery.

    Core Responsibilities:
    1. **Out-of-Order Resolution**: Buffers early arrivals (e.g., chunk 2 before chunk 1)
       and delivers them in strict chronological sequence once missing chunks arrive.
    2. **Missing Chunk Handling**: When a gap exceeds the `reorder_window`, detects the
       loss, logs metrics, and optionally inserts zero-padded silence to prevent STT
       timeline distortion.
    3. **Stale Chunk Suppression**: Drops chunks that arrive after their gap has already
       been timed out and advanced.
    """

    def __init__(
        self,
        reorder_window: int = 5,
        fill_missing_chunks: bool = True,
        default_chunk_size: int = 3200,
    ) -> None:
        self.reorder_window: int = max(1, reorder_window)
        self.fill_missing_chunks: bool = fill_missing_chunks
        self.default_chunk_size: int = default_chunk_size

        self._expected_chunk_index: int = 0
        self._buffer: Dict[int, AudioEvent] = {}
        self._metrics: AudioReordererMetrics = AudioReordererMetrics()

    @property
    def expected_chunk_index(self) -> int:
        return self._expected_chunk_index

    @property
    def metrics(self) -> AudioReordererMetrics:
        return self._metrics.model_copy()

    def ingest_chunk(self, event: AudioEvent) -> List[AudioEvent]:
        """Ingest an AudioEvent(AUDIO_CHUNK) and return contiguous in-order chunks.

        Args:
            event: An AudioEvent of type AUDIO_CHUNK.

        Returns:
            List of AudioEvents ready for immediate pipeline delivery in order.
        """
        if event.chunk_index is None:
            # Unsequenced chunk: deliver immediately
            self._metrics.chunks_received += 1
            self._metrics.chunks_delivered += 1
            return [event]

        self._metrics.chunks_received += 1
        idx = event.chunk_index
        delivered: List[AudioEvent] = []

        # Case 1: Stale chunk (already passed)
        if idx < self._expected_chunk_index:
            self._metrics.stale_chunks_dropped += 1
            logger.debug(
                "Dropped stale audio chunk index %d (expected >= %d)",
                idx, self._expected_chunk_index,
            )
            return []

        # Case 2: In-order arrival
        if idx == self._expected_chunk_index:
            delivered.append(event)
            self._metrics.chunks_delivered += 1
            self._expected_chunk_index += 1

            # Drain contiguous buffered chunks
            while self._expected_chunk_index in self._buffer:
                next_chunk = self._buffer.pop(self._expected_chunk_index)
                delivered.append(next_chunk)
                self._metrics.chunks_delivered += 1
                self._metrics.out_of_order_resolved += 1
                self._expected_chunk_index += 1

            return delivered

        # Case 3: Out-of-order future arrival (idx > expected)
        self._buffer[idx] = event

        # Check if gap exceeds reorder window
        gap = max(self._buffer.keys()) - self._expected_chunk_index
        if gap >= self.reorder_window:
            # Advance past missing chunks up to the earliest buffered chunk
            earliest_buffered = min(self._buffer.keys())
            missing_count = earliest_buffered - self._expected_chunk_index
            self._metrics.missing_chunks_detected += missing_count

            logger.warning(
                "Detected %d missing audio chunk(s) (indices %d to %d). Advancing stream.",
                missing_count, self._expected_chunk_index, earliest_buffered - 1,
            )

            # Optionally generate silence fill packets to preserve timeline
            if self.fill_missing_chunks:
                sample_chunk = self._buffer[earliest_buffered]
                chunk_len = len(sample_chunk.data) if sample_chunk.data else self.default_chunk_size
                silence_bytes = b"\x00" * chunk_len

                for missing_idx in range(self._expected_chunk_index, earliest_buffered):
                    silence_event = AudioEvent.chunk(
                        session_id=event.session_id,
                        data=silence_bytes,
                        chunk_index=missing_idx,
                        sample_rate=event.sample_rate,
                        channels=event.channels,
                        metadata={"synthetic_fill": True, "missing_chunk": True},
                    )
                    delivered.append(silence_event)
                    self._metrics.chunks_delivered += 1

            self._expected_chunk_index = earliest_buffered

            # Deliver earliest buffered and contiguous followers
            while self._expected_chunk_index in self._buffer:
                next_chunk = self._buffer.pop(self._expected_chunk_index)
                delivered.append(next_chunk)
                self._metrics.chunks_delivered += 1
                self._expected_chunk_index += 1

        return delivered

    def flush(self) -> List[AudioEvent]:
        """Deliver any remaining buffered chunks in sorted order upon audio completion."""
        delivered: List[AudioEvent] = []
        if not self._buffer:
            return delivered

        for idx in sorted(self._buffer.keys()):
            # Fill missing gap before idx if enabled
            if self.fill_missing_chunks and idx > self._expected_chunk_index:
                missing_count = idx - self._expected_chunk_index
                self._metrics.missing_chunks_detected += missing_count
                sample_chunk = self._buffer[idx]
                chunk_len = len(sample_chunk.data) if sample_chunk.data else self.default_chunk_size
                silence_bytes = b"\x00" * chunk_len
                for missing_idx in range(self._expected_chunk_index, idx):
                    silence_event = AudioEvent.chunk(
                        session_id=sample_chunk.session_id,
                        data=silence_bytes,
                        chunk_index=missing_idx,
                        sample_rate=sample_chunk.sample_rate,
                        channels=sample_chunk.channels,
                        metadata={"synthetic_fill": True, "missing_chunk": True},
                    )
                    delivered.append(silence_event)
                    self._metrics.chunks_delivered += 1

            chunk = self._buffer[idx]
            delivered.append(chunk)
            self._metrics.chunks_delivered += 1
            if idx != self._expected_chunk_index:
                self._metrics.out_of_order_resolved += 1
            self._expected_chunk_index = idx + 1

        self._buffer.clear()
        return delivered

    def reset(self) -> None:
        """Reset sequence tracker and buffer."""
        self._expected_chunk_index = 0
        self._buffer.clear()


# ==============================================================================
# 3. W5 Backend Event Stream Integration Bus
# ==============================================================================

class BackendEventStream:
    """Asynchronous pub/sub event stream for W5 backend integration.

    Enables real-time multiplexing of reconciled TranscriptEvents from
    TranscriptionOrchestrator to downstream backend services (dialog management,
    LLM reasoning agent, workflow policy engine, and WebSocket gateways).
    """

    def __init__(self, session_id: Optional[str] = None) -> None:
        self.session_id: Optional[str] = session_id
        self._subscribers: Set[asyncio.Queue[Optional[TranscriptEvent]]] = set()
        self._consumers: List[Callable[[TranscriptEvent], Any]] = []
        self._history: List[TranscriptEvent] = []
        self._is_closed: bool = False
        self._events_published: int = 0

    @property
    def is_closed(self) -> bool:
        return self._is_closed

    @property
    def events_published(self) -> int:
        return self._events_published

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def history(self) -> List[TranscriptEvent]:
        """Return an immutable snapshot copy of all published events."""
        return list(self._history)

    def publish_nowait(self, event: TranscriptEvent) -> None:
        """Synchronously publish a TranscriptEvent to history, queues, and consumers."""
        if self._is_closed:
            logger.warning("Attempted to publish to closed BackendEventStream.")
            return

        self._history.append(event)
        self._events_published += 1

        # Broadcast to asynchronous stream queues
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Backend event subscriber queue full.")

        # Invoke callback consumers
        for consumer in list(self._consumers):
            try:
                res = consumer(event)
                if inspect.isawaitable(res):
                    try:
                        asyncio.create_task(res)
                    except RuntimeError:
                        pass
            except Exception as exc:
                logger.warning("Backend event consumer callback error: %s", exc)

    async def publish(self, event: TranscriptEvent) -> None:
        """Publish a TranscriptEvent to all active subscribers and consumers.

        Args:
            event: Standardized TranscriptEvent instance.
        """
        self.publish_nowait(event)

    async def consume(
        self,
        filter_types: Optional[Set[TranscriptEventType]] = None,
        replay_history: bool = False,
    ) -> AsyncIterator[TranscriptEvent]:
        """Asynchronously stream events published to this backend bus.

        Args:
            filter_types: Optional filter set of TranscriptEventTypes.
            replay_history: If True, first yield previously recorded events from history.

        Yields:
            TranscriptEvent instances until the stream is closed.
        """
        if self._is_closed and not replay_history:
            return

        queue: asyncio.Queue[Optional[TranscriptEvent]] = asyncio.Queue(maxsize=500)
        if replay_history:
            for past_ev in list(self._history):
                queue.put_nowait(past_ev)

        if self._is_closed:
            queue.put_nowait(None)
        else:
            self._subscribers.add(queue)

        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                if filter_types is None or event.event_type in filter_types:
                    yield event
        finally:
            self._subscribers.discard(queue)

    def add_consumer(self, callback: Callable[[TranscriptEvent], Any]) -> None:
        """Register a synchronous or asynchronous consumer callback."""
        self._consumers.append(callback)

    def remove_consumer(self, callback: Callable[[TranscriptEvent], Any]) -> None:
        """Unregister a consumer callback."""
        if callback in self._consumers:
            self._consumers.remove(callback)

    def close_nowait(self) -> None:
        """Synchronously conclude the event stream and signal all subscribers."""
        if self._is_closed:
            return
        self._is_closed = True

        for queue in list(self._subscribers):
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass

    async def close(self) -> None:
        """Gracefully conclude the event stream and signal all subscribers."""
        self.close_nowait()
