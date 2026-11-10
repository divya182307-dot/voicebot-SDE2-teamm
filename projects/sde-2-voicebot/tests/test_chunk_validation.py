"""Unit tests for invalid, empty, and corrupt audio chunks, and CLI demo (Week 1, Day 5-6)."""

import io
from math import isfinite
import sys
import unittest

from voicebot.chunker import AudioChunker, chunk_audio
from voicebot.cli import parse_args, run_demo
from voicebot.mock_microphone import MockMicrophone
from voicebot.schemas import AudioChunk, AudioError, AudioFormat


class TestValidHappyPath(unittest.TestCase):
    """Test valid happy path chunking and metadata across audio configurations."""

    def test_happy_path_standard_formats(self):
        """Verify chunk creation across standard speech and audio formats."""
        test_formats = [
            (8000, 1, 1, "8kHz mono 8-bit"),
            (16000, 1, 2, "16kHz mono 16-bit standard speech"),
            (44100, 2, 2, "44.1kHz stereo 16-bit"),
            (48000, 2, 4, "48kHz stereo 32-bit"),
        ]

        for sr, ch, sw, desc in test_formats:
            with self.subTest(format=desc):
                fmt = AudioFormat(sample_rate=sr, channels=ch, sample_width=sw)
                bytes_per_frame = ch * sw
                frames = 100
                raw_data = bytes([i % 256 for i in range(frames * bytes_per_frame)])

                chunk = AudioChunk(
                    sequence_id=0,
                    timestamp=0.0,
                    audio_format=fmt,
                    data=raw_data,
                )

                self.assertEqual(chunk.sequence_id, 0)
                self.assertEqual(chunk.timestamp, 0.0)
                self.assertEqual(chunk.audio_format, fmt)
                self.assertEqual(len(chunk.data), frames * bytes_per_frame)
                self.assertEqual(chunk.frame_count, frames)
                self.assertAlmostEqual(chunk.duration, frames / sr)

    def test_happy_path_chunker_end_to_end(self):
        """Verify chunker slices stream cleanly and produces complete chunks."""
        fmt = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        # 320 frames = 640 bytes (20ms at 16kHz)
        frames_per_chunk = 320
        total_chunks = 5
        raw_pcm = bytes([i % 256 for i in range(frames_per_chunk * 2 * total_chunks)])

        chunks = list(chunk_audio(raw_pcm, fmt, frames_per_chunk=frames_per_chunk))
        self.assertEqual(len(chunks), total_chunks)

        for i, c in enumerate(chunks):
            self.assertEqual(c.sequence_id, i)
            self.assertAlmostEqual(c.timestamp, i * 0.02)
            self.assertEqual(c.frame_count, frames_per_chunk)
            self.assertEqual(len(c.data), frames_per_chunk * 2)
            self.assertAlmostEqual(c.duration, 0.02)


class TestEmptyChunksAndInput(unittest.TestCase):
    """Test behavior when audio data or streams are empty."""

    def setUp(self):
        self.format_mono = AudioFormat(sample_rate=16000, channels=1, sample_width=2)

    def test_empty_audio_chunk_raises_audio_error(self):
        """AudioChunk cannot be constructed with empty data bytes."""
        with self.assertRaises(AudioError) as ctx:
            AudioChunk(
                sequence_id=0,
                timestamp=0.0,
                audio_format=self.format_mono,
                data=b"",
            )
        self.assertEqual(str(ctx.exception), "Audio chunk data must not be empty.")

    def test_chunker_empty_byte_buffer(self):
        """AudioChunker.chunk_bytes returns empty iterator without error on b''."""
        chunker = AudioChunker(self.format_mono, frames_per_chunk=160)
        chunks = list(chunker.chunk_bytes(b""))
        self.assertEqual(chunks, [])

    def test_chunker_empty_stream(self):
        """AudioChunker.chunk_stream returns empty iterator without error on empty stream."""
        chunker = AudioChunker(self.format_mono, frames_per_chunk=160)
        chunks = list(chunker.chunk_stream([]))
        self.assertEqual(chunks, [])

    def test_mock_microphone_empty_stream(self):
        """MockMicrophone with chunk_count=0 emits zero chunks cleanly."""
        mic = MockMicrophone(chunk_count=0)
        chunks = list(mic.stream())
        self.assertEqual(chunks, [])


class TestInvalidChunks(unittest.TestCase):
    """Test rejection of invalid chunk types, sequence numbers, timestamps, and formats."""

    def setUp(self):
        self.format_mono = AudioFormat(sample_rate=16000, channels=1, sample_width=2)

    def test_invalid_data_types(self):
        """AudioChunk rejects non-bytes data."""
        invalid_data = ["not_bytes", [0, 0], {"data": b"\x00\x00"}, None, 12345]
        for val in invalid_data:
            with self.subTest(val=type(val)):
                with self.assertRaises(AudioError) as ctx:
                    AudioChunk(
                        sequence_id=0,
                        timestamp=0.0,
                        audio_format=self.format_mono,
                        data=val,
                    )
                self.assertEqual(str(ctx.exception), "Audio chunk data must be bytes.")

    def test_invalid_sequence_ids(self):
        """AudioChunk rejects negative or non-integer sequence IDs."""
        invalid_seqs = [
            (-1, "Sequence ID must be non-negative."),
            (-100, "Sequence ID must be non-negative."),
            (True, "Sequence ID must be an integer."),
            (False, "Sequence ID must be an integer."),
            (1.5, "Sequence ID must be an integer."),
            ("0", "Sequence ID must be an integer."),
            (None, "Sequence ID must be an integer."),
        ]
        for val, expected_msg in invalid_seqs:
            with self.subTest(val=val):
                with self.assertRaises(AudioError) as ctx:
                    AudioChunk(
                        sequence_id=val,
                        timestamp=0.0,
                        audio_format=self.format_mono,
                        data=b"\x00\x00",
                    )
                self.assertEqual(str(ctx.exception), expected_msg)

    def test_invalid_timestamps(self):
        """AudioChunk rejects negative, non-numeric, or non-finite timestamps."""
        invalid_timestamps = [
            (-0.001, "Timestamp must be non-negative."),
            (-10.0, "Timestamp must be non-negative."),
            (float("nan"), "Timestamp must be finite."),
            (float("inf"), "Timestamp must be finite."),
            (float("-inf"), "Timestamp must be finite."),
            (True, "Timestamp must be a number in seconds."),
            (False, "Timestamp must be a number in seconds."),
            ("0.0", "Timestamp must be a number in seconds."),
            (None, "Timestamp must be a number in seconds."),
        ]
        for val, expected_msg in invalid_timestamps:
            with self.subTest(val=val):
                with self.assertRaises(AudioError) as ctx:
                    AudioChunk(
                        sequence_id=0,
                        timestamp=val,
                        audio_format=self.format_mono,
                        data=b"\x00\x00",
                    )
                self.assertEqual(str(ctx.exception), expected_msg)

    def test_invalid_audio_format_reference(self):
        """AudioChunk rejects invalid or non-AudioFormat objects."""
        for val in (None, "AudioFormat", {"sample_rate": 16000}, 16000):
            with self.subTest(val=type(val)):
                with self.assertRaises(AudioError) as ctx:
                    AudioChunk(
                        sequence_id=0,
                        timestamp=0.0,
                        audio_format=val,
                        data=b"\x00\x00",
                    )
                self.assertEqual(str(ctx.exception), "audio_format must be an AudioFormat instance.")


class TestCorruptChunks(unittest.TestCase):
    """Test detection and rejection of misaligned, truncated, or corrupt frames."""

    def test_corrupt_chunk_incomplete_frames_mono(self):
        """Mono 16-bit format (2 bytes/frame) rejects odd byte lengths."""
        fmt = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        odd_lengths = [1, 3, 5, 7, 9, 15]

        for length in odd_lengths:
            with self.subTest(length=length):
                with self.assertRaises(AudioError) as ctx:
                    AudioChunk(
                        sequence_id=0,
                        timestamp=0.0,
                        audio_format=fmt,
                        data=bytes(length),
                    )
                self.assertEqual(str(ctx.exception), "Audio chunk size must contain complete audio frames.")

    def test_corrupt_chunk_incomplete_frames_stereo(self):
        """Stereo 16-bit format (4 bytes/frame) rejects non-multiple of 4 lengths."""
        fmt = AudioFormat(sample_rate=44100, channels=2, sample_width=2)
        misaligned_lengths = [1, 2, 3, 5, 6, 7, 9, 10, 11]

        for length in misaligned_lengths:
            with self.subTest(length=length):
                with self.assertRaises(AudioError) as ctx:
                    AudioChunk(
                        sequence_id=0,
                        timestamp=0.0,
                        audio_format=fmt,
                        data=bytes(length),
                    )
                self.assertEqual(str(ctx.exception), "Audio chunk size must contain complete audio frames.")

    def test_corrupt_raw_input_to_chunker(self):
        """chunk_bytes rejects input data whose length is not a multiple of frame size."""
        fmt = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        chunker = AudioChunker(fmt, frames_per_chunk=10)
        # 11 bytes: 5 frames + 1 orphaned byte
        with self.assertRaises(AudioError) as ctx:
            list(chunker.chunk_bytes(bytes(11)))
        self.assertEqual(str(ctx.exception), "Audio data size must contain complete audio frames.")

    def test_corrupt_trailing_stream_data(self):
        """chunk_stream rejects trailing data with incomplete frames at end of stream."""
        fmt = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        chunker = AudioChunker(fmt, frames_per_chunk=10)
        # Send packets resulting in total 21 bytes (20 bytes for 1 chunk of 10 frames + 1 orphaned byte)
        stream_packets = [bytes(10), bytes(11)]
        with self.assertRaises(AudioError) as ctx:
            list(chunker.chunk_stream(stream_packets))
        self.assertEqual(str(ctx.exception), "Trailing stream data contains incomplete audio frames.")


class TestCLIDemonstration(unittest.TestCase):
    """Test CLI demo execution and printed metadata output."""

    def test_cli_demo_default_run(self):
        """run_demo prints expected chunk metadata and summary."""
        captured_output = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = captured_output
            exit_code = run_demo(parse_args([]))
        finally:
            sys.stdout = old_stdout

        self.assertEqual(exit_code, 0)
        output = captured_output.getvalue()

        # Check header and metadata table headers
        self.assertIn("Audio Streaming Demo (Week 1)", output)
        self.assertIn("Seq ID", output)
        self.assertIn("Timestamp", output)
        self.assertIn("Format", output)
        self.assertIn("Size (Bytes)", output)

        # Check all 5 default chunks were printed
        for i in range(5):
            self.assertIn(f"{i:<8}", output)

        # Check summary footer
        self.assertIn("Stream Completed Successfully:", output)
        self.assertIn("Total Chunks:    5", output)
        self.assertIn("Total Bytes:     40 bytes", output)

    def test_cli_demo_custom_arguments(self):
        """run_demo supports custom sample rate, channels, chunk count, and frames."""
        custom_args = parse_args([
            "--sample-rate", "44100",
            "--channels", "2",
            "--chunk-count", "3",
            "--frames-per-chunk", "8",
        ])

        captured_output = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = captured_output
            exit_code = run_demo(custom_args)
        finally:
            sys.stdout = old_stdout

        self.assertEqual(exit_code, 0)
        output = captured_output.getvalue()

        self.assertIn("44100 Hz", output)
        self.assertIn("Stereo (2 ch)", output)
        self.assertIn("Total Chunks:    3", output)
        # 3 chunks * 8 frames * (2 channels * 2 bytes) = 96 bytes
        self.assertIn("Total Bytes:     96 bytes", output)


if __name__ == "__main__":
    unittest.main()
