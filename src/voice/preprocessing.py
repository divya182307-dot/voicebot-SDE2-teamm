"""Audio preprocessing module: Resampling, amplitude normalization, and channel conversion.

Provides pure-Python acoustic processing tailored for Speech-to-Text streaming:
1. Linear interpolation resampling from arbitrary sampling rates (e.g., 8k, 44.1k, 48k) to target 16kHz.
2. Peak and RMS (energy/loudness) amplitude normalization with optional DC offset removal.
3. Stereo-to-mono downmixing.
4. Modular AudioPreprocessor pipeline for real-time streaming chunks or batch audio buffers.
"""

from __future__ import annotations

import array
import logging
import math
import sys
from typing import Any, List, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field

from src.voice.adapter import AudioConfig, AudioEncoding
from src.voice.exceptions import AudioPreprocessingError

logger = logging.getLogger(__name__)


class AudioPreprocessorConfig(BaseModel):
    """Configuration options for audio preprocessing pipeline."""

    model_config = ConfigDict(extra="forbid")

    target_sample_rate: int = Field(
        default=16000,
        ge=8000,
        le=48000,
        description="Target sample rate in Hz required by speech model (defaults to 16,000 Hz)",
    )
    target_channels: int = Field(
        default=1,
        ge=1,
        le=2,
        description="Target channel count (1 for mono, 2 for stereo)",
    )
    enable_resampling: bool = Field(
        default=True,
        description="Enable automatic sample rate conversion if input rate differs from target",
    )
    enable_normalization: bool = Field(
        default=True,
        description="Enable volume/amplitude normalization on audio samples",
    )
    normalization_method: str = Field(
        default="peak",
        description="Normalization algorithm: 'peak' (peak dBFS scaling), 'rms' (loudness energy), or 'none'",
    )
    target_peak_dbfs: float = Field(
        default=-1.0,
        le=0.0,
        ge=-60.0,
        description="Target peak level in dBFS relative to full scale (e.g. -1.0 dBFS = ~89.1% max scale)",
    )
    target_rms_dbfs: float = Field(
        default=-20.0,
        le=-3.0,
        ge=-60.0,
        description="Target RMS loudness level in dBFS for speech conversational consistency",
    )
    remove_dc_offset: bool = Field(
        default=True,
        description="Subtract waveform mean to eliminate microphone DC offset prior to scaling",
    )


class AudioPreprocessorMetrics(BaseModel):
    """Telemetry tracking preprocessor frame counts and conversions."""

    model_config = ConfigDict(extra="forbid")

    chunks_processed: int = Field(default=0, ge=0, description="Total chunks ingested by preprocessor")
    bytes_in: int = Field(default=0, ge=0, description="Total raw bytes ingested")
    bytes_out: int = Field(default=0, ge=0, description="Total preprocessed bytes produced")
    chunks_resampled: int = Field(default=0, ge=0, description="Chunks requiring sample rate conversion")
    chunks_normalized: int = Field(default=0, ge=0, description="Chunks processed through amplitude normalization")
    chunks_downmixed: int = Field(default=0, ge=0, description="Stereo chunks downmixed to mono")


def resample_pcm16(
    audio_bytes: bytes,
    in_rate: int,
    out_rate: int,
    channels: int = 1,
) -> bytes:
    """Resample 16-bit linear PCM audio using high-precision linear interpolation.

    Args:
        audio_bytes: Raw 16-bit signed integer little-endian PCM bytes.
        in_rate: Source sampling rate in Hz (e.g. 8000, 44100, 48000).
        out_rate: Target sampling rate in Hz (e.g. 16000).
        channels: Channel count (1 for mono, 2 for stereo).

    Returns:
        Resampled 16-bit PCM bytes.

    Raises:
        AudioPreprocessingError: If parameters or audio byte lengths are invalid.
    """
    if in_rate <= 0 or out_rate <= 0:
        raise AudioPreprocessingError(f"Sample rates must be positive. Got in={in_rate}, out={out_rate}")

    if in_rate == out_rate:
        return audio_bytes

    if not isinstance(audio_bytes, (bytes, bytearray)):
        raise AudioPreprocessingError("Audio data must be bytes or bytearray.")

    if len(audio_bytes) == 0:
        return b""

    # Validate 16-bit alignment (2 bytes per sample per channel)
    bytes_per_frame = 2 * channels
    if len(audio_bytes) % bytes_per_frame != 0:
        raise AudioPreprocessingError(
            f"Audio byte length ({len(audio_bytes)}) is not a multiple of {bytes_per_frame} bytes."
        )

    # Fast unpack into signed 16-bit integer array
    samples = array.array("h")
    samples.frombytes(audio_bytes)

    if sys.byteorder != "little":
        samples.byteswap()

    total_frames_in = len(samples) // channels
    ratio = out_rate / in_rate
    total_frames_out = int(round(total_frames_in * ratio))

    if total_frames_out == 0:
        return b""

    out_samples = array.array("h")

    if channels == 1:
        # Mono resampling
        for j in range(total_frames_out):
            src_pos = j / ratio
            idx = int(src_pos)
            alpha = src_pos - idx

            if idx + 1 < total_frames_in:
                val = int(round((1.0 - alpha) * samples[idx] + alpha * samples[idx + 1]))
            else:
                val = samples[min(idx, total_frames_in - 1)]

            out_samples.append(max(-32768, min(32767, val)))

    else:
        # Multi-channel / stereo resampling (interleaved L, R, L, R...)
        for j in range(total_frames_out):
            src_pos = j / ratio
            idx = int(src_pos)
            alpha = src_pos - idx

            for ch in range(channels):
                curr_idx = idx * channels + ch
                next_idx = (idx + 1) * channels + ch

                if idx + 1 < total_frames_in:
                    val = int(round((1.0 - alpha) * samples[curr_idx] + alpha * samples[next_idx]))
                else:
                    val = samples[min(curr_idx, len(samples) - 1)]

                out_samples.append(max(-32768, min(32767, val)))

    if sys.byteorder != "little":
        out_samples.byteswap()

    return out_samples.tobytes()


def convert_stereo_to_mono(audio_bytes: bytes) -> bytes:
    """Downmix 2-channel 16-bit PCM stereo audio to 1-channel mono by averaging channels.

    Args:
        audio_bytes: Interleaved 16-bit signed PCM stereo bytes.

    Returns:
        Mono 16-bit PCM bytes.

    Raises:
        AudioPreprocessingError: If byte length is not a multiple of 4 (2 channels * 2 bytes).
    """
    if len(audio_bytes) == 0:
        return b""

    if len(audio_bytes) % 4 != 0:
        raise AudioPreprocessingError(
            f"Stereo audio byte length ({len(audio_bytes)}) must be a multiple of 4 bytes."
        )

    samples = array.array("h")
    samples.frombytes(audio_bytes)
    if sys.byteorder != "little":
        samples.byteswap()

    mono = array.array("h")
    num_frames = len(samples) // 2
    for i in range(num_frames):
        left = samples[i * 2]
        right = samples[i * 2 + 1]
        avg = (left + right) // 2
        mono.append(max(-32768, min(32767, avg)))

    if sys.byteorder != "little":
        mono.byteswap()

    return mono.tobytes()


def normalize_amplitude_pcm16(
    audio_bytes: bytes,
    method: str = "peak",
    target_dbfs: float = -1.0,
    remove_dc_offset: bool = True,
) -> bytes:
    """Normalize 16-bit linear PCM audio amplitude to a target dBFS level.

    Args:
        audio_bytes: Raw 16-bit signed PCM bytes.
        method: Normalization strategy: 'peak', 'rms', or 'none'.
        target_dbfs: Target volume in dBFS relative to full scale (e.g., -1.0 dBFS).
        remove_dc_offset: If True, subtract mean sample value prior to gain scaling.

    Returns:
        Normalized 16-bit PCM bytes.

    Raises:
        AudioPreprocessingError: If method is invalid or audio byte buffer is malformed.
    """
    if len(audio_bytes) == 0 or method.lower() == "none":
        return audio_bytes

    if len(audio_bytes) % 2 != 0:
        raise AudioPreprocessingError(
            f"PCM 16-bit audio bytes length ({len(audio_bytes)}) must be an even number."
        )

    samples = array.array("h")
    samples.frombytes(audio_bytes)
    if sys.byteorder != "little":
        samples.byteswap()

    n = len(samples)
    if n == 0:
        return audio_bytes

    # 1. DC Offset Removal
    float_samples: List[float]
    if remove_dc_offset:
        mean_offset = sum(samples) / float(n)
        float_samples = [s - mean_offset for s in samples]
    else:
        float_samples = [float(s) for s in samples]

    # Full-scale 16-bit signed integer peak = 32767.0
    full_scale = 32767.0
    target_amplitude = (10.0 ** (target_dbfs / 20.0)) * full_scale

    method_lower = method.lower()
    gain: float = 1.0

    if method_lower == "peak":
        peak = max(abs(s) for s in float_samples) if float_samples else 0.0
        if peak > 0.0:
            gain = target_amplitude / peak
        else:
            return audio_bytes  # Complete silence

    elif method_lower == "rms":
        sum_sq = sum(s * s for s in float_samples)
        rms = math.sqrt(sum_sq / float(n))
        if rms > 0.0:
            gain = target_amplitude / rms
        else:
            return audio_bytes  # Complete silence

    else:
        raise AudioPreprocessingError(
            f"Unsupported normalization method '{method}'. Expected 'peak', 'rms', or 'none'."
        )

    # 2. Apply Gain and Clamp to 16-bit Integer Range
    out_samples = array.array("h")
    for s in float_samples:
        scaled = int(round(s * gain))
        out_samples.append(max(-32768, min(32767, scaled)))

    if sys.byteorder != "little":
        out_samples.byteswap()

    return out_samples.tobytes()


class AudioPreprocessor:
    """Unified audio preprocessing pipeline for speech-to-text chunk ingestion.

    Performs:
    1. Channel downmixing (e.g. stereo 2ch -> mono 1ch).
    2. Resampling (e.g. 44.1k/48k -> 16k Hz) using linear interpolation.
    3. Waveform DC offset centering.
    4. Amplitude normalization (peak or RMS).
    """

    def __init__(self, config: Optional[AudioPreprocessorConfig] = None) -> None:
        self._config: AudioPreprocessorConfig = config or AudioPreprocessorConfig()
        self._metrics: AudioPreprocessorMetrics = AudioPreprocessorMetrics()

    @property
    def config(self) -> AudioPreprocessorConfig:
        return self._config

    @property
    def metrics(self) -> AudioPreprocessorMetrics:
        return self._metrics.model_copy()

    def process_chunk(
        self,
        chunk: bytes,
        in_sample_rate: Optional[int] = None,
        in_channels: Optional[int] = None,
    ) -> bytes:
        """Process an audio chunk through downmixing, resampling, and normalization.

        Args:
            chunk: Input 16-bit PCM audio bytes.
            in_sample_rate: Source sample rate (defaults to target if None).
            in_channels: Source channel count (defaults to target if None).

        Returns:
            Preprocessed 16-bit PCM bytes ready for speech recognition engine.
        """
        if not isinstance(chunk, (bytes, bytearray)):
            raise AudioPreprocessingError("Input chunk must be bytes or bytearray.")

        if len(chunk) == 0:
            return b""

        self._metrics.chunks_processed += 1
        self._metrics.bytes_in += len(chunk)

        current_rate = in_sample_rate or self._config.target_sample_rate
        current_channels = in_channels or self._config.target_channels
        out = bytes(chunk)

        # 1. Downmix stereo to mono if needed
        if current_channels == 2 and self._config.target_channels == 1:
            out = convert_stereo_to_mono(out)
            current_channels = 1
            self._metrics.chunks_downmixed += 1

        # 2. Resample if rate differs
        if self._config.enable_resampling and current_rate != self._config.target_sample_rate:
            out = resample_pcm16(
                audio_bytes=out,
                in_rate=current_rate,
                out_rate=self._config.target_sample_rate,
                channels=current_channels,
            )
            self._metrics.chunks_resampled += 1

        # 3. Normalize amplitude if enabled
        if self._config.enable_normalization and self._config.normalization_method != "none":
            target_db = (
                self._config.target_rms_dbfs
                if self._config.normalization_method == "rms"
                else self._config.target_peak_dbfs
            )
            out = normalize_amplitude_pcm16(
                audio_bytes=out,
                method=self._config.normalization_method,
                target_dbfs=target_db,
                remove_dc_offset=self._config.remove_dc_offset,
            )
            self._metrics.chunks_normalized += 1

        self._metrics.bytes_out += len(out)
        return out
