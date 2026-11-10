"""Audio schemas and validation for SDE Team 2, Week 1.

This module defines the foundational audio data structures and custom error classes
for the voicebot audio capture pipeline:
- AudioFormat: Audio configuration specifying sample rate, channels, and sample width.
- AudioChunk: Individual slice of audio stream data with sequencing and timestamp.
- AudioError: Domain-specific exception raised for validation or format failures.
"""

from dataclasses import dataclass
import math


class AudioError(ValueError):
    """Raised when audio format or chunk validation fails.

    Subclasses ValueError so callers can catch ValueError or the specific AudioError.
    """


@dataclass(frozen=True)
class AudioFormat:
    """Describes the format specification of raw PCM audio data.

    All audio data within the pipeline conforms to this immutable configuration.

    Fields:
        sample_rate:
            - Type: int
            - Units: Hertz (Hz, samples per second)
            - Constraints: Must be a positive integer (> 0). Booleans are rejected.
        channels:
            - Type: int
            - Units: Channel count (dimensionless)
            - Constraints: Must be either 1 (mono) or 2 (stereo). Booleans are rejected.
        sample_width:
            - Type: int
            - Units: Bytes per sample per channel
            - Constraints: Must be 1, 2, 3, or 4 bytes (e.g., 2 bytes = 16-bit PCM).
                           Default is 2 bytes. Booleans are rejected.
    """

    sample_rate: int
    channels: int
    sample_width: int = 2

    def __post_init__(self):
        if isinstance(self.sample_rate, bool) or not isinstance(self.sample_rate, int):
            raise AudioError("Sample rate must be an integer in Hz.")
        if self.sample_rate <= 0:
            raise AudioError("Sample rate must be greater than 0 Hz.")

        if isinstance(self.channels, bool) or not isinstance(self.channels, int):
            raise AudioError("Channels must be an integer.")
        if self.channels not in (1, 2):
            raise AudioError("Channels must be 1 (mono) or 2 (stereo).")

        if isinstance(self.sample_width, bool) or not isinstance(self.sample_width, int):
            raise AudioError("Sample width must be an integer in bytes.")
        if self.sample_width not in (1, 2, 3, 4):
            raise AudioError("Sample width must be 1, 2, 3, or 4 bytes.")

    @property
    def bytes_per_frame(self) -> int:
        """Calculate bytes per audio frame across all channels (channels * sample_width)."""
        return self.channels * self.sample_width

    @property
    def bytes_per_second(self) -> int:
        """Calculate throughput in bytes per second (sample_rate * bytes_per_frame)."""
        return self.sample_rate * self.bytes_per_frame


@dataclass(frozen=True)
class AudioChunk:
    """Represents a discrete chunk of raw PCM audio data in a stream.

    Chunks are emitted sequentially with monotonic sequence numbering and timestamps.

    Fields:
        sequence_id:
            - Type: int
            - Units: Sequential chunk counter / index (dimensionless)
            - Constraints: Must be a non-negative integer (>= 0). Booleans are rejected.
        timestamp:
            - Type: float (or int)
            - Units: Seconds (s) elapsed since stream inception
            - Constraints: Must be a non-negative, finite real number (>= 0.0).
                           NaN and Infinity are rejected. Booleans are rejected.
        audio_format:
            - Type: AudioFormat
            - Units: Not applicable (format metadata object)
            - Constraints: Must be a valid instance of AudioFormat.
        data:
            - Type: bytes
            - Units: Raw binary PCM bytes
            - Constraints: Must be non-empty bytes. Length must be an exact multiple
                           of bytes_per_frame (channels * sample_width) so no partial
                           frames exist.
    """

    sequence_id: int
    timestamp: float
    audio_format: AudioFormat
    data: bytes

    def __post_init__(self):
        if isinstance(self.sequence_id, bool) or not isinstance(self.sequence_id, int):
            raise AudioError("Sequence ID must be an integer.")
        if self.sequence_id < 0:
            raise AudioError("Sequence ID must be non-negative.")

        if isinstance(self.timestamp, bool) or not isinstance(self.timestamp, (int, float)):
            raise AudioError("Timestamp must be a number in seconds.")
        if not math.isfinite(self.timestamp):
            raise AudioError("Timestamp must be finite.")
        if self.timestamp < 0:
            raise AudioError("Timestamp must be non-negative.")

        if not isinstance(self.audio_format, AudioFormat):
            raise AudioError("audio_format must be an AudioFormat instance.")

        if not isinstance(self.data, bytes):
            raise AudioError("Audio chunk data must be bytes.")
        if not self.data:
            raise AudioError("Audio chunk data must not be empty.")

        bytes_per_frame = self.audio_format.bytes_per_frame
        if len(self.data) % bytes_per_frame != 0:
            raise AudioError("Audio chunk size must contain complete audio frames.")

    @property
    def frame_count(self) -> int:
        """Calculate the number of complete audio frames contained in this chunk."""
        return len(self.data) // self.audio_format.bytes_per_frame

    @property
    def duration(self) -> float:
        """Calculate the duration of this audio chunk in seconds."""
        return self.frame_count / self.audio_format.sample_rate
