"""PCM Audio Normalization and Quality Analysis for SDE Team 2, Week 3 (Days 15-16).

This module provides deterministic, format-preserving PCM amplitude normalization:
- AudioQualityMetrics: Immutable dataclass capturing peak, RMS, clipping, and dynamic range.
- AudioNormalizer: Normalizes audio samples to a consistent target peak amplitude while
  enforcing safe gain limits, zero-division protection, and hard clipping prevention.
"""

from dataclasses import dataclass
import math
import struct
from typing import Sequence

from voicebot.schemas import AudioChunk, AudioError


@dataclass(frozen=True)
class AudioQualityMetrics:
    """Quality analysis metrics for an AudioChunk.

    Fields:
        peak_amplitude: Maximum sample amplitude normalized to [0.0, 1.0].
        rms_energy: Root Mean Square energy normalized to [0.0, 1.0].
        is_clipped: True if one or more samples reached or exceeded the digital rail.
        dynamic_range_db: Ratio of peak amplitude to RMS energy in decibels (dB).
    """

    peak_amplitude: float
    rms_energy: float
    is_clipped: bool
    dynamic_range_db: float


class AudioNormalizer:
    """Normalizes raw PCM audio chunks to a standardized target amplitude.

    Guarantees:
        - Format Invariance: Preserves sample rate, channel count, and sample width.
        - Frame Alignment: Guarantees byte length is identical and an exact frame multiple.
        - Safe Gain: Limits maximum amplification gain (max_gain_db) to avoid noise boost.
        - Hard Clamping: Clamps samples within physical PCM bounds, preventing integer wrapping.
        - Zero Safety: Handles pure silence without division-by-zero errors.
    """

    def __init__(
        self,
        target_peak: float = 0.95,
        max_gain_db: float = 24.0,
    ):
        """Initialize the AudioNormalizer.

        Args:
            target_peak (float): Target peak amplitude in range (0.0, 1.0] (default: 0.95).
            max_gain_db (float): Maximum allowed amplification gain in dB (default: 24.0 dB).

        Raises:
            AudioError: If target_peak or max_gain_db are invalid.
        """
        if isinstance(target_peak, bool) or not isinstance(target_peak, (int, float)):
            raise AudioError("target_peak must be a numeric value.")
        if not (0.0 < target_peak <= 1.0):
            raise AudioError("target_peak must be between 0.0 (exclusive) and 1.0 (inclusive).")

        if isinstance(max_gain_db, bool) or not isinstance(max_gain_db, (int, float)):
            raise AudioError("max_gain_db must be a numeric value.")
        if max_gain_db < 0.0:
            raise AudioError("max_gain_db must be non-negative.")

        self.target_peak = float(target_peak)
        self.max_gain_db = float(max_gain_db)
        self._max_linear_gain = 10.0 ** (self.max_gain_db / 20.0)

    def _unpack_samples(self, chunk: AudioChunk) -> list[int]:
        """Unpack raw PCM bytes into signed integer samples."""
        data = chunk.data
        sample_width = chunk.audio_format.sample_width

        if sample_width == 2:
            # 16-bit signed PCM
            sample_count = len(data) // 2
            return list(struct.unpack(f"<{sample_count}h", data))
        elif sample_width == 1:
            # 8-bit unsigned PCM normalized around center (128)
            sample_count = len(data)
            raw = struct.unpack(f"<{sample_count}B", data)
            return [s - 128 for s in raw]
        elif sample_width == 4:
            # 32-bit signed PCM
            sample_count = len(data) // 4
            return list(struct.unpack(f"<{sample_count}i", data))
        elif sample_width == 3:
            # 24-bit signed PCM (3 bytes per sample)
            sample_count = len(data) // 3
            samples = []
            for i in range(sample_count):
                b = data[i * 3 : (i + 1) * 3]
                s = int.from_bytes(b, byteorder="little", signed=True)
                samples.append(s)
            return samples
        else:
            raise AudioError(f"Unsupported sample width: {sample_width}")

    def _pack_samples(self, samples: Sequence[int], sample_width: int) -> bytes:
        """Pack integer samples back into raw PCM bytes."""
        if sample_width == 2:
            # Clamp to 16-bit signed: [-32768, 32767]
            clamped = [max(-32768, min(32767, s)) for s in samples]
            return struct.pack(f"<{len(clamped)}h", *clamped)
        elif sample_width == 1:
            # Shift back to 8-bit unsigned: [0, 255]
            clamped = [max(0, min(255, s + 128)) for s in samples]
            return struct.pack(f"<{len(clamped)}B", *clamped)
        elif sample_width == 4:
            # Clamp to 32-bit signed: [-2147483648, 2147483647]
            clamped = [max(-2147483648, min(2147483647, s)) for s in samples]
            return struct.pack(f"<{len(clamped)}i", *clamped)
        elif sample_width == 3:
            # Clamp to 24-bit signed: [-8388608, 8388607]
            out = bytearray()
            for s in samples:
                cs = max(-8388608, min(8388607, s))
                out.extend(cs.to_bytes(3, byteorder="little", signed=True))
            return bytes(out)
        else:
            raise AudioError(f"Unsupported sample width: {sample_width}")

    def _get_max_possible_amplitude(self, sample_width: int) -> float:
        """Return the maximum theoretical integer amplitude for a given sample width."""
        if sample_width == 2:
            return 32768.0
        elif sample_width == 1:
            return 128.0
        elif sample_width == 3:
            return 8388608.0
        elif sample_width == 4:
            return 2147483648.0
        raise AudioError(f"Unsupported sample width: {sample_width}")

    def analyze_quality(self, chunk: AudioChunk) -> AudioQualityMetrics:
        """Analyze the audio quality of an AudioChunk.

        Args:
            chunk (AudioChunk): Audio chunk to evaluate.

        Returns:
            AudioQualityMetrics: Structured metrics covering peak, RMS, clipping, and dynamic range.
        """
        if not isinstance(chunk, AudioChunk):
            raise AudioError("chunk must be an instance of AudioChunk.")

        if not chunk.data:
            return AudioQualityMetrics(
                peak_amplitude=0.0,
                rms_energy=0.0,
                is_clipped=False,
                dynamic_range_db=0.0,
            )

        samples = self._unpack_samples(chunk)
        if not samples:
            return AudioQualityMetrics(
                peak_amplitude=0.0,
                rms_energy=0.0,
                is_clipped=False,
                dynamic_range_db=0.0,
            )

        max_val = self._get_max_possible_amplitude(chunk.audio_format.sample_width)
        abs_samples = [abs(s) for s in samples]
        peak = max(abs_samples)
        peak_norm = min(1.0, peak / max_val)

        sum_sq = sum((s / max_val) ** 2 for s in samples)
        rms = math.sqrt(sum_sq / len(samples))
        rms_norm = min(1.0, rms)

        # Clipping threshold: within 1 LSB of the maximum rail
        is_clipped = peak >= (max_val - 1.0)

        if rms_norm > 1e-9 and peak_norm > 1e-9:
            dyn_range = 20.0 * math.log10(peak_norm / rms_norm)
        else:
            dyn_range = 0.0

        return AudioQualityMetrics(
            peak_amplitude=round(peak_norm, 6),
            rms_energy=round(rms_norm, 6),
            is_clipped=is_clipped,
            dynamic_range_db=round(max(0.0, dyn_range), 2),
        )

    def normalize_chunk(self, chunk: AudioChunk) -> AudioChunk:
        """Normalize the amplitude of an AudioChunk to the configured target_peak.

        Args:
            chunk (AudioChunk): Incoming raw PCM audio chunk.

        Returns:
            AudioChunk: New AudioChunk with normalized PCM data, preserving format and timestamps.
        """
        if not isinstance(chunk, AudioChunk):
            raise AudioError("chunk must be an instance of AudioChunk.")

        if not chunk.data:
            return chunk

        samples = self._unpack_samples(chunk)
        if not samples:
            return chunk

        max_val = self._get_max_possible_amplitude(chunk.audio_format.sample_width)
        peak = max(abs(s) for s in samples)
        peak_norm = peak / max_val

        # Pure silence: avoid division by zero; leave chunk unmodified
        if peak_norm < 1e-7:
            return chunk

        # Calculate desired linear gain and cap by max_gain_db
        desired_gain = self.target_peak / peak_norm
        effective_gain = min(desired_gain, self._max_linear_gain)

        # Scale and clamp samples
        normalized_samples = [int(round(s * effective_gain)) for s in samples]
        normalized_data = self._pack_samples(normalized_samples, chunk.audio_format.sample_width)

        return AudioChunk(
            sequence_id=chunk.sequence_id,
            timestamp=chunk.timestamp,
            audio_format=chunk.audio_format,
            data=normalized_data,
        )

