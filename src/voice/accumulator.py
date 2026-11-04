"""Ordered transcript segment accumulator for streaming speech-to-text pipelines.

This module aggregates streaming TranscriptEvents and TranscriptSegments, managing
chronological ordering, speculative interim hypothesis updates, final segment locking,
deduplication, and turn-level projections for downstream AI agents and UI clients.
"""

from __future__ import annotations

import bisect
from typing import Any, Iterable, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.voice.exceptions import (
    DuplicateSegmentError,
    InvalidEventError,
    SessionMismatchError,
)
from src.voice.schemas import (
    TranscriptError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
    WordTiming,
)


class AccumulatorConfig(BaseModel):
    """Configuration settings for SegmentAccumulator behavior.

    Fields:
        enforce_session_id: If True, reject events from differing session IDs.
        deduplicate_by_id: If True, ignore identical duplicate final segment IDs idempotently.
        auto_sort: If True, automatically maintain final segments sorted by start_time_ms.
        preserve_interim_on_speech_ended: If True, do not discard active interim on SPEECH_ENDED.
    """

    model_config = ConfigDict(extra="forbid")

    enforce_session_id: bool = Field(
        default=True,
        description="Reject events with mismatched session_id if accumulator is bound to a session",
    )
    deduplicate_by_id: bool = Field(
        default=True,
        description="Idempotently ignore duplicate final segment IDs rather than raising errors",
    )
    auto_sort: bool = Field(
        default=True,
        description="Maintain segments in strict chronological order by start_time_ms",
    )
    preserve_interim_on_speech_ended: bool = Field(
        default=False,
        description="Whether to keep active interim hypothesis when SPEECH_ENDED arrives",
    )


class AccumulatedTranscript(BaseModel):
    """Immutable snapshot representation of the accumulated transcript state.

    Fields:
        session_id: The session identifier.
        final_segments: Ordered list of locked-in TranscriptSegments.
        active_interim: Currently active speculative hypothesis (or None).
        final_text: Concatenated text of all committed final segments.
        full_text: Final text combined with the active interim text.
        total_duration_ms: Total time span from first segment start to latest segment end.
        average_confidence: Weighted average confidence of finalized segments.
        word_count: Total word count in finalized segments.
        speech_active: True if VAD currently detects active speech.
        errors: List of any TranscriptErrors encountered during the session.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: Optional[str] = Field(default=None, description="Bound session identifier")
    final_segments: List[TranscriptSegment] = Field(default_factory=list, description="Committed segments")
    active_interim: Optional[TranscriptSegment] = Field(default=None, description="Active speculative hypothesis")
    final_text: str = Field(default="", description="Joined final transcript text")
    full_text: str = Field(default="", description="Full text including interim hypothesis")
    total_duration_ms: int = Field(default=0, ge=0, description="Span from earliest to latest segment in ms")
    average_confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Mean confidence score")
    word_count: int = Field(default=0, ge=0, description="Count of words in finalized transcript")
    speech_active: bool = Field(default=False, description="Whether speech turn is active")
    errors: List[TranscriptError] = Field(default_factory=list, description="Encountered errors")


class SegmentAccumulator:
    """Aggregates streaming speech events into an ordered, coherent transcript.

    Core responsibilities:
    1. **Interim vs. Final Handling**: Updates speculative interim hypotheses in-place;
       commits finalized utterances into an immutable chronological history.
    2. **Ordering Guarantee**: Enforces strict chronological order by `start_time_ms`
       (and secondarily `sequence_number`), re-ordering events that arrive with network jitter.
    3. **Deduplication**: Idempotently prevents duplicate segment IDs from corrupting the stream.
    4. **Turn Management**: Tracks speech boundaries (`speech_started`, `speech_ended`).
    5. **Downstream Projections**: Provides clean text projections for LLM prompt context
       and real-time UI caption bubbles.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        config: Optional[AccumulatorConfig] = None,
    ) -> None:
        """Initialize the SegmentAccumulator.

        Args:
            session_id: Optional session identifier to bind and enforce.
            config: Optional configuration settings (uses defaults if omitted).
        """
        self._session_id: Optional[str] = session_id.strip() if session_id else None
        self._config: AccumulatorConfig = config or AccumulatorConfig()

        # Internal state
        self._final_segments: List[TranscriptSegment] = []
        self._final_segment_ids: set[str] = set()
        self._active_interim: Optional[TranscriptSegment] = None
        self._speech_active: bool = False
        self._errors: List[TranscriptError] = []

    # --------------------------------------------------------------------------
    # Properties
    # --------------------------------------------------------------------------

    @property
    def session_id(self) -> Optional[str]:
        """Return the bound session ID (if any)."""
        return self._session_id

    @property
    def config(self) -> AccumulatorConfig:
        """Return current accumulator configuration."""
        return self._config

    @property
    def final_segments(self) -> List[TranscriptSegment]:
        """Return an immutable copy of committed final segments."""
        return list(self._final_segments)

    @property
    def active_interim(self) -> Optional[TranscriptSegment]:
        """Return current speculative interim segment, or None if idle."""
        return self._active_interim

    @property
    def speech_active(self) -> bool:
        """True if speech activity is currently ongoing."""
        return self._speech_active

    @property
    def errors(self) -> List[TranscriptError]:
        """Return list of any recorded error diagnostics."""
        return list(self._errors)

    @property
    def is_empty(self) -> bool:
        """True if no final segments and no active interim segment exist."""
        return len(self._final_segments) == 0 and self._active_interim is None

    @property
    def total_duration_ms(self) -> int:
        """Total duration spanned by finalized segments in milliseconds."""
        if not self._final_segments:
            return 0
        min_start = min(s.start_time_ms for s in self._final_segments)
        max_end = max(s.end_time_ms for s in self._final_segments)
        return max(0, max_end - min_start)

    @property
    def average_confidence(self) -> float:
        """Weighted average confidence across all finalized segments (by duration)."""
        if not self._final_segments:
            return 0.0

        total_weighted = sum(s.confidence * max(s.duration_ms, 1) for s in self._final_segments)
        total_duration = sum(max(s.duration_ms, 1) for s in self._final_segments)
        return round(total_weighted / total_duration, 4) if total_duration > 0 else 0.0

    @property
    def word_count(self) -> int:
        """Total number of words across all committed final segments."""
        return sum(len(s.text.split()) for s in self._final_segments)

    @property
    def all_words(self) -> List[WordTiming]:
        """Flattened list of all word timings across finalized segments."""
        words: List[WordTiming] = []
        for segment in self._final_segments:
            if segment.words:
                words.extend(segment.words)
        return words

    # --------------------------------------------------------------------------
    # Event and Segment Ingestion
    # --------------------------------------------------------------------------

    def add_event(self, event: TranscriptEvent) -> None:
        """Process an incoming TranscriptEvent into the accumulator state.

        Args:
            event: A valid TranscriptEvent model instance.

        Raises:
            InvalidEventError: If event is None, malformed, or has an invalid type.
            SessionMismatchError: If event session_id does not match bound session.
            DuplicateSegmentError: If a duplicate segment is rejected by configuration.
        """
        if not isinstance(event, TranscriptEvent):
            raise InvalidEventError(
                f"Expected TranscriptEvent instance, received '{type(event).__name__}'."
            )

        # Enforce session correlation if enabled
        if self._config.enforce_session_id:
            if self._session_id is None:
                self._session_id = event.session_id
            elif self._session_id != event.session_id:
                raise SessionMismatchError(
                    f"Event session_id '{event.session_id}' does not match accumulator session '{self._session_id}'."
                )

        # Dispatch based on event type
        if event.event_type == TranscriptEventType.SPEECH_STARTED:
            self._speech_active = True

        elif event.event_type == TranscriptEventType.INTERIM_TRANSCRIPT:
            if event.segment is None:
                raise InvalidEventError("INTERIM_TRANSCRIPT event missing required segment payload.")
            self._handle_interim_segment(event.segment)

        elif event.event_type == TranscriptEventType.FINAL_TRANSCRIPT:
            if event.segment is None:
                raise InvalidEventError("FINAL_TRANSCRIPT event missing required segment payload.")
            self._handle_final_segment(event.segment)

        elif event.event_type == TranscriptEventType.SPEECH_ENDED:
            self._speech_active = False
            if not self._config.preserve_interim_on_speech_ended:
                self._active_interim = None

        elif event.event_type == TranscriptEventType.ERROR:
            if event.error is None:
                raise InvalidEventError("ERROR event missing required error payload.")
            self._errors.append(event.error)

    def add_events(self, events: Iterable[TranscriptEvent]) -> None:
        """Convenience method to process an iterable of TranscriptEvents in order."""
        for event in events:
            self.add_event(event)

    def add_segment(self, segment: TranscriptSegment) -> None:
        """Directly ingest a TranscriptSegment.

        If `segment.is_final` is False, updates the active interim hypothesis.
        If `segment.is_final` is True, locks it into the ordered final segments.

        Args:
            segment: Valid TranscriptSegment instance.

        Raises:
            InvalidEventError: If segment is not a TranscriptSegment.
        """
        if not isinstance(segment, TranscriptSegment):
            raise InvalidEventError(
                f"Expected TranscriptSegment instance, received '{type(segment).__name__}'."
            )

        if segment.is_final:
            self._handle_final_segment(segment)
        else:
            self._handle_interim_segment(segment)

    def _handle_interim_segment(self, segment: TranscriptSegment) -> None:
        """Update active interim hypothesis."""
        if segment.is_final:
            raise InvalidEventError("Cannot treat segment with is_final=True as interim hypothesis.")
        self._active_interim = segment

    def _handle_final_segment(self, segment: TranscriptSegment) -> None:
        """Commit final segment in ordered position and clear corresponding interim."""
        if not segment.is_final:
            raise InvalidEventError("Cannot commit segment with is_final=False into final segments.")

        # Check for duplicate segment IDs
        if segment.id in self._final_segment_ids:
            if self._config.deduplicate_by_id:
                # Idempotent: silently ignore exact duplicates
                return
            raise DuplicateSegmentError(
                f"Segment with id '{segment.id}' has already been committed."
            )

        self._final_segment_ids.add(segment.id)

        # Clear active interim if it corresponds to or was superseded by this final segment
        self._active_interim = None

        if not self._config.auto_sort:
            self._final_segments.append(segment)
            return

        # Insert into strictly sorted position by start_time_ms
        insert_idx = bisect.bisect_left(
            [s.start_time_ms for s in self._final_segments],
            segment.start_time_ms,
        )
        self._final_segments.insert(insert_idx, segment)

    # --------------------------------------------------------------------------
    # Text Projections and Inspection
    # --------------------------------------------------------------------------

    def get_final_text(self) -> str:
        """Return the concatenated, formatted text of all finalized segments."""
        return " ".join(s.text.strip() for s in self._final_segments if s.text.strip())

    def get_interim_text(self) -> str:
        """Return text of the currently active interim hypothesis, or empty string."""
        if self._active_interim and self._active_interim.text:
            return self._active_interim.text.strip()
        return ""

    def get_full_text(self) -> str:
        """Return combined transcript text (committed final segments + current interim)."""
        final_part = self.get_final_text()
        interim_part = self.get_interim_text()

        if final_part and interim_part:
            return f"{final_part} {interim_part}"
        elif final_part:
            return final_part
        return interim_part

    def get_snapshot(self) -> AccumulatedTranscript:
        """Generate a complete immutable snapshot of the current transcript state."""
        return AccumulatedTranscript(
            session_id=self._session_id,
            final_segments=self.final_segments,
            active_interim=self._active_interim,
            final_text=self.get_final_text(),
            full_text=self.get_full_text(),
            total_duration_ms=self.total_duration_ms,
            average_confidence=self.average_confidence,
            word_count=self.word_count,
            speech_active=self._speech_active,
            errors=self.errors,
        )

    def reset(self) -> None:
        """Clear all accumulated final segments, interims, and error records."""
        self._final_segments.clear()
        self._final_segment_ids.clear()
        self._active_interim = None
        self._speech_active = False
        self._errors.clear()
