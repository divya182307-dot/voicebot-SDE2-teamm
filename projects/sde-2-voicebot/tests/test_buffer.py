"""Unit tests for BoundedAudioBuffer, DropStrategy, and BufferStatistics.

Week 2 (Days 12-13) Deliverables for SDE Team 2.
"""

import unittest

from voicebot.buffer import BoundedAudioBuffer, BufferStatistics, DropStrategy
from voicebot.schemas import AudioChunk, AudioError, AudioFormat


class TestBufferInitialization(unittest.TestCase):
    """Test suite for BoundedAudioBuffer initialization and configuration validation."""

    def test_default_initialization(self):
        """Verify default configuration: max_chunks=50, DROP_OLDEST, high_water_mark=0.8."""
        buf = BoundedAudioBuffer()
        self.assertEqual(buf.max_chunks, 50)
        self.assertEqual(buf.drop_strategy, DropStrategy.DROP_OLDEST)
        self.assertEqual(buf.high_water_mark, 0.8)
        self.assertEqual(buf.current_occupancy, 0)
        self.assertEqual(buf.dropped_chunk_counter, 0)
        self.assertTrue(buf.is_empty)
        self.assertFalse(buf.is_full)
        self.assertFalse(buf.is_backpressure_active)

    def test_custom_initialization(self):
        """Verify custom valid configuration parameters."""
        buf = BoundedAudioBuffer(
            max_chunks=20,
            drop_strategy=DropStrategy.DROP_NEWEST,
            high_water_mark=0.75,
        )
        self.assertEqual(buf.max_chunks, 20)
        self.assertEqual(buf.drop_strategy, DropStrategy.DROP_NEWEST)
        self.assertEqual(buf.high_water_mark, 0.75)

    def test_invalid_max_chunks(self):
        """Verify invalid max_chunks values raise AudioError."""
        for invalid in [0, -5, True, False, "50", 12.5, None]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(AudioError):
                    BoundedAudioBuffer(max_chunks=invalid)  # type: ignore

    def test_invalid_drop_strategy(self):
        """Verify non-DropStrategy values raise AudioError."""
        for invalid in ["DROP_OLDEST", "INVALID", None, 1]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(AudioError):
                    BoundedAudioBuffer(drop_strategy=invalid)  # type: ignore

    def test_invalid_high_water_mark(self):
        """Verify invalid high_water_mark values raise AudioError."""
        for invalid in [0.0, -0.1, 1.1, True, False, "0.8", None]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(AudioError):
                    BoundedAudioBuffer(high_water_mark=invalid)  # type: ignore


class TestBufferFIFOOperations(unittest.TestCase):
    """Test suite for standard FIFO ordering and chunk retrieval."""

    def setUp(self):
        """Create standard audio format and buffer fixtures."""
        self.format = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        self.buf = BoundedAudioBuffer(max_chunks=10)

    def _create_chunk(self, sequence_id: int) -> AudioChunk:
        """Helper to create dummy AudioChunk with specified sequence ID."""
        return AudioChunk(
            sequence_id=sequence_id,
            timestamp=sequence_id * 0.02,
            audio_format=self.format,
            data=bytes([0x01, 0x02] * 160),  # 160 frames = 10ms
        )

    def test_fifo_ordering(self):
        """Verify chunks are retrieved in strictly identical order pushed."""
        for i in range(5):
            accepted = self.buf.push(self._create_chunk(i))
            self.assertTrue(accepted)

        self.assertEqual(self.buf.current_occupancy, 5)

        for i in range(5):
            chunk = self.buf.pull()
            self.assertIsNotNone(chunk)
            self.assertEqual(chunk.sequence_id, i)

        self.assertTrue(self.buf.is_empty)
        self.assertIsNone(self.buf.pull())

    def test_pull_all(self):
        """Verify pull_all drains all chunks in sequential order."""
        for i in range(4):
            self.buf.push(self._create_chunk(i))

        drained = self.buf.pull_all()
        self.assertEqual(len(drained), 4)
        self.assertEqual([c.sequence_id for c in drained], [0, 1, 2, 3])
        self.assertTrue(self.buf.is_empty)

    def test_push_invalid_type_raises_audio_error(self):
        """Verify push rejects non-AudioChunk arguments."""
        with self.assertRaises(AudioError):
            self.buf.push("not_a_chunk")  # type: ignore


class TestOverflowAndDropStrategies(unittest.TestCase):
    """Test suite for overflow handling, drop policies, and dropped-chunk counters."""

    def setUp(self):
        """Create standard format fixture."""
        self.format = AudioFormat(sample_rate=16000, channels=1, sample_width=2)

    def _create_chunk(self, sequence_id: int) -> AudioChunk:
        return AudioChunk(
            sequence_id=sequence_id,
            timestamp=sequence_id * 0.02,
            audio_format=self.format,
            data=bytes([0x01, 0x02] * 160),
        )

    def test_drop_oldest_strategy(self):
        """Verify DROP_OLDEST evicts oldest queued chunk and increments dropped_chunk_counter."""
        buf = BoundedAudioBuffer(max_chunks=3, drop_strategy=DropStrategy.DROP_OLDEST)

        # Fill buffer to capacity (Chunks 0, 1, 2)
        for i in range(3):
            buf.push(self._create_chunk(i))

        self.assertEqual(buf.current_occupancy, 3)
        self.assertEqual(buf.dropped_chunk_counter, 0)

        # Push Chunk 3 -> Chunk 0 is dropped
        accepted = buf.push(self._create_chunk(3))
        self.assertTrue(accepted)
        self.assertEqual(buf.current_occupancy, 3)
        self.assertEqual(buf.dropped_chunk_counter, 1)

        # Push Chunk 4 -> Chunk 1 is dropped
        buf.push(self._create_chunk(4))
        self.assertEqual(buf.dropped_chunk_counter, 2)

        # Remaining chunks in buffer must be 2, 3, 4
        drained = buf.pull_all()
        self.assertEqual([c.sequence_id for c in drained], [2, 3, 4])

    def test_drop_newest_strategy(self):
        """Verify DROP_NEWEST rejects incoming chunks and increments dropped_chunk_counter."""
        buf = BoundedAudioBuffer(max_chunks=3, drop_strategy=DropStrategy.DROP_NEWEST)

        for i in range(3):
            buf.push(self._create_chunk(i))

        # Push Chunk 3 -> rejected immediately
        accepted3 = buf.push(self._create_chunk(3))
        self.assertFalse(accepted3)
        self.assertEqual(buf.dropped_chunk_counter, 1)

        # Push Chunk 4 -> rejected immediately
        accepted4 = buf.push(self._create_chunk(4))
        self.assertFalse(accepted4)
        self.assertEqual(buf.dropped_chunk_counter, 2)

        # Chunks 0, 1, 2 remain in buffer
        drained = buf.pull_all()
        self.assertEqual([c.sequence_id for c in drained], [0, 1, 2])

    def test_reject_new_strategy(self):
        """Verify REJECT_NEW raises AudioError on overflow and increments counter."""
        buf = BoundedAudioBuffer(max_chunks=2, drop_strategy=DropStrategy.REJECT_NEW)
        buf.push(self._create_chunk(0))
        buf.push(self._create_chunk(1))

        with self.assertRaises(AudioError) as ctx:
            buf.push(self._create_chunk(2))
        self.assertIn("buffer overflow", str(ctx.exception))
        self.assertEqual(buf.dropped_chunk_counter, 1)


class TestBackpressureAndTelemetry(unittest.TestCase):
    """Test suite for backpressure threshold signaling and telemetry statistics."""

    def setUp(self):
        self.format = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        # Capacity = 10, High Water Mark = 0.8 (threshold is 8 chunks)
        self.buf = BoundedAudioBuffer(max_chunks=10, high_water_mark=0.8)

    def _create_chunk(self, sequence_id: int) -> AudioChunk:
        return AudioChunk(
            sequence_id=sequence_id,
            timestamp=sequence_id * 0.01,
            audio_format=self.format,
            data=bytes([0x01, 0x02] * 160),  # 10ms = 0.01s
        )

    def test_backpressure_activation_and_deactivation(self):
        """Verify backpressure trips when occupancy >= 80% and clears when drained."""
        # Push 7 chunks (70% occupancy) -> no backpressure
        for i in range(7):
            self.buf.push(self._create_chunk(i))
        self.assertFalse(self.buf.is_backpressure_active)

        # Push 8th chunk (80% occupancy) -> backpressure active!
        self.buf.push(self._create_chunk(7))
        self.assertTrue(self.buf.is_backpressure_active)

        # Pull 2 chunks (drops to 60% occupancy) -> backpressure clears!
        self.buf.pull()
        self.buf.pull()
        self.assertFalse(self.buf.is_backpressure_active)

    def test_buffer_statistics_reporting(self):
        """Verify get_stats returns an accurate BufferStatistics snapshot."""
        for i in range(5):
            self.buf.push(self._create_chunk(i))
        self.buf.pull()

        stats = self.buf.get_stats()
        self.assertIsInstance(stats, BufferStatistics)
        self.assertEqual(stats.current_occupancy, 4)
        self.assertEqual(stats.max_chunks, 10)
        self.assertEqual(stats.occupancy_ratio, 0.4)
        self.assertEqual(stats.total_chunks_pushed, 5)
        self.assertEqual(stats.total_chunks_pulled, 1)
        self.assertEqual(stats.total_chunks_dropped, 0)
        self.assertEqual(stats.dropped_chunk_counter, 0)
        self.assertEqual(stats.peak_occupancy, 5)
        self.assertAlmostEqual(stats.current_duration_seconds, 0.04, places=3)
        self.assertFalse(stats.is_backpressure_active)

    def test_sequence_gap_detection(self):
        """Verify sequence gap is detected when sequence IDs skip numbers."""
        self.buf.push(self._create_chunk(0))
        # Skip seq 1 and 2, push seq 3
        self.buf.push(self._create_chunk(3))

        gaps = self.buf.gaps_detected
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0], (1, 2))  # Missing seq 1 through 2

        stats = self.buf.get_stats()
        self.assertEqual(stats.gaps_detected, 1)

    def test_late_chunk_detection(self):
        """Verify out-of-order sequence ID is logged as a late chunk."""
        self.buf.push(self._create_chunk(0))
        self.buf.push(self._create_chunk(2))
        # Seq 1 arrives late after seq 2
        self.buf.push(self._create_chunk(1))

        late = self.buf.late_chunks_detected
        self.assertEqual(len(late), 1)
        self.assertEqual(late[0], 1)

        stats = self.buf.get_stats()
        self.assertEqual(stats.late_chunks_detected, 1)

    def test_clear_resets_buffer_and_metrics(self):
        """Verify clear() drains all items and resets sequence tracking."""
        for i in range(3):
            self.buf.push(self._create_chunk(i))
        self.buf.clear()

        self.assertTrue(self.buf.is_empty)
        self.assertEqual(self.buf.current_occupancy, 0)
        self.assertEqual(len(self.buf.gaps_detected), 0)
        self.assertEqual(len(self.buf.late_chunks_detected), 0)


if __name__ == "__main__":
    unittest.main()

