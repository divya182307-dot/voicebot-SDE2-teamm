"""Unit tests for AudioChunk, AudioFormat, and AudioError schemas (Week 1, Day 1-2)."""

from dataclasses import FrozenInstanceError
import math
import unittest

from voicebot.schemas import AudioChunk, AudioError, AudioFormat


class TestAudioError(unittest.TestCase):
    """Verify that AudioError behaves properly as a custom ValueError subclass."""

    def test_audio_error_is_value_error(self):
        """AudioError must subclass ValueError for standard Python exception handling."""
        self.assertTrue(issubclass(AudioError, ValueError))

    def test_audio_error_message(self):
        """AudioError preserves and displays the custom error message."""
        err = AudioError("Sample rate must be greater than 0 Hz.")
        self.assertEqual(str(err), "Sample rate must be greater than 0 Hz.")
        self.assertIsInstance(err, ValueError)


class TestAudioFormat(unittest.TestCase):
    """Verify validation, constraints, and immutability of AudioFormat."""

    def test_valid_audio_format_defaults(self):
        """Valid initialization with default sample_width (2 bytes = 16-bit PCM)."""
        fmt = AudioFormat(sample_rate=16000, channels=1)
        self.assertEqual(fmt.sample_rate, 16000)
        self.assertEqual(fmt.channels, 1)
        self.assertEqual(fmt.sample_width, 2)
        self.assertEqual(fmt.bytes_per_frame, 2)
        self.assertEqual(fmt.bytes_per_second, 32000)

    def test_valid_audio_format_stereo_and_widths(self):
        """Valid initialization with stereo channels and various valid sample widths."""
        for width in (1, 2, 3, 4):
            fmt = AudioFormat(sample_rate=44100, channels=2, sample_width=width)
            self.assertEqual(fmt.sample_rate, 44100)
            self.assertEqual(fmt.channels, 2)
            self.assertEqual(fmt.sample_width, width)
            self.assertEqual(fmt.bytes_per_frame, 2 * width)
            self.assertEqual(fmt.bytes_per_second, 44100 * 2 * width)

    def test_invalid_sample_rate_type(self):
        """Sample rate must be an int, not bool, float, str, or None."""
        invalid_types = [True, False, 16000.0, "16000", None, [16000]]
        for val in invalid_types:
            with self.subTest(val=val):
                with self.assertRaises(AudioError) as ctx:
                    AudioFormat(sample_rate=val, channels=1)
                self.assertEqual(str(ctx.exception), "Sample rate must be an integer in Hz.")

    def test_invalid_sample_rate_value(self):
        """Sample rate must be strictly greater than 0 Hz."""
        invalid_values = [0, -1, -16000]
        for val in invalid_values:
            with self.subTest(val=val):
                with self.assertRaises(AudioError) as ctx:
                    AudioFormat(sample_rate=val, channels=1)
                self.assertEqual(str(ctx.exception), "Sample rate must be greater than 0 Hz.")

    def test_invalid_channels_type(self):
        """Channels must be an int, not bool, float, str, or None."""
        invalid_types = [True, False, 1.0, "1", None, (1,)]
        for val in invalid_types:
            with self.subTest(val=val):
                with self.assertRaises(AudioError) as ctx:
                    AudioFormat(sample_rate=16000, channels=val)
                self.assertEqual(str(ctx.exception), "Channels must be an integer.")

    def test_invalid_channels_value(self):
        """Channels must be either 1 (mono) or 2 (stereo)."""
        invalid_channels = [0, 3, 4, 6, 8, -1]
        for val in invalid_channels:
            with self.subTest(val=val):
                with self.assertRaises(AudioError) as ctx:
                    AudioFormat(sample_rate=16000, channels=val)
                self.assertEqual(str(ctx.exception), "Channels must be 1 (mono) or 2 (stereo).")

    def test_invalid_sample_width_type(self):
        """Sample width must be an int, not bool, float, str, or None."""
        invalid_types = [True, False, 2.0, "2", None]
        for val in invalid_types:
            with self.subTest(val=val):
                with self.assertRaises(AudioError) as ctx:
                    AudioFormat(sample_rate=16000, channels=1, sample_width=val)
                self.assertEqual(str(ctx.exception), "Sample width must be an integer in bytes.")

    def test_invalid_sample_width_value(self):
        """Sample width must be 1, 2, 3, or 4 bytes."""
        invalid_widths = [0, 5, 8, -1]
        for val in invalid_widths:
            with self.subTest(val=val):
                with self.assertRaises(AudioError) as ctx:
                    AudioFormat(sample_rate=16000, channels=1, sample_width=val)
                self.assertEqual(str(ctx.exception), "Sample width must be 1, 2, 3, or 4 bytes.")

    def test_audio_format_immutability(self):
        """AudioFormat is frozen and its attributes cannot be modified."""
        fmt = AudioFormat(sample_rate=16000, channels=1)
        with self.assertRaises(FrozenInstanceError):
            fmt.sample_rate = 48000
        with self.assertRaises(FrozenInstanceError):
            fmt.channels = 2


class TestAudioChunk(unittest.TestCase):
    """Verify validation, constraints, and immutability of AudioChunk."""

    def setUp(self):
        """Create a standard format fixture for chunk testing."""
        self.format_mono = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        self.format_stereo = AudioFormat(sample_rate=16000, channels=2, sample_width=2)

    def test_valid_audio_chunk(self):
        """Valid initialization of AudioChunk with correct frame alignment."""
        # 4 frames of mono 16-bit = 8 bytes
        raw_data = b"\x00\x00\x01\x00\x02\x00\x03\x00"
        chunk = AudioChunk(
            sequence_id=0,
            timestamp=0.0,
            audio_format=self.format_mono,
            data=raw_data,
        )
        self.assertEqual(chunk.sequence_id, 0)
        self.assertEqual(chunk.timestamp, 0.0)
        self.assertEqual(chunk.audio_format, self.format_mono)
        self.assertEqual(chunk.data, raw_data)
        self.assertEqual(chunk.frame_count, 4)
        self.assertAlmostEqual(chunk.duration, 4 / 16000)

    def test_valid_audio_chunk_stereo(self):
        """Valid initialization of stereo chunk."""
        # 2 frames of stereo 16-bit = 2 * (2 channels * 2 bytes) = 8 bytes
        raw_data = b"\x00\x00\x00\x00\x01\x00\x01\x00"
        chunk = AudioChunk(
            sequence_id=5,
            timestamp=0.25,
            audio_format=self.format_stereo,
            data=raw_data,
        )
        self.assertEqual(chunk.sequence_id, 5)
        self.assertEqual(chunk.timestamp, 0.25)
        self.assertEqual(chunk.frame_count, 2)
        self.assertAlmostEqual(chunk.duration, 2 / 16000)

    def test_invalid_sequence_id_type(self):
        """Sequence ID must be an int, not bool, float, str, or None."""
        invalid_types = [True, False, 1.5, "0", None]
        for val in invalid_types:
            with self.subTest(val=val):
                with self.assertRaises(AudioError) as ctx:
                    AudioChunk(
                        sequence_id=val,
                        timestamp=0.0,
                        audio_format=self.format_mono,
                        data=b"\x00\x00",
                    )
                self.assertEqual(str(ctx.exception), "Sequence ID must be an integer.")

    def test_invalid_sequence_id_negative(self):
        """Sequence ID must be non-negative."""
        with self.assertRaises(AudioError) as ctx:
            AudioChunk(
                sequence_id=-1,
                timestamp=0.0,
                audio_format=self.format_mono,
                data=b"\x00\x00",
            )
        self.assertEqual(str(ctx.exception), "Sequence ID must be non-negative.")

    def test_invalid_timestamp_type(self):
        """Timestamp must be numeric (int or float), not bool, str, or None."""
        invalid_types = [True, False, "0.0", None, [0.0]]
        for val in invalid_types:
            with self.subTest(val=val):
                with self.assertRaises(AudioError) as ctx:
                    AudioChunk(
                        sequence_id=0,
                        timestamp=val,
                        audio_format=self.format_mono,
                        data=b"\x00\x00",
                    )
                self.assertEqual(str(ctx.exception), "Timestamp must be a number in seconds.")

    def test_invalid_timestamp_value(self):
        """Timestamp must be finite and non-negative."""
        invalid_values = [
            (-0.001, "Timestamp must be non-negative."),
            (-10.0, "Timestamp must be non-negative."),
            (float("nan"), "Timestamp must be finite."),
            (float("inf"), "Timestamp must be finite."),
            (float("-inf"), "Timestamp must be finite."),
        ]
        for val, expected_msg in invalid_values:
            with self.subTest(val=val):
                with self.assertRaises(AudioError) as ctx:
                    AudioChunk(
                        sequence_id=0,
                        timestamp=val,
                        audio_format=self.format_mono,
                        data=b"\x00\x00",
                    )
                self.assertEqual(str(ctx.exception), expected_msg)

    def test_invalid_audio_format_instance(self):
        """audio_format must be an AudioFormat instance."""
        invalid_formats = [None, "AudioFormat", {"sample_rate": 16000}]
        for val in invalid_formats:
            with self.subTest(val=val):
                with self.assertRaises(AudioError) as ctx:
                    AudioChunk(
                        sequence_id=0,
                        timestamp=0.0,
                        audio_format=val,
                        data=b"\x00\x00",
                    )
                self.assertEqual(str(ctx.exception), "audio_format must be an AudioFormat instance.")

    def test_invalid_data_type(self):
        """Audio chunk data must be bytes."""
        invalid_data = ["raw string", [0, 0], None, 123]
        for val in invalid_data:
            with self.subTest(val=val):
                with self.assertRaises(AudioError) as ctx:
                    AudioChunk(
                        sequence_id=0,
                        timestamp=0.0,
                        audio_format=self.format_mono,
                        data=val,
                    )
                self.assertEqual(str(ctx.exception), "Audio chunk data must be bytes.")

    def test_empty_data(self):
        """Audio chunk data must not be empty."""
        with self.assertRaises(AudioError) as ctx:
            AudioChunk(
                sequence_id=0,
                timestamp=0.0,
                audio_format=self.format_mono,
                data=b"",
            )
        self.assertEqual(str(ctx.exception), "Audio chunk data must not be empty.")

    def test_incomplete_audio_frames(self):
        """Data length must be a multiple of bytes_per_frame."""
        # format_mono bytes_per_frame = 2 (channels=1, width=2)
        # Passing 3 bytes has a 1-byte remainder
        with self.assertRaises(AudioError) as ctx:
            AudioChunk(
                sequence_id=0,
                timestamp=0.0,
                audio_format=self.format_mono,
                data=b"\x00\x01\x02",
            )
        self.assertEqual(str(ctx.exception), "Audio chunk size must contain complete audio frames.")

        # format_stereo bytes_per_frame = 4 (channels=2, width=2)
        # Passing 6 bytes has a 2-byte remainder
        with self.assertRaises(AudioError) as ctx:
            AudioChunk(
                sequence_id=0,
                timestamp=0.0,
                audio_format=self.format_stereo,
                data=b"\x00\x01\x02\x03\x04\x05",
            )
        self.assertEqual(str(ctx.exception), "Audio chunk size must contain complete audio frames.")

    def test_audio_chunk_immutability(self):
        """AudioChunk is frozen and its attributes cannot be modified."""
        chunk = AudioChunk(
            sequence_id=0,
            timestamp=0.0,
            audio_format=self.format_mono,
            data=b"\x00\x00",
        )
        with self.assertRaises(FrozenInstanceError):
            chunk.sequence_id = 1
        with self.assertRaises(FrozenInstanceError):
            chunk.timestamp = 1.0
        with self.assertRaises(FrozenInstanceError):
            chunk.data = b"\x01\x01"


class TestSchemaDocumentation(unittest.TestCase):
    """Verify that all fields are documented with types, units, and constraints."""

    def test_audio_format_docstring(self):
        """AudioFormat docstring must document sample_rate, channels, and sample_width."""
        doc = AudioFormat.__doc__
        self.assertIsNotNone(doc)
        for field in ("sample_rate", "channels", "sample_width"):
            self.assertIn(field, doc)
        for term in ("Type", "Units", "Constraints"):
            self.assertIn(term, doc)

    def test_audio_chunk_docstring(self):
        """AudioChunk docstring must document sequence_id, timestamp, audio_format, and data."""
        doc = AudioChunk.__doc__
        self.assertIsNotNone(doc)
        for field in ("sequence_id", "timestamp", "audio_format", "data"):
            self.assertIn(field, doc)
        for term in ("Type", "Units", "Constraints"):
            self.assertIn(term, doc)


if __name__ == "__main__":
    unittest.main()
