"""Unit tests for VoiceActivityDetector and VADResult.

Week 2 (Days 10-11) Deliverables for SDE Team 2.
"""

import math
import struct
import unittest

from voicebot.schemas import AudioChunk, AudioError, AudioFormat
from voicebot.vad import VADResult, VoiceActivityDetector


class TestVADInitialization(unittest.TestCase):
    """Test suite for VoiceActivityDetector initialization and configuration."""

    def test_default_initialization(self):
        """Verify default parameters: energy_threshold=0.02, min_speech_duration_ms=100.0."""
        vad = VoiceActivityDetector()
        self.assertEqual(vad.energy_threshold, 0.02)
        self.assertEqual(vad.min_speech_duration_ms, 100.0)
        self.assertEqual(vad.continuous_speech_duration_ms, 0.0)
        self.assertEqual(vad.total_speech_chunks, 0)
        self.assertEqual(vad.total_silence_chunks, 0)

    def test_custom_initialization(self):
        """Verify custom thresholds and durations are stored correctly."""
        vad = VoiceActivityDetector(energy_threshold=0.05, min_speech_duration_ms=150.0)
        self.assertEqual(vad.energy_threshold, 0.05)
        self.assertEqual(vad.min_speech_duration_ms, 150.0)

    def test_invalid_energy_threshold(self):
        """Verify invalid energy_threshold values raise AudioError."""
        for invalid in [-0.01, 1.01, True, False, "0.05", None]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(AudioError):
                    VoiceActivityDetector(energy_threshold=invalid)  # type: ignore

    def test_invalid_min_speech_duration(self):
        """Verify invalid min_speech_duration_ms values raise AudioError."""
        for invalid in [-1.0, True, False, "100", None]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(AudioError):
                    VoiceActivityDetector(min_speech_duration_ms=invalid)  # type: ignore


class TestRMSCalculation(unittest.TestCase):
    """Test suite for mathematical accuracy of RMS energy calculations."""

    def setUp(self):
        """Create standard audio format fixtures."""
        self.format_16k_mono = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        self.format_16k_stereo = AudioFormat(sample_rate=16000, channels=2, sample_width=2)
        self.vad = VoiceActivityDetector()

    def test_pure_silence_rms_is_zero(self):
        """Verify all-zero PCM samples produce exact 0.0 RMS energy."""
        silence_data = bytes(160 * 2)  # 160 frames of 16-bit zeros = 10ms
        chunk = AudioChunk(
            sequence_id=0,
            timestamp=0.0,
            audio_format=self.format_16k_mono,
            data=silence_data,
        )
        rms = self.vad.calculate_rms(chunk)
        self.assertEqual(rms, 0.0)

    def test_full_scale_dc_rms_is_one(self):
        """Verify full scale 16-bit samples produce RMS approximately 1.0."""
        # 32767 is max positive value for 16-bit signed PCM
        data = struct.pack("<100h", *([32767] * 100))
        chunk = AudioChunk(
            sequence_id=0,
            timestamp=0.0,
            audio_format=self.format_16k_mono,
            data=data,
        )
        rms = self.vad.calculate_rms(chunk)
        self.assertAlmostEqual(rms, 1.0, places=2)

    def test_synthetic_sine_wave_rms(self):
        """Verify RMS of a pure sine wave matches theoretical V_peak / sqrt(2)."""
        sample_rate = 16000
        frequency = 400.0  # 400 Hz tone
        amplitude = 16384  # Half of full scale (approx 0.5 peak)
        sample_count = 160  # 10ms

        samples = [
            int(amplitude * math.sin(2.0 * math.pi * frequency * i / sample_rate))
            for i in range(sample_count)
        ]
        data = struct.pack(f"<{sample_count}h", *samples)
        chunk = AudioChunk(
            sequence_id=0,
            timestamp=0.0,
            audio_format=self.format_16k_mono,
            data=data,
        )
        rms = self.vad.calculate_rms(chunk)
        # Expected normalized RMS: (amplitude / 32768) / sqrt(2) = 0.5 / 1.414 ~ 0.3535
        expected_rms = (amplitude / 32768.0) / math.sqrt(2.0)
        self.assertAlmostEqual(rms, expected_rms, places=2)

    def test_stereo_rms_calculation(self):
        """Verify stereo PCM audio calculates RMS across both channels."""
        # 50 frames of stereo (100 samples)
        samples = [10000, -10000] * 50
        data = struct.pack("<100h", *samples)
        chunk = AudioChunk(
            sequence_id=0,
            timestamp=0.0,
            audio_format=self.format_16k_stereo,
            data=data,
        )
        rms = self.vad.calculate_rms(chunk)
        self.assertGreater(rms, 0.2)
        self.assertLess(rms, 0.4)

    def test_calculate_rms_invalid_chunk_type_raises_audio_error(self):
        """Verify calculate_rms rejects non-AudioChunk arguments."""
        with self.assertRaises(AudioError):
            self.vad.calculate_rms(b"raw bytes")  # type: ignore


class TestVADDebounceAndDuration(unittest.TestCase):
    """Test suite for Voice Activity Detection debouncing and minimum speech duration."""

    def setUp(self):
        """Configure VAD with 100ms minimum speech duration and standard format."""
        self.format = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        # 160 frames at 16000 Hz = 0.01s (10ms) per chunk
        self.frames_per_chunk = 160
        self.vad = VoiceActivityDetector(
            energy_threshold=0.02,
            min_speech_duration_ms=100.0,
        )

    def _create_chunk(self, sequence_id: int, amplitude: int) -> AudioChunk:
        """Helper to create a 10ms chunk with constant amplitude."""
        data = struct.pack(f"<{self.frames_per_chunk}h", *([amplitude] * self.frames_per_chunk))
        timestamp = sequence_id * (self.frames_per_chunk / self.format.sample_rate)
        return AudioChunk(
            sequence_id=sequence_id,
            timestamp=timestamp,
            audio_format=self.format,
            data=data,
        )

    def test_pure_silence_classified_as_non_speech(self):
        """Verify silence produces is_speech=False with 0ms speech duration."""
        silence_chunk = self._create_chunk(0, amplitude=0)
        result = self.vad.process_chunk(silence_chunk)

        self.assertIsInstance(result, VADResult)
        self.assertFalse(result.is_speech)
        self.assertEqual(result.energy_score, 0.0)
        self.assertEqual(result.speech_duration_ms, 0.0)
        self.assertEqual(self.vad.total_silence_chunks, 1)
        self.assertEqual(self.vad.total_speech_chunks, 0)

    def test_low_amplitude_noise_filtered_below_threshold(self):
        """Verify low-level background noise below threshold is classified as silence."""
        # Amplitude 300 / 32768 = ~0.009 RMS (below 0.02 threshold)
        low_noise_chunk = self._create_chunk(0, amplitude=300)
        result = self.vad.process_chunk(low_noise_chunk)

        self.assertFalse(result.is_speech)
        self.assertLess(result.energy_score, self.vad.energy_threshold)
        self.assertEqual(result.speech_duration_ms, 0.0)

    def test_transient_click_pop_rejected_by_debounce(self):
        """Verify short high-energy burst (e.g. 20ms click) does not trigger speech."""
        # 2 high-energy chunks (20ms total) with min_speech_duration_ms = 100ms
        chunk1 = self._create_chunk(0, amplitude=15000)  # 10ms
        chunk2 = self._create_chunk(1, amplitude=15000)  # 20ms cumulative
        chunk3_silence = self._create_chunk(2, amplitude=0)

        res1 = self.vad.process_chunk(chunk1)
        self.assertFalse(res1.is_speech)
        self.assertEqual(res1.speech_duration_ms, 10.0)

        res2 = self.vad.process_chunk(chunk2)
        self.assertFalse(res2.is_speech)
        self.assertEqual(res2.speech_duration_ms, 20.0)

        # Silence arrives: debounce timer resets
        res3 = self.vad.process_chunk(chunk3_silence)
        self.assertFalse(res3.is_speech)
        self.assertEqual(res3.speech_duration_ms, 0.0)
        self.assertEqual(self.vad.total_speech_chunks, 0)

    def test_sustained_speech_triggers_speech_classification(self):
        """Verify sustained high energy exceeding 100ms triggers is_speech=True."""
        # 12 chunks of 10ms each = 120ms total (> 100ms min_speech_duration_ms)
        results: list[VADResult] = []
        for seq in range(12):
            chunk = self._create_chunk(seq, amplitude=15000)
            results.append(self.vad.process_chunk(chunk))

        # First 9 chunks (10ms through 90ms) should be False (accumulating)
        for i in range(9):
            self.assertFalse(results[i].is_speech)
            self.assertEqual(results[i].speech_duration_ms, (i + 1) * 10.0)

        # 10th chunk reaches 100ms -> should be True!
        self.assertTrue(results[9].is_speech)
        self.assertEqual(results[9].speech_duration_ms, 100.0)

        # 11th and 12th chunks continue as True
        self.assertTrue(results[10].is_speech)
        self.assertTrue(results[11].is_speech)
        self.assertEqual(results[11].speech_duration_ms, 120.0)
        self.assertEqual(self.vad.total_speech_chunks, 3)

    def test_reset_clears_vad_state(self):
        """Verify reset() clears accumulated speech duration and chunk counters."""
        chunk = self._create_chunk(0, amplitude=15000)
        self.vad.process_chunk(chunk)
        self.assertGreater(self.vad.continuous_speech_duration_ms, 0.0)

        self.vad.reset()
        self.assertEqual(self.vad.continuous_speech_duration_ms, 0.0)
        self.assertEqual(self.vad.total_speech_chunks, 0)
        self.assertEqual(self.vad.total_silence_chunks, 0)

    def test_process_stream_helper(self):
        """Verify process_stream yields paired (AudioChunk, VADResult) tuples."""
        chunks = [self._create_chunk(i, amplitude=i * 2000) for i in range(4)]
        stream = self.vad.process_stream(iter(chunks))

        paired = list(stream)
        self.assertEqual(len(paired), 4)
        for i, (chunk, result) in enumerate(paired):
            self.assertIsInstance(chunk, AudioChunk)
            self.assertIsInstance(result, VADResult)
            self.assertEqual(chunk.sequence_id, i)
            self.assertEqual(result.chunk_sequence_id, i)


if __name__ == "__main__":
    unittest.main()

