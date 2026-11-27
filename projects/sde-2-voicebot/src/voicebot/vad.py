"""Voice Activity Detection (VAD) module for SDE Team 2, Week 2 (Days 10-11).

This module defines deterministic, RMS-based energy Voice Activity Detection:
- VADResult: Immutable classification result for an AudioChunk.
- VoiceActivityDetector: Configurable VAD computing normalized RMS energy and applying
  minimum speech duration debouncing to filter out short transient noise (clicks, pops).
"""

from dataclasses import dataclass
import math
import struct
from typing import Iterator

from voicebot.schemas import AudioChunk, AudioError


@dataclass(frozen=True)
class VADResult:
    """Represents the classification result of Voice Activity Detection for an AudioChunk.

    Fields:
        is_speech: Whether active human speech is detected. True only when energy
                   meets the threshold AND speech duration reaches min_speech_duration_ms.
        energy_score: Normalized Root Mean Square (RMS) energy score in range [0.0, 1.0].
        speech_duration_ms: Accumulated duration (ms) of continuous active speech.
        confidence: Confidence score in range [0.0, 1.0].
        chunk_sequence_id: Sequence ID of the analyzed AudioChunk.
    """

    is_speech: bool
    energy_score: float
    speech_duration_ms: float
    confidence: float
    chunk_sequence_id: int


class VoiceActivityDetector:
    """Deterministic, energy-based Voice Activity Detector with duration debouncing.

    Features:
        - Configurable energy threshold (RMS amplitude on [0.0, 1.0] scale).
        - Configurable minimum speech duration in milliseconds.
        - Frame debouncing: short acoustic transients (keyboard taps, clicks, pops)
          shorter than min_speech_duration_ms are classified as non-speech.
        - Support for 8-bit, 16-bit, 24-bit, and 32-bit PCM audio in mono and stereo.
    """

    def __init__(
        self,
        energy_threshold: float = 0.02,
        min_speech_duration_ms: float = 100.0,
    ):
        """Initialize the Voice Activity Detector.

        Args:
            energy_threshold (float): Minimum normalized RMS energy [0.0, 1.0]
                                      required to consider a frame speech (default: 0.02).
            min_speech_duration_ms (float): Minimum consecutive speech duration in ms
                                            required to trigger is_speech=True (default: 100.0ms).

        Raises:
            AudioError: If energy_threshold or min_speech_duration_ms are invalid.
        """
        if isinstance(energy_threshold, bool) or not isinstance(energy_threshold, (int, float)):
            raise AudioError("energy_threshold must be a numeric value.")
        if not (0.0 <= energy_threshold <= 1.0):
            raise AudioError("energy_threshold must be between 0.0 and 1.0.")

        if isinstance(min_speech_duration_ms, bool) or not isinstance(min_speech_duration_ms, (int, float)):
            raise AudioError("min_speech_duration_ms must be a numeric value.")
        if min_speech_duration_ms < 0.0:
            raise AudioError("min_speech_duration_ms must be non-negative.")

        self.energy_threshold = float(energy_threshold)
        self.min_speech_duration_ms = float(min_speech_duration_ms)

        self._continuous_speech_duration_ms: float = 0.0
        self._total_speech_chunks: int = 0
        self._total_silence_chunks: int = 0

    @property
    def continuous_speech_duration_ms(self) -> float:
        """Return the current continuous speech duration in milliseconds."""
        return self._continuous_speech_duration_ms

    @property
    def total_speech_chunks(self) -> int:
        """Return the cumulative number of chunks classified as active speech."""
        return self._total_speech_chunks

    @property
    def total_silence_chunks(self) -> int:
        """Return the cumulative number of chunks classified as silence/noise."""
        return self._total_silence_chunks

    def reset(self) -> None:
        """Reset internal debouncing state and counters."""
        self._continuous_speech_duration_ms = 0.0
        self._total_speech_chunks = 0
        self._total_silence_chunks = 0

    def calculate_rms(self, chunk: AudioChunk) -> float:
        """Calculate normalized Root Mean Square (RMS) energy score [0.0, 1.0] of an AudioChunk.

        Args:
            chunk (AudioChunk): Audio chunk to analyze.

        Returns:
            float: Normalized RMS amplitude between 0.0 (pure silence) and 1.0 (full scale).

        Raises:
            AudioError: If chunk is not an AudioChunk instance or format is unsupported.
        """
        if not isinstance(chunk, AudioChunk):
            raise AudioError("chunk must be an instance of AudioChunk.")

        data = chunk.data
        if not data:
            return 0.0

        sample_width = chunk.audio_format.sample_width

        if sample_width == 2:
            # 16-bit signed PCM (standard)
            sample_count = len(data) // 2
            samples = struct.unpack(f"<{sample_count}h", data)
            sum_squares = sum((s / 32768.0) ** 2 for s in samples)
            rms = math.sqrt(sum_squares / sample_count)
        elif sample_width == 1:
            # 8-bit unsigned PCM
            sample_count = len(data)
            samples = struct.unpack(f"<{sample_count}B", data)
            sum_squares = sum(((s - 128) / 128.0) ** 2 for s in samples)
            rms = math.sqrt(sum_squares / sample_count)
        elif sample_width == 4:
            # 32-bit signed PCM
            sample_count = len(data) // 4
            samples = struct.unpack(f"<{sample_count}i", data)
            sum_squares = sum((s / 2147483648.0) ** 2 for s in samples)
            rms = math.sqrt(sum_squares / sample_count)
        elif sample_width == 3:
            # 24-bit signed PCM (3 bytes per sample)
            sample_count = len(data) // 3
            sum_squares = 0.0
            for i in range(sample_count):
                b = data[i * 3 : (i + 1) * 3]
                s = int.from_bytes(b, byteorder="little", signed=True)
                sum_squares += (s / 8388608.0) ** 2
            rms = math.sqrt(sum_squares / sample_count)
        else:
            raise AudioError(f"Unsupported sample width: {sample_width}")

        return min(1.0, max(0.0, rms))

    def process_chunk(self, chunk: AudioChunk) -> VADResult:
        """Process an AudioChunk and determine voice activity status with duration debouncing.

        Args:
            chunk (AudioChunk): Incoming raw PCM audio chunk.

        Returns:
            VADResult: Classification result containing speech status, RMS energy, and confidence.
        """
        energy_score = self.calculate_rms(chunk)
        chunk_duration_ms = chunk.duration * 1000.0

        has_speech_energy = energy_score >= self.energy_threshold

        if has_speech_energy:
            self._continuous_speech_duration_ms += chunk_duration_ms
            # Speech is only confirmed if continuous energy meets min_speech_duration_ms
            if self._continuous_speech_duration_ms >= self.min_speech_duration_ms:
                is_speech = True
                self._total_speech_chunks += 1
            else:
                # Energy detected, but duration too short (e.g. click, pop, cough spike)
                is_speech = False
                self._total_silence_chunks += 1
        else:
            # Energy dropped below threshold: reset consecutive speech counter
            self._continuous_speech_duration_ms = 0.0
            is_speech = False
            self._total_silence_chunks += 1

        # Calculate confidence metric [0.0, 1.0]
        denom = max(self.energy_threshold, 0.001)
        if is_speech:
            confidence = min(1.0, 0.5 + (energy_score / (2.0 * denom)))
        else:
            confidence = min(1.0, 0.5 + ((self.energy_threshold - energy_score) / (2.0 * denom)))
        confidence = max(0.0, min(1.0, confidence))

        return VADResult(
            is_speech=is_speech,
            energy_score=round(energy_score, 6),
            speech_duration_ms=round(self._continuous_speech_duration_ms, 2),
            confidence=round(confidence, 4),
            chunk_sequence_id=chunk.sequence_id,
        )

    def process_stream(
        self, chunks: Iterator[AudioChunk]
    ) -> Iterator[tuple[AudioChunk, VADResult]]:
        """Process an iterator of AudioChunk instances and yield (chunk, VADResult) pairs.

        Args:
            chunks (Iterator[AudioChunk]): Sequence of audio chunks.

        Yields:
            tuple[AudioChunk, VADResult]: Each chunk paired with its VAD result.
        """
        for chunk in chunks:
            result = self.process_chunk(chunk)
            yield chunk, result

