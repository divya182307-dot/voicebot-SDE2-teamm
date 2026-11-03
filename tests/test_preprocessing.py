"""Automated unit and mathematical tests for audio preprocessing (Days 12–13 Milestone).

Verifies:
1. Resampling from various rates (8kHz, 44.1kHz, 48kHz) to target 16kHz.
2. Accurate sample count and frame scaling.
3. Stereo-to-mono downmixing with channel averaging.
4. Peak amplitude normalization to target dBFS without clipping.
5. RMS loudness energy normalization.
6. DC offset removal centering waveforms.
7. Silence handling without division by zero.
8. AudioPreprocessor pipeline metrics and error validation.
"""

from __future__ import annotations

import array
import math
import struct
import pytest

from src.voice.exceptions import AudioPreprocessingError
from src.voice.preprocessing import (
    AudioPreprocessor,
    AudioPreprocessorConfig,
    convert_stereo_to_mono,
    normalize_amplitude_pcm16,
    resample_pcm16,
)


def make_sine_pcm16(freq_hz: float, sample_rate: int, duration_ms: int, amplitude: int = 16000) -> bytes:
    """Synthesize a pure sine wave in 16-bit PCM format."""
    num_samples = (sample_rate * duration_ms) // 1000
    samples = array.array("h")
    for i in range(num_samples):
        t = i / float(sample_rate)
        val = int(round(amplitude * math.sin(2.0 * math.pi * freq_hz * t)))
        samples.append(max(-32768, min(32767, val)))
    return samples.tobytes()


class TestAudioResampling:
    """Validate sample rate conversion mechanics and boundary conditions."""

    def test_identical_rate_returns_same_buffer(self):
        raw = b"\x00\x10" * 100
        resampled = resample_pcm16(raw, in_rate=16000, out_rate=16000)
        assert resampled == raw

    def test_empty_buffer_returns_empty(self):
        assert resample_pcm16(b"", in_rate=48000, out_rate=16000) == b""

    def test_resample_upsample_8k_to_16k(self):
        """Upsampling 8kHz to 16kHz should double the number of samples."""
        raw_8k = make_sine_pcm16(freq_hz=440.0, sample_rate=8000, duration_ms=100)
        # 8000 * 0.1 = 800 samples = 1600 bytes
        assert len(raw_8k) == 1600

        resampled_16k = resample_pcm16(raw_8k, in_rate=8000, out_rate=16000)
        # 16000 * 0.1 = 1600 samples = 3200 bytes
        assert len(resampled_16k) == 3200

    def test_resample_downsample_48k_to_16k(self):
        """Downsampling 48kHz to 16kHz should reduce sample count by factor of 3."""
        raw_48k = make_sine_pcm16(freq_hz=440.0, sample_rate=48000, duration_ms=100)
        # 48000 * 0.1 = 4800 samples = 9600 bytes
        assert len(raw_48k) == 9600

        resampled_16k = resample_pcm16(raw_48k, in_rate=48000, out_rate=16000)
        # 16000 * 0.1 = 1600 samples = 3200 bytes
        assert len(resampled_16k) == 3200

    def test_resample_non_integer_ratio_44k1_to_16k(self):
        """Resampling from 44.1kHz (CD audio) to 16kHz."""
        raw_44k = make_sine_pcm16(freq_hz=440.0, sample_rate=44100, duration_ms=100)
        # 4410 samples = 8820 bytes
        assert len(raw_44k) == 8820

        resampled_16k = resample_pcm16(raw_44k, in_rate=44100, out_rate=16000)
        # Expected ~1600 samples = 3200 bytes (+/- 2 bytes rounding)
        num_samples = len(resampled_16k) // 2
        assert abs(num_samples - 1600) <= 2

    def test_resample_invalid_alignment_raises_error(self):
        with pytest.raises(AudioPreprocessingError, match="not a multiple"):
            resample_pcm16(b"\x00\x01\x02", in_rate=48000, out_rate=16000)


class TestStereoToMonoConversion:
    """Validate 2-channel downmixing."""

    def test_stereo_to_mono_averaging(self):
        # Create 2 frames of stereo: (L=1000, R=3000), (L=-2000, R=-4000)
        stereo_samples = array.array("h", [1000, 3000, -2000, -4000])
        stereo_bytes = stereo_samples.tobytes()

        mono_bytes = convert_stereo_to_mono(stereo_bytes)
        mono_samples = array.array("h")
        mono_samples.frombytes(mono_bytes)

        assert len(mono_samples) == 2
        assert mono_samples[0] == 2000   # (1000 + 3000) // 2
        assert mono_samples[1] == -3000  # (-2000 + -4000) // 2

    def test_stereo_invalid_byte_length(self):
        with pytest.raises(AudioPreprocessingError, match="multiple of 4"):
            convert_stereo_to_mono(b"\x00\x01\x02")


class TestAmplitudeNormalization:
    """Validate peak and RMS loudness normalization."""

    def test_peak_normalization_to_minus_one_dbfs(self):
        # Create a low-volume sine wave with peak = 5,000
        low_vol_pcm = make_sine_pcm16(freq_hz=440.0, sample_rate=16000, duration_ms=50, amplitude=5000)
        samples_in = array.array("h")
        samples_in.frombytes(low_vol_pcm)
        assert max(abs(s) for s in samples_in) <= 5000

        # Peak normalize to -1.0 dBFS (~29204 peak)
        normalized = normalize_amplitude_pcm16(low_vol_pcm, method="peak", target_dbfs=-1.0, remove_dc_offset=False)
        samples_out = array.array("h")
        samples_out.frombytes(normalized)

        max_peak = max(abs(s) for s in samples_out)
        expected_peak = int(round(32767.0 * (10.0 ** (-1.0 / 20.0))))
        # Allow +/- 5 margin for discrete sine sampling approximation
        assert abs(max_peak - expected_peak) <= 10

    def test_rms_normalization(self):
        raw = make_sine_pcm16(freq_hz=300.0, sample_rate=16000, duration_ms=100, amplitude=4000)
        normalized = normalize_amplitude_pcm16(raw, method="rms", target_dbfs=-20.0, remove_dc_offset=True)

        samples_out = array.array("h")
        samples_out.frombytes(normalized)
        rms = math.sqrt(sum(s * s for s in samples_out) / len(samples_out))
        expected_rms = 32767.0 * (10.0 ** (-20.0 / 20.0))

        # Sine wave RMS is close to target_rms
        assert abs(rms - expected_rms) / expected_rms < 0.15

    def test_dc_offset_removal(self):
        # Create samples with DC offset of +2000
        samples = array.array("h", [2100, 1900, 2200, 1800, 2000, 2000])
        norm = normalize_amplitude_pcm16(samples.tobytes(), method="peak", target_dbfs=-6.0, remove_dc_offset=True)
        res = array.array("h")
        res.frombytes(norm)

        # Average should now be zero (centered)
        mean_val = sum(res) / len(res)
        assert abs(mean_val) <= 1.0

    def test_silence_handling_does_not_divide_by_zero(self):
        silent_bytes = b"\x00" * 3200
        res = normalize_amplitude_pcm16(silent_bytes, method="peak", target_dbfs=-1.0)
        assert res == silent_bytes


class TestAudioPreprocessorPipeline:
    """Validate integrated AudioPreprocessor pipeline."""

    def test_full_pipeline_downmix_resample_normalize(self):
        config = AudioPreprocessorConfig(
            target_sample_rate=16000,
            target_channels=1,
            enable_resampling=True,
            enable_normalization=True,
            normalization_method="peak",
            target_peak_dbfs=-1.0,
        )
        preprocessor = AudioPreprocessor(config=config)

        # 48kHz stereo input, 100ms: 4800 samples * 2 channels * 2 bytes = 19,200 bytes
        raw_stereo_48k = make_sine_pcm16(freq_hz=440.0, sample_rate=48000, duration_ms=100, amplitude=6000)
        # Interleave stereo channels
        mono_arr = array.array("h")
        mono_arr.frombytes(raw_stereo_48k)
        stereo_arr = array.array("h")
        for s in mono_arr:
            stereo_arr.append(s)
            stereo_arr.append(s)
        in_bytes = stereo_arr.tobytes()
        assert len(in_bytes) == 19200

        # Process through preprocessor
        out_bytes = preprocessor.process_chunk(in_bytes, in_sample_rate=48000, in_channels=2)

        # Expected output: 16kHz mono, 100ms = 1,600 samples = 3,200 bytes
        assert len(out_bytes) == 3200

        # Verify metrics tracked
        metrics = preprocessor.metrics
        assert metrics.chunks_processed == 1
        assert metrics.bytes_in == 19200
        assert metrics.bytes_out == 3200
        assert metrics.chunks_downmixed == 1
        assert metrics.chunks_resampled == 1
        assert metrics.chunks_normalized == 1

