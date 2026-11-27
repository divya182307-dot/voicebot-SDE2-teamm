"""Unit test suite for AudioNormalizer and AudioQualityMetrics.

Week 3 (Days 15-16) validation for SDE Team 2.
"""

import math
import struct
import unittest

from voicebot.normalizer import AudioNormalizer, AudioQualityMetrics
from voicebot.schemas import AudioChunk, AudioError, AudioFormat


class TestAudioNormalizer(unittest.TestCase):
    """Test cases for PCM amplitude normalization and quality metrics."""

    def setUp(self) -> None:
        self.format_16k_mono = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        self.format_8k_stereo = AudioFormat(sample_rate=8000, channels=2, sample_width=2)
        self.format_8bit = AudioFormat(sample_rate=16000, channels=1, sample_width=1)
        self.format_32bit = AudioFormat(sample_rate=16000, channels=1, sample_width=4)
        self.normalizer = AudioNormalizer(target_peak=0.95, max_gain_db=24.0)

    def _generate_pcm_16bit(self, samples: list[int]) -> bytes:
        return struct.pack(f"<{len(samples)}h", *samples)

    def test_normalizer_initialization_valid(self) -> None:
        """Verify normalizer initializes with valid defaults and custom attributes."""
        norm = AudioNormalizer(target_peak=0.8, max_gain_db=18.0)
        self.assertAlmostEqual(norm.target_peak, 0.8)
        self.assertAlmostEqual(norm.max_gain_db, 18.0)

    def test_normalizer_initialization_invalid_peak(self) -> None:
        """Verify normalizer rejects invalid target_peak values."""
        invalid_peaks = [0.0, -0.5, 1.2, "0.95", True, None]
        for val in invalid_peaks:
            with self.subTest(val=val):
                with self.assertRaises(AudioError):
                    AudioNormalizer(target_peak=val)  # type: ignore

    def test_normalizer_initialization_invalid_gain(self) -> None:
        """Verify normalizer rejects invalid max_gain_db values."""
        invalid_gains = [-1.0, -20.0, "12.0", False, None]
        for val in invalid_gains:
            with self.subTest(val=val):
                with self.assertRaises(AudioError):
                    AudioNormalizer(max_gain_db=val)  # type: ignore

    def test_normalize_quiet_chunk_amplification(self) -> None:
        """Verify low-amplitude signal is amplified to target peak."""
        # Max sample = 3276 (~0.10 normalized peak)
        raw_samples = [0, 1000, 2000, 3276, -1500, -3276, 500, 0]
        chunk = AudioChunk(
            sequence_id=0,
            timestamp=0.0,
            audio_format=self.format_16k_mono,
            data=self._generate_pcm_16bit(raw_samples),
        )

        normalized = self.normalizer.normalize_chunk(chunk)

        # Check metadata preservation
        self.assertEqual(normalized.sequence_id, chunk.sequence_id)
        self.assertEqual(normalized.timestamp, chunk.timestamp)
        self.assertEqual(normalized.audio_format, chunk.audio_format)
        self.assertEqual(len(normalized.data), len(chunk.data))

        # Check sample amplitudes scaled to ~0.95 * 32768 = ~31129
        norm_samples = list(struct.unpack(f"<{len(raw_samples)}h", normalized.data))
        peak = max(abs(s) for s in norm_samples)
        expected_peak = int(round(0.95 * 32768))
        self.assertAlmostEqual(peak, expected_peak, delta=20)

    def test_normalize_loud_chunk_clamping(self) -> None:
        """Verify samples at or near rails do not wrap or overflow."""
        raw_samples = [32000, -32000, 32760, -32760]
        chunk = AudioChunk(
            sequence_id=1,
            timestamp=0.02,
            audio_format=self.format_16k_mono,
            data=self._generate_pcm_16bit(raw_samples),
        )

        normalized = self.normalizer.normalize_chunk(chunk)
        norm_samples = list(struct.unpack(f"<{len(raw_samples)}h", normalized.data))

        for s in norm_samples:
            self.assertTrue(-32768 <= s <= 32767)

    def test_normalize_silence_safety(self) -> None:
        """Verify pure zero PCM is untouched and does not cause division by zero."""
        chunk = AudioChunk(
            sequence_id=2,
            timestamp=0.04,
            audio_format=self.format_16k_mono,
            data=b"\x00" * 320,
        )

        normalized = self.normalizer.normalize_chunk(chunk)
        self.assertEqual(normalized.data, chunk.data)

    def test_normalize_8bit_unsigned_pcm(self) -> None:
        """Verify 8-bit unsigned PCM scaling around center (128)."""
        raw_samples = [128, 140, 116, 128]
        chunk = AudioChunk(
            sequence_id=3,
            timestamp=0.06,
            audio_format=self.format_8bit,
            data=bytes(raw_samples),
        )

        normalized = self.normalizer.normalize_chunk(chunk)
        self.assertEqual(len(normalized.data), len(chunk.data))
        norm_samples = list(normalized.data)
        for s in norm_samples:
            self.assertTrue(0 <= s <= 255)

    def test_normalize_32bit_signed_pcm(self) -> None:
        """Verify 32-bit signed PCM scaling."""
        raw_samples = [0, 50000000, -50000000, 100000000]
        data = struct.pack(f"<{len(raw_samples)}i", *raw_samples)
        chunk = AudioChunk(
            sequence_id=4,
            timestamp=0.08,
            audio_format=self.format_32bit,
            data=data,
        )

        normalized = self.normalizer.normalize_chunk(chunk)
        self.assertEqual(len(normalized.data), len(chunk.data))
        norm_samples = struct.unpack(f"<{len(raw_samples)}i", normalized.data)
        for s in norm_samples:
            self.assertTrue(-2147483648 <= s <= 2147483647)

    def test_normalize_24bit_signed_pcm(self) -> None:
        """Verify 24-bit signed PCM scaling, exact values, limits, and frame alignment."""
        format_24bit = AudioFormat(sample_rate=16000, channels=1, sample_width=3)
        raw_samples = [0, 2000000, -2000000, 4000000]
        out = bytearray()
        for s in raw_samples:
            out.extend(s.to_bytes(3, byteorder="little", signed=True))
        chunk = AudioChunk(
            sequence_id=5,
            timestamp=0.10,
            audio_format=format_24bit,
            data=bytes(out),
        )

        normalized = self.normalizer.normalize_chunk(chunk)

        # 1. Byte length and frame alignment remain unchanged
        self.assertEqual(len(normalized.data), len(chunk.data))
        self.assertEqual(len(normalized.data), len(raw_samples) * 3)
        self.assertEqual(len(normalized.data) % format_24bit.bytes_per_frame, 0)
        self.assertEqual(normalized.audio_format, chunk.audio_format)
        self.assertEqual(normalized.sequence_id, chunk.sequence_id)
        self.assertEqual(normalized.timestamp, chunk.timestamp)

        # 2. Unpack normalized 24-bit signed samples
        unpacked = []
        for i in range(len(raw_samples)):
            b = normalized.data[i * 3 : (i + 1) * 3]
            unpacked.append(int.from_bytes(b, byteorder="little", signed=True))

        # 3. Verify actual sample values are correctly scaled to target peak 0.95
        # Expected peak = int(round(0.95 * 8388608)) = 7969178
        expected_peak = int(round(0.95 * 8388608))
        self.assertEqual(unpacked[0], 0)
        self.assertAlmostEqual(unpacked[3], expected_peak, delta=5)
        self.assertAlmostEqual(unpacked[1], expected_peak // 2, delta=5)
        self.assertAlmostEqual(unpacked[2], -(expected_peak // 2), delta=5)

        # 4. Verify all samples stay strictly within signed 24-bit physical limits
        for s in unpacked:
            self.assertTrue(-8388608 <= s <= 8388607)

    def test_analyze_quality_clean_and_clipped(self) -> None:
        """Verify analyze_quality correctly computes metrics and flags clipping."""
        # Unclipped chunk
        clean_samples = [0, 10000, -10000, 5000]
        clean_chunk = AudioChunk(
            sequence_id=5,
            timestamp=0.10,
            audio_format=self.format_16k_mono,
            data=self._generate_pcm_16bit(clean_samples),
        )
        metrics = self.normalizer.analyze_quality(clean_chunk)
        self.assertFalse(metrics.is_clipped)
        self.assertAlmostEqual(metrics.peak_amplitude, 10000 / 32768.0, places=4)
        self.assertGreater(metrics.rms_energy, 0.0)

        # Clipped chunk
        clipped_samples = [0, 32767, -32768]
        clipped_chunk = AudioChunk(
            sequence_id=6,
            timestamp=0.12,
            audio_format=self.format_16k_mono,
            data=self._generate_pcm_16bit(clipped_samples),
        )
        clipped_metrics = self.normalizer.analyze_quality(clipped_chunk)
        self.assertTrue(clipped_metrics.is_clipped)
        self.assertAlmostEqual(clipped_metrics.peak_amplitude, 1.0, places=3)

    def test_reject_non_audio_chunk(self) -> None:
        """Verify normalize_chunk and analyze_quality reject invalid input types."""
        with self.assertRaises(AudioError):
            self.normalizer.normalize_chunk("invalid")  # type: ignore
        with self.assertRaises(AudioError):
            self.normalizer.analyze_quality([1, 2, 3])  # type: ignore


if __name__ == "__main__":
    unittest.main()

