"""Unit tests for AudioChunker and chunk_audio (Week 1, Day 3-4)."""

import unittest

from voicebot.chunker import AudioChunker, chunk_audio
from voicebot.schemas import AudioChunk, AudioError, AudioFormat


class TestAudioChunker(unittest.TestCase):
    """Verify deterministic chunking, ordering, timestamps, and error handling."""

    def setUp(self):
        """Create standard test fixtures."""
        self.format_mono = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        self.format_stereo = AudioFormat(sample_rate=16000, channels=2, sample_width=2)

    def test_chunker_initialization(self):
        """Valid initialization sets expected properties."""
        chunker = AudioChunker(self.format_mono, frames_per_chunk=320)
        self.assertEqual(chunker.audio_format, self.format_mono)
        self.assertEqual(chunker.frames_per_chunk, 320)
        self.assertEqual(chunker.bytes_per_chunk, 320 * 2)  # 640 bytes (20ms at 16kHz)
        self.assertAlmostEqual(chunker.chunk_duration, 0.02)

    def test_chunker_invalid_init_parameters(self):
        """AudioChunker rejects invalid audio_format and frames_per_chunk."""
        with self.assertRaises(AudioError):
            AudioChunker("not_format", frames_per_chunk=10)
        with self.assertRaises(AudioError):
            AudioChunker(self.format_mono, frames_per_chunk=0)
        with self.assertRaises(AudioError):
            AudioChunker(self.format_mono, frames_per_chunk=-5)
        for invalid_val in (True, False, 10.5, "10", None):
            with self.subTest(val=invalid_val):
                with self.assertRaises(AudioError):
                    AudioChunker(self.format_mono, frames_per_chunk=invalid_val)

    def test_chunk_bytes_exact_multiples(self):
        """Chunking byte buffer that is an exact multiple of chunk size."""
        chunker = AudioChunker(self.format_mono, frames_per_chunk=10)
        # 100 frames = 200 bytes
        raw_bytes = bytes(range(200))
        chunks = list(chunker.chunk_bytes(raw_bytes))

        self.assertEqual(len(chunks), 10)
        for i, chunk in enumerate(chunks):
            self.assertEqual(chunk.sequence_id, i)
            expected_time = i * (10 / 16000)
            self.assertAlmostEqual(chunk.timestamp, expected_time)
            self.assertEqual(len(chunk.data), 20)  # 10 frames * 2 bytes = 20 bytes
            self.assertEqual(chunk.frame_count, 10)
            self.assertEqual(chunk.data, raw_bytes[i * 20 : (i + 1) * 20])

    def test_chunk_bytes_repeatability_and_determinism(self):
        """Identical input bytes yield identical AudioChunk objects every run."""
        chunker = AudioChunker(self.format_mono, frames_per_chunk=16)
        raw_bytes = bytes(i % 256 for i in range(1600))  # 800 frames = 50 chunks

        run1 = list(chunker.chunk_bytes(raw_bytes))
        run2 = list(chunker.chunk_bytes(raw_bytes))

        self.assertEqual(len(run1), len(run2))
        for c1, c2 in zip(run1, run2):
            self.assertEqual(c1.sequence_id, c2.sequence_id)
            self.assertEqual(c1.timestamp, c2.timestamp)
            self.assertEqual(c1.data, c2.data)
            self.assertEqual(c1.audio_format, c2.audio_format)

    def test_chunk_bytes_with_partial_tail_chunk(self):
        """Buffer with non-multiple frames emits final partial chunk when allowed."""
        chunker = AudioChunker(self.format_mono, frames_per_chunk=20)
        # 45 frames = 90 bytes (2 chunks of 20 frames + 1 chunk of 5 frames)
        raw_bytes = bytes(90)
        chunks_with_partial = list(chunker.chunk_bytes(raw_bytes, allow_partial_chunk=True))
        self.assertEqual(len(chunks_with_partial), 3)
        self.assertEqual(chunks_with_partial[0].frame_count, 20)
        self.assertEqual(chunks_with_partial[1].frame_count, 20)
        self.assertEqual(chunks_with_partial[2].frame_count, 5)
        self.assertEqual(len(chunks_with_partial[2].data), 10)

        # Without partial chunk, trailing 5 frames are dropped
        chunks_no_partial = list(chunker.chunk_bytes(raw_bytes, allow_partial_chunk=False))
        self.assertEqual(len(chunks_no_partial), 2)

    def test_chunk_bytes_start_offset(self):
        """Custom start_sequence_id and start_timestamp propagate correctly."""
        chunker = AudioChunker(self.format_mono, frames_per_chunk=10)
        raw_bytes = bytes(40)  # 20 frames = 2 chunks
        chunks = list(
            chunker.chunk_bytes(
                raw_bytes,
                start_sequence_id=42,
                start_timestamp=1.5,
            )
        )
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].sequence_id, 42)
        self.assertAlmostEqual(chunks[0].timestamp, 1.5)
        self.assertEqual(chunks[1].sequence_id, 43)
        self.assertAlmostEqual(chunks[1].timestamp, 1.5 + (10 / 16000))

    def test_chunk_bytes_empty_data(self):
        """Empty input buffer yields zero chunks without error."""
        chunker = AudioChunker(self.format_mono, frames_per_chunk=10)
        chunks = list(chunker.chunk_bytes(b""))
        self.assertEqual(chunks, [])

    def test_chunk_bytes_invalid_input(self):
        """Invalid types or incomplete frame alignment raise AudioError."""
        chunker = AudioChunker(self.format_mono, frames_per_chunk=10)
        with self.assertRaises(AudioError):
            list(chunker.chunk_bytes("not bytes"))
        with self.assertRaises(AudioError):
            list(chunker.chunk_bytes(b"\x00\x01\x02"))  # 3 bytes, mono 16-bit needs multiple of 2
        with self.assertRaises(AudioError):
            list(chunker.chunk_bytes(bytes(20), start_sequence_id=-1))
        with self.assertRaises(AudioError):
            list(chunker.chunk_bytes(bytes(20), start_sequence_id=True))
        with self.assertRaises(AudioError):
            list(chunker.chunk_bytes(bytes(20), start_timestamp=-0.1))

    def test_chunk_stream(self):
        """Streaming arbitrary-sized byte packets chunks uniformly."""
        chunker = AudioChunker(self.format_mono, frames_per_chunk=10)
        # Target chunk size: 20 bytes (10 frames)
        # Send packets of non-uniform sizes: 7, 13, 25, 15 bytes (total: 60 bytes = 3 chunks of 20)
        packets = [
            bytes(range(0, 7)),
            bytes(range(7, 20)),
            bytes(range(20, 45)),
            bytes(range(45, 60)),
        ]
        chunks = list(chunker.chunk_stream(packets))
        self.assertEqual(len(chunks), 3)
        reconstructed = b"".join(c.data for c in chunks)
        self.assertEqual(reconstructed, bytes(range(60)))
        self.assertEqual([c.sequence_id for c in chunks], [0, 1, 2])

    def test_chunk_audio_convenience_function(self):
        """chunk_audio free function behaves identically to AudioChunker.chunk_bytes."""
        raw_bytes = bytes(60)  # 30 frames
        chunks = list(chunk_audio(raw_bytes, self.format_mono, frames_per_chunk=15))
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].frame_count, 15)
        self.assertEqual(chunks[1].frame_count, 15)

    def test_chunk_stream_validates_params_on_empty_stream(self):
        """chunk_stream rejects invalid start_sequence_id and start_timestamp even on empty stream."""
        chunker = AudioChunker(self.format_mono, frames_per_chunk=10)
        empty_stream = []

        with self.assertRaises(AudioError) as ctx:
            list(chunker.chunk_stream(empty_stream, start_sequence_id=-1))
        self.assertEqual(str(ctx.exception), "start_sequence_id must be non-negative.")

        with self.assertRaises(AudioError) as ctx:
            list(chunker.chunk_stream(empty_stream, start_sequence_id=True))
        self.assertEqual(str(ctx.exception), "start_sequence_id must be an integer.")

        with self.assertRaises(AudioError) as ctx:
            list(chunker.chunk_stream(empty_stream, start_timestamp=-1.0))
        self.assertEqual(str(ctx.exception), "start_timestamp must be non-negative.")

        with self.assertRaises(AudioError) as ctx:
            list(chunker.chunk_stream(empty_stream, start_timestamp="invalid"))
        self.assertEqual(str(ctx.exception), "start_timestamp must be a number in seconds.")

        with self.assertRaises(AudioError) as ctx:
            list(chunker.chunk_stream(empty_stream, start_timestamp=float("nan")))
        self.assertEqual(str(ctx.exception), "start_timestamp must be finite.")


if __name__ == "__main__":
    unittest.main()

