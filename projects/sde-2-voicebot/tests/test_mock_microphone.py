"""Unit tests for MockMicrophone fake audio source (Week 1, Day 3-4)."""

import unittest

from voicebot.mock_microphone import MockMicrophone
from voicebot.schemas import AudioChunk, AudioError, AudioFormat


class TestMockMicrophone(unittest.TestCase):
    """Verify fake microphone source behavior, repeatability, and schema compliance."""

    def test_default_initialization(self):
        """MockMicrophone initializes with expected default configuration."""
        mic = MockMicrophone()
        self.assertEqual(mic.audio_format.sample_rate, 16000)
        self.assertEqual(mic.audio_format.channels, 1)
        self.assertEqual(mic.audio_format.sample_width, 2)
        self.assertEqual(mic.chunk_count, 5)
        self.assertEqual(mic.frames_per_chunk, 4)

    def test_chunk_emission_count(self):
        """stream() emits exactly chunk_count AudioChunks."""
        mic = MockMicrophone(chunk_count=7)
        chunks = list(mic.stream())
        self.assertEqual(len(chunks), 7)

    def test_chunk_ordering_monotonic_sequence_ids(self):
        """Sequence IDs start at 0 and strictly increase monotonically by 1."""
        mic = MockMicrophone(chunk_count=10)
        chunks = list(mic.stream())
        sequence_ids = [c.sequence_id for c in chunks]
        self.assertEqual(sequence_ids, list(range(10)))

    def test_timestamp_monotonicity_and_accuracy(self):
        """Timestamps start at 0.0 and advance accurately according to chunk duration."""
        sample_rate = 16000
        frames_per_chunk = 4
        mic = MockMicrophone(
            sample_rate=sample_rate,
            chunk_count=6,
            frames_per_chunk=frames_per_chunk,
        )
        chunks = list(mic.stream())
        expected_chunk_duration = frames_per_chunk / sample_rate

        for i, chunk in enumerate(chunks):
            expected_time = i * expected_chunk_duration
            self.assertAlmostEqual(chunk.timestamp, expected_time, places=6)

    def test_chunk_size_and_frame_alignment(self):
        """Each chunk payload size matches frames_per_chunk * bytes_per_frame."""
        mic = MockMicrophone(
            sample_rate=16000,
            channels=2,
            sample_width=2,
            chunk_count=4,
            frames_per_chunk=10,
        )
        bytes_per_frame = 2 * 2  # 4 bytes per frame
        expected_bytes = 10 * bytes_per_frame  # 40 bytes per chunk

        chunks = list(mic.stream())
        for chunk in chunks:
            self.assertIsInstance(chunk, AudioChunk)
            self.assertEqual(len(chunk.data), expected_bytes)
            self.assertEqual(chunk.frame_count, 10)

    def test_schema_compatibility(self):
        """Emitted chunks are valid AudioChunk objects containing the expected AudioFormat."""
        mic = MockMicrophone(sample_rate=8000, channels=1, chunk_count=3)
        for chunk in mic.stream():
            self.assertIsInstance(chunk, AudioChunk)
            self.assertIsInstance(chunk.audio_format, AudioFormat)
            self.assertEqual(chunk.audio_format.sample_rate, 8000)
            self.assertEqual(chunk.audio_format.channels, 1)

    def test_repeatability_and_determinism(self):
        """Streaming multiple times or across separate instances yields identical chunks."""
        mic1 = MockMicrophone(chunk_count=5, frames_per_chunk=8)
        mic2 = MockMicrophone(chunk_count=5, frames_per_chunk=8)

        run1 = list(mic1.stream())
        run2 = list(mic1.stream())
        run3 = list(mic2.stream())

        self.assertEqual(len(run1), len(run2))
        self.assertEqual(len(run1), len(run3))

        for c1, c2, c3 in zip(run1, run2, run3):
            self.assertEqual(c1.sequence_id, c2.sequence_id)
            self.assertEqual(c1.sequence_id, c3.sequence_id)
            self.assertEqual(c1.timestamp, c2.timestamp)
            self.assertEqual(c1.timestamp, c3.timestamp)
            self.assertEqual(c1.data, c2.data)
            self.assertEqual(c1.data, c3.data)

    def test_mock_microphone_with_raw_data(self):
        """MockMicrophone can chunk and stream pre-supplied PCM raw bytes."""
        format_mono = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        # 16 frames of mono 16-bit = 32 bytes
        raw_pcm = b"".join(bytes([i % 256, 0]) for i in range(16))
        mic = MockMicrophone(
            sample_rate=16000,
            channels=1,
            frames_per_chunk=4,
            raw_data=raw_pcm,
        )
        chunks = list(mic.stream())
        self.assertEqual(len(chunks), 4)  # 16 frames / 4 frames_per_chunk = 4 chunks
        reconstructed = b"".join(c.data for c in chunks)
        self.assertEqual(reconstructed, raw_pcm)

    def test_zero_chunk_count(self):
        """MockMicrophone with chunk_count=0 emits zero chunks without error."""
        mic = MockMicrophone(chunk_count=0)
        chunks = list(mic.stream())
        self.assertEqual(chunks, [])

    def test_invalid_chunk_count_negative(self):
        """Negative chunk_count raises ValueError."""
        with self.assertRaises(ValueError):
            MockMicrophone(chunk_count=-1)

    def test_invalid_chunk_count_type(self):
        """Non-integer chunk_count raises ValueError."""
        for invalid_val in (True, False, 5.0, "5", None):
            with self.subTest(val=invalid_val):
                with self.assertRaises(ValueError):
                    MockMicrophone(chunk_count=invalid_val)

    def test_invalid_frames_per_chunk_value(self):
        """frames_per_chunk <= 0 raises ValueError."""
        for val in (0, -1, -10):
            with self.subTest(val=val):
                with self.assertRaises(ValueError):
                    MockMicrophone(frames_per_chunk=val)

    def test_invalid_frames_per_chunk_type(self):
        """Non-integer frames_per_chunk raises ValueError."""
        for invalid_val in (True, False, 4.0, "4", None):
            with self.subTest(val=invalid_val):
                with self.assertRaises(ValueError):
                    MockMicrophone(frames_per_chunk=invalid_val)

    def test_invalid_audio_format_parameters(self):
        """Invalid audio format parameters raise AudioError."""
        with self.assertRaises(AudioError):
            MockMicrophone(sample_rate=-16000)
        with self.assertRaises(AudioError):
            MockMicrophone(channels=3)

    def test_positional_arguments_compatibility(self):
        """MockMicrophone(16000, 1, 5, 4) initializes with backward-compatible positional order."""
        mic = MockMicrophone(16000, 1, 5, 4)
        self.assertEqual(mic.audio_format.sample_rate, 16000)
        self.assertEqual(mic.audio_format.channels, 1)
        self.assertEqual(mic.chunk_count, 5)
        self.assertEqual(mic.frames_per_chunk, 4)
        self.assertEqual(mic.audio_format.sample_width, 2)
        chunks = list(mic.stream())
        self.assertEqual(len(chunks), 5)
        self.assertEqual([c.sequence_id for c in chunks], [0, 1, 2, 3, 4])


if __name__ == "__main__":
    unittest.main()

