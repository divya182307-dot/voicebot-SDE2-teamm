"""Custom exceptions for the Voice and Speech-to-Text module."""

from typing import Any, Optional


class VoiceError(Exception):
    """Base exception for all voice pipeline errors."""

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class SchemaValidationError(VoiceError):
    """Raised when transcript payload or segment fails validation rules."""

    def __init__(self, message: str, invalid_field: Optional[str] = None, details: Optional[dict[str, Any]] = None):
        super().__init__(message, details)
        self.invalid_field = invalid_field


class InvalidTimeRangeError(SchemaValidationError):
    """Raised when segment end_time_ms is less than start_time_ms or timestamps are negative."""

    pass


class InvalidConfidenceError(SchemaValidationError):
    """Raised when confidence score is outside the [0.0, 1.0] interval."""

    pass


class TranscriberError(VoiceError):
    """Base exception for speech-to-text transcriber operations and adapters."""

    pass


class TranscriberConnectionError(TranscriberError):
    """Raised when connection to an STT service or streaming socket fails."""

    pass


class TranscriberStateError(TranscriberError):
    """Raised when a transcriber method is invoked in an invalid lifecycle state."""

    pass


class TranscriberAudioError(TranscriberError):
    """Raised when an audio chunk or configuration is invalid or malformed."""

    pass


class AccumulatorError(VoiceError):
    """Base exception for transcript segment accumulator operations."""

    pass


class SessionMismatchError(AccumulatorError):
    """Raised when an event belonging to an unexpected session is added to an accumulator."""

    pass


class InvalidEventError(AccumulatorError):
    """Raised when an invalid event, segment, or payload is fed to the accumulator."""

    pass


class DuplicateSegmentError(AccumulatorError):
    """Raised when a final segment with an existing ID or incompatible overlap is rejected."""

    pass


