"""Transcript schemas and event data models for Speech-to-Text (STT) pipeline.

This module defines the canonical data contracts used across the voice pipeline,
backend services, agent orchestrator, and desktop UI client.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TranscriptEventType(str, Enum):
    """Enumeration of transcript event types emitted during streaming speech processing."""

    SPEECH_STARTED = "speech_started"
    INTERIM_TRANSCRIPT = "interim_transcript"
    FINAL_TRANSCRIPT = "final_transcript"
    SPEECH_ENDED = "speech_ended"
    ERROR = "error"


class WordTiming(BaseModel):
    """Word-level timing information for synchronized visual rendering and highlighting.

    Fields:
        word: The spoken word token.
        start_time_ms: Start offset from audio onset in milliseconds (>= 0).
        end_time_ms: End offset from audio onset in milliseconds (>= start_time_ms).
        confidence: Word transcription confidence score [0.0, 1.0].
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    word: str = Field(..., min_length=1, description="Transcribed word token")
    start_time_ms: int = Field(..., ge=0, description="Start offset in milliseconds from audio start")
    end_time_ms: int = Field(..., ge=0, description="End offset in milliseconds from audio start")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0")

    @model_validator(mode="after")
    def validate_time_range(self) -> WordTiming:
        if self.end_time_ms < self.start_time_ms:
            raise ValueError(
                f"end_time_ms ({self.end_time_ms}) cannot be less than start_time_ms ({self.start_time_ms})"
            )
        return self


class TranscriptSegment(BaseModel):
    """Atomic unit of transcribed speech representing a phrase, sentence, or utterance.

    Fields:
        id: Unique identifier for the segment.
        start_time_ms: Start offset in milliseconds from audio stream onset (unit: ms, ge: 0).
        end_time_ms: End offset in milliseconds from audio stream onset (unit: ms, ge: 0).
        text: Transcribed text content.
        confidence: Normalized confidence score from speech recognizer (range: [0.0, 1.0]).
        is_final: Flag indicating whether this segment is final (immutable) or interim (speculative).
        language: BCP-47 / ISO language code (e.g. 'en', 'en-US', 'es', 'hi').
        words: Optional list of word-level timings for sub-segment precision.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for the transcript segment",
    )
    start_time_ms: int = Field(
        ...,
        ge=0,
        description="Start timestamp in milliseconds relative to audio stream start (unit: ms, constraint: >= 0)",
    )
    end_time_ms: int = Field(
        ...,
        ge=0,
        description="End timestamp in milliseconds relative to audio stream start (unit: ms, constraint: >= start_time_ms)",
    )
    text: str = Field(
        ...,
        description="Transcribed text string",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score assigned by STT engine (unit: normalized probability, constraint: [0.0, 1.0])",
    )
    is_final: bool = Field(
        default=False,
        description="True if segment is finalized/locked; False if interim/speculative hypothesis",
    )
    language: str = Field(
        default="en",
        description="Language code compliant with ISO 639-1 / BCP-47 (e.g., 'en', 'en-US')",
    )
    words: Optional[List[WordTiming]] = Field(
        default=None,
        description="Optional list of word-level timing breakdown",
    )

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Segment text must contain at least one non-whitespace character")
        return stripped

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        lang_code = value.strip()
        # Regex matching ISO 639-1 / BCP-47 language codes (e.g., "en", "en-US", "es-419", "zh-CN")
        pattern = r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})?$"
        if not re.match(pattern, lang_code):
            raise ValueError(
                f"Invalid language code '{value}'. Must follow ISO 639-1 / BCP-47 format (e.g., 'en', 'en-US')."
            )
        return lang_code

    @model_validator(mode="after")
    def validate_timestamps(self) -> TranscriptSegment:
        if self.end_time_ms < self.start_time_ms:
            raise ValueError(
                f"end_time_ms ({self.end_time_ms}) must be greater than or equal to start_time_ms ({self.start_time_ms})"
            )
        return self

    @property
    def duration_ms(self) -> int:
        """Calculate duration of the segment in milliseconds."""
        return self.end_time_ms - self.start_time_ms


class TranscriptError(BaseModel):
    """Structured error payload for speech recognition failures.

    Fields:
        code: Machine-readable error code string (e.g., 'AUDIO_TIMEOUT', 'PROVIDER_ERROR').
        message: Human-readable error description.
        details: Optional dictionary containing additional diagnostic context.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(..., min_length=1, description="Machine-readable error identifier")
    message: str = Field(..., min_length=1, description="Human-readable error description")
    details: Optional[dict[str, Any]] = Field(default=None, description="Diagnostic attributes and context")


class TranscriptEvent(BaseModel):
    """Canonical event payload emitted over the voice pipeline message bus / WebSockets.

    Fields:
        event_id: Unique event tracking ID.
        session_id: Client interaction session ID.
        event_type: The type of event (SPEECH_STARTED, INTERIM_TRANSCRIPT, etc.).
        timestamp: UTC timestamp of event generation.
        segment: Associated TranscriptSegment (required for INTERIM_TRANSCRIPT and FINAL_TRANSCRIPT).
        error: Associated TranscriptError (required when event_type is ERROR).
        sequence_number: Optional sequential message counter for ordering verification.
        metadata: Optional dictionary with custom provider or client attributes.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Globally unique identifier for this event",
    )
    session_id: str = Field(
        ...,
        min_length=1,
        description="Session identifier correlating user requests",
    )
    event_type: TranscriptEventType = Field(
        ...,
        description="Classification of the transcript event",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="ISO-8601 UTC timestamp of event creation",
    )
    segment: Optional[TranscriptSegment] = Field(
        default=None,
        description="Transcript segment payload for interim and final events",
    )
    error: Optional[TranscriptError] = Field(
        default=None,
        description="Error details payload for error events",
    )
    sequence_number: Optional[int] = Field(
        default=None,
        ge=0,
        description="Sequential index of the event within the stream",
    )
    metadata: Optional[dict[str, Any]] = Field(
        default=None,
        description="Extensible metadata dictionary for provider diagnostics or telemetry",
    )

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("session_id cannot be empty or blank")
        return stripped

    @model_validator(mode="after")
    def validate_event_payload_consistency(self) -> TranscriptEvent:
        # Validate segment presence and state based on event_type
        if self.event_type in (TranscriptEventType.INTERIM_TRANSCRIPT, TranscriptEventType.FINAL_TRANSCRIPT):
            if self.segment is None:
                raise ValueError(f"Event type '{self.event_type.value}' requires a non-null 'segment' field.")

            if self.event_type == TranscriptEventType.FINAL_TRANSCRIPT and not self.segment.is_final:
                raise ValueError("Event type 'final_transcript' must have segment.is_final=True.")

            if self.event_type == TranscriptEventType.INTERIM_TRANSCRIPT and self.segment.is_final:
                raise ValueError("Event type 'interim_transcript' must have segment.is_final=False.")

        elif self.event_type == TranscriptEventType.ERROR:
            if self.error is None:
                raise ValueError("Event type 'error' requires a non-null 'error' field.")

        else:
            # SPEECH_STARTED and SPEECH_ENDED should not carry segments or errors
            if self.error is not None:
                raise ValueError(f"Event type '{self.event_type.value}' must not include an 'error' payload.")

        return self
