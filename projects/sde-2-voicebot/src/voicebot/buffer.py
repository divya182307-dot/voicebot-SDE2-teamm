"""Bounded audio stream buffer with backpressure and dropped-chunk counters.

Week 2 (Days 12-13) Deliverables for SDE Team 2.

This module provides bounded memory buffering for AudioChunk streams:
- DropStrategy: Enum defining overflow policies (DROP_OLDEST, DROP_NEWEST, REJECT_NEW).
- BufferStatistics: Immutable telemetry dataclass capturing occupancy and drop metrics.
- BoundedAudioBuffer: Thread-safe bounded FIFO queue managing backpressure, dropped-chunk
  counters, sequence gap detection, and memory protection.
"""

from collections import deque
from dataclasses import dataclass
from enum import Enum
import threading
from typing import Iterator

from voicebot.schemas import AudioChunk, AudioError


class DropStrategy(str, Enum):
    """Policy for handling buffer overflow when capacity is reached."""

    DROP_OLDEST = "DROP_OLDEST"  # Discard oldest chunk at queue head (keeps freshest speech)
    DROP_NEWEST = "DROP_NEWEST"  # Discard incoming chunk immediately
    REJECT_NEW = "REJECT_NEW"    # Raise AudioError on overflow


@dataclass(frozen=True)
class BufferStatistics:
    """Snapshot of audio buffer performance metrics and telemetry.

    Fields:
        current_occupancy: Current number of AudioChunks queued in buffer.
        max_chunks: Configured maximum capacity.
        occupancy_ratio: Fractional occupancy between 0.0 and 1.0 (occupancy / max_chunks).
        current_duration_seconds: Cumulative audio duration of all queued chunks in seconds.
        total_chunks_pushed: Total number of chunks submitted to the buffer.
        total_chunks_pulled: Total number of chunks retrieved by downstream consumers.
        total_chunks_dropped: Total number of chunks dropped due to buffer overflow.
        dropped_chunk_counter: Cumulative dropped-chunk counter for monitoring and diagnostics.
        peak_occupancy: Maximum queue size reached during this buffer lifecycle.
        is_backpressure_active: True if occupancy meets or exceeds the high-water mark.
        gaps_detected: Count of detected sequence gaps in incoming audio stream.
        late_chunks_detected: Count of out-of-order or late arriving sequence IDs.
    """

    current_occupancy: int
    max_chunks: int
    occupancy_ratio: float
    current_duration_seconds: float
    total_chunks_pushed: int
    total_chunks_pulled: int
    total_chunks_dropped: int
    dropped_chunk_counter: int
    peak_occupancy: int
    is_backpressure_active: bool
    gaps_detected: int
    late_chunks_detected: int


class BoundedAudioBuffer:
    """Thread-safe bounded FIFO queue for AudioChunk streams with backpressure telemetry.

    Guarantees:
        - Bounded Memory: Fixed capacity prevents unbounded memory growth.
        - Dropped-Chunk Counter: Tracks exact count of dropped chunks on overflow.
        - Backpressure Signaling: Alerts upstream producer when buffer reaches high-water mark.
        - Sequence Integrity: Detects sequence ID skips (gaps) and out-of-order (late) chunks.
        - Configurable Policy: Supports DROP_OLDEST, DROP_NEWEST, and REJECT_NEW strategies.
    """

    def __init__(
        self,
        max_chunks: int = 50,
        drop_strategy: DropStrategy = DropStrategy.DROP_OLDEST,
        high_water_mark: float = 0.8,
    ):
        """Initialize the bounded audio buffer.

        Args:
            max_chunks (int): Maximum number of AudioChunk instances to hold (must be > 0).
            drop_strategy (DropStrategy): Policy when buffer is full (default: DROP_OLDEST).
            high_water_mark (float): Occupancy ratio [0.0, 1.0] to trigger backpressure (default: 0.8).

        Raises:
            AudioError: If max_chunks <= 0, drop_strategy is invalid, or high_water_mark is out of bounds.
        """
        if isinstance(max_chunks, bool) or not isinstance(max_chunks, int):
            raise AudioError("max_chunks must be an integer.")
        if max_chunks <= 0:
            raise AudioError("max_chunks must be greater than 0.")

        if not isinstance(drop_strategy, DropStrategy):
            raise AudioError("drop_strategy must be a DropStrategy enum value.")

        if isinstance(high_water_mark, bool) or not isinstance(high_water_mark, (int, float)):
            raise AudioError("high_water_mark must be a numeric value.")
        if not (0.0 < high_water_mark <= 1.0):
            raise AudioError("high_water_mark must be between 0.0 (exclusive) and 1.0 (inclusive).")

        self.max_chunks = max_chunks
        self.drop_strategy = drop_strategy
        self.high_water_mark = float(high_water_mark)

        self._queue: deque[AudioChunk] = deque()
        self._lock = threading.RLock()

        self._total_chunks_pushed: int = 0
        self._total_chunks_pulled: int = 0
        self._dropped_chunk_counter: int = 0
        self._peak_occupancy: int = 0

        self._highest_sequence_id: int = -1
        self._gaps: list[tuple[int, int]] = []
        self._late_chunks: list[int] = []

    @property
    def dropped_chunk_counter(self) -> int:
        """Return the cumulative count of chunks dropped due to overflow."""
        with self._lock:
            return self._dropped_chunk_counter

    @property
    def current_occupancy(self) -> int:
        """Return the current number of queued chunks."""
        with self._lock:
            return len(self._queue)

    @property
    def occupancy_ratio(self) -> float:
        """Return current occupancy as a fraction of max_chunks [0.0, 1.0]."""
        with self._lock:
            return len(self._queue) / self.max_chunks

    @property
    def current_duration_seconds(self) -> float:
        """Return the total duration of audio currently queued in seconds."""
        with self._lock:
            return sum(c.duration for c in self._queue)

    @property
    def is_backpressure_active(self) -> bool:
        """Return True if buffer occupancy meets or exceeds the high-water mark."""
        with self._lock:
            return self.occupancy_ratio >= self.high_water_mark

    @property
    def is_empty(self) -> bool:
        """Return True if the buffer contains no chunks."""
        with self._lock:
            return len(self._queue) == 0

    @property
    def is_full(self) -> bool:
        """Return True if the buffer has reached maximum capacity."""
        with self._lock:
            return len(self._queue) >= self.max_chunks

    @property
    def total_chunks_pushed(self) -> int:
        """Return total chunks submitted to buffer."""
        with self._lock:
            return self._total_chunks_pushed

    @property
    def total_chunks_pulled(self) -> int:
        """Return total chunks retrieved from buffer."""
        with self._lock:
            return self._total_chunks_pulled

    @property
    def peak_occupancy(self) -> int:
        """Return maximum queue occupancy reached."""
        with self._lock:
            return self._peak_occupancy

    @property
    def gaps_detected(self) -> list[tuple[int, int]]:
        """Return list of detected sequence gaps as (start_missing, end_missing) tuples."""
        with self._lock:
            return list(self._gaps)

    @property
    def late_chunks_detected(self) -> list[int]:
        """Return list of detected out-of-order sequence IDs."""
        with self._lock:
            return list(self._late_chunks)

    def push(self, chunk: AudioChunk) -> bool:
        """Push an AudioChunk into the bounded buffer.

        Handles sequence gap/late detection, enforces capacity limits, and applies
        the configured DropStrategy when full.

        Args:
            chunk (AudioChunk): Incoming audio chunk to buffer.

        Returns:
            bool: True if chunk was accepted into the buffer; False if dropped (DROP_NEWEST).

        Raises:
            AudioError: If chunk is invalid or if drop_strategy is REJECT_NEW on overflow.
        """
        if not isinstance(chunk, AudioChunk):
            raise AudioError("chunk must be an instance of AudioChunk.")

        with self._lock:
            # Sequence integrity check
            if self._highest_sequence_id >= 0:
                if chunk.sequence_id < self._highest_sequence_id:
                    # Late / out-of-order chunk
                    self._late_chunks.append(chunk.sequence_id)
                elif chunk.sequence_id > self._highest_sequence_id + 1:
                    # Sequence gap: missing chunks between highest and current
                    self._gaps.append((self._highest_sequence_id + 1, chunk.sequence_id - 1))

            self._highest_sequence_id = max(self._highest_sequence_id, chunk.sequence_id)

            # Capacity check
            if len(self._queue) >= self.max_chunks:
                self._dropped_chunk_counter += 1

                if self.drop_strategy == DropStrategy.REJECT_NEW:
                    raise AudioError(
                        f"Audio buffer overflow: reached capacity of {self.max_chunks} chunks."
                    )

                if self.drop_strategy == DropStrategy.DROP_NEWEST:
                    self._total_chunks_pushed += 1
                    return False

                if self.drop_strategy == DropStrategy.DROP_OLDEST:
                    self._queue.popleft()  # Evict oldest chunk from head of queue

            # Add new chunk to queue tail
            self._queue.append(chunk)
            self._total_chunks_pushed += 1

            if len(self._queue) > self._peak_occupancy:
                self._peak_occupancy = len(self._queue)

            return True

    def pull(self) -> AudioChunk | None:
        """Retrieve and remove the oldest AudioChunk from the queue head (FIFO).

        Returns:
            AudioChunk | None: The next sequential chunk, or None if the buffer is empty.
        """
        with self._lock:
            if not self._queue:
                return None
            chunk = self._queue.popleft()
            self._total_chunks_pulled += 1
            return chunk

    def pull_all(self) -> list[AudioChunk]:
        """Drain and return all queued chunks in sequential FIFO order.

        Returns:
            list[AudioChunk]: All queued chunks drained from the buffer.
        """
        with self._lock:
            chunks: list[AudioChunk] = []
            while self._queue:
                chunks.append(self._queue.popleft())
                self._total_chunks_pulled += 1
            return chunks

    def clear(self) -> None:
        """Clear all queued chunks and reset tracking metrics."""
        with self._lock:
            self._queue.clear()
            self._highest_sequence_id = -1
            self._gaps.clear()
            self._late_chunks.clear()

    def get_stats(self) -> BufferStatistics:
        """Retrieve an immutable snapshot of current buffer statistics and metrics.

        Returns:
            BufferStatistics: Comprehensive telemetry snapshot.
        """
        with self._lock:
            return BufferStatistics(
                current_occupancy=len(self._queue),
                max_chunks=self.max_chunks,
                occupancy_ratio=round(len(self._queue) / self.max_chunks, 4),
                current_duration_seconds=round(sum(c.duration for c in self._queue), 4),
                total_chunks_pushed=self._total_chunks_pushed,
                total_chunks_pulled=self._total_chunks_pulled,
                total_chunks_dropped=self._dropped_chunk_counter,
                dropped_chunk_counter=self._dropped_chunk_counter,
                peak_occupancy=self._peak_occupancy,
                is_backpressure_active=self.is_backpressure_active,
                gaps_detected=len(self._gaps),
                late_chunks_detected=len(self._late_chunks),
            )

