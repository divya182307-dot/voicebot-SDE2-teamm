"""Transcript ordering, duplicate suppression, and interim/final reconciliation engine.

This module provides the core reconciliation logic for streaming speech-to-text pipelines:
1. Chronological ordering and out-of-order segment insertion.
2. Multi-layer deduplication (event IDs, segment IDs, content/time overlaps, repeated interims).
3. Interim vs. final reconciliation (stale interim suppression, overlap trimming, hypothesis commitment).
"""

from __future__ import annotations

import bisect
import logging
from typing import (
    Dict,
    Iterable,
    List,
    Optional,
    Set,
    Tuple,
)

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

logger = logging.getLogger(__name__)


class ReconciliationConfig(BaseModel):
    """Configuration settings for transcript reconciliation and deduplication.

    Fields:
        deduplicate_events: If True, suppress duplicate events with identical event_id.
        deduplicate_segments_by_id: If True, suppress duplicate final segments with identical segment id.
        deduplicate_by_content: If True, suppress segments with identical [start, end] and normalized text.
        suppress_repeated_interims: If True, suppress consecutive identical interim hypotheses.
        suppress_stale_interims: If True, drop speculative interims whose end_time_ms <= latest committed final.
        reconcile_overlapping_interims: If True, trim interim start_time_ms if it overlaps committed final speech.
        auto_sort_finals: If True, maintain committed final segments in strict chronological order.
        promote_interim_on_speech_ended: If True, promote active interim to final segment when speech ends.
        enforce_session_id: If True, reject events with mismatched session_id.
    """

    model_config = ConfigDict(extra="forbid")

    deduplicate_events: bool = Field(
        default=True,
        description="Filter duplicate events with identical event_id",
    )
    deduplicate_segments_by_id: bool = Field(
        default=True,
        description="Idempotently suppress duplicate final segments with identical id",
    )
    deduplicate_by_content: bool = Field(
        default=True,
        description="Suppress segments with identical timing and normalized text content",
    )
    suppress_repeated_interims: bool = Field(
        default=True,
        description="Suppress consecutive interim events with identical hypothesis text",
    )
    suppress_stale_interims: bool = Field(
        default=True,
        description="Drop interim events that fall entirely behind committed final transcripts",
    )
    reconcile_overlapping_interims: bool = Field(
        default=True,
        description="Trim interim boundaries if they overlap already committed final speech",
    )
    auto_sort_finals: bool = Field(
        default=True,
        description="Keep committed final segments strictly sorted chronologically by start_time_ms",
    )
    promote_interim_on_speech_ended: bool = Field(
        default=False,
        description="Promote remaining speculative interim to final transcript upon SPEECH_ENDED",
    )
    enforce_session_id: bool = Field(
        default=True,
        description="Validate and enforce matching session IDs across all ingested events",
    )


class ReconciliationMetrics(BaseModel):
    """Telemetry metrics tracking deduplication, ordering, and reconciliation events."""

    model_config = ConfigDict(extra="forbid")

    total_events_processed: int = Field(default=0, ge=0, description="Total events ingested")
    duplicates_suppressed: int = Field(default=0, ge=0, description="Total duplicate events/segments filtered")
    duplicate_events_count: int = Field(default=0, ge=0, description="Count of duplicate event_ids filtered")
    duplicate_segments_count: int = Field(default=0, ge=0, description="Count of duplicate segment_ids filtered")
    content_duplicates_count: int = Field(default=0, ge=0, description="Count of duplicate content segments filtered")
    repeated_interims_count: int = Field(default=0, ge=0, description="Consecutive identical interims filtered")
    stale_interims_count: int = Field(default=0, ge=0, description="Stale/superseded interims dropped")
    out_of_order_resolved: int = Field(default=0, ge=0, description="Out-of-order final segments reordered")
    finals_committed: int = Field(default=0, ge=0, description="Count of final segments locked into transcript")
    interims_promoted: int = Field(default=0, ge=0, description="Interims promoted to final on speech conclusion")


class TranscriptReconciler:
    """Manages stream ordering, deduplication, and interim-to-final reconciliation.

    Core Responsibilities (Days 10–11 Milestone):
    1. **Strict Chronological Ordering**: Auto-sorts segments using bisection insertion on
       `start_time_ms` with tie-breaking on `end_time_ms` and segment ID.
    2. **Multi-Stage Duplicate Suppression**:
       - Suppresses duplicate `event_id` occurrences.
       - Suppresses duplicate segment IDs.
       - Suppresses temporal/content duplicates (exact same window and text).
       - Suppresses repeated consecutive identical interim hypotheses.
    3. **Interim/Final Reconciliation**:
       - Discards stale interims that arrive after a final segment has already committed that audio window.
       - Reconciles overlapping interims against committed final boundaries.
       - Locks final segments in-place and clears superseded interim hypotheses.
       - Optionally promotes uncommitted interims to final transcripts on speech conclusion.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        config: Optional[ReconciliationConfig] = None,
    ) -> None:
        """Initialize the transcript reconciler.

        Args:
            session_id: Optional session identifier. Bound on first event if omitted.
            config: Optional reconciliation configuration flags.
        """
        self._session_id: Optional[str] = session_id.strip() if session_id else None
        self._config: ReconciliationConfig = config or ReconciliationConfig()

        # Final committed segments history
        self._final_segments: List[TranscriptSegment] = []
        self._final_segment_ids: Set[str] = set()
        self._committed_content_keys: Set[Tuple[int, int, str]] = set()

        # Interim tracking
        self._active_interim: Optional[TranscriptSegment] = None
        self._last_emitted_interim_text: Optional[str] = None

        # Tracking seen event IDs
        self._seen_event_ids: Set[str] = set()

        # Telemetry metrics
        self._metrics: ReconciliationMetrics = ReconciliationMetrics()

    # --------------------------------------------------------------------------
    # Properties
    # --------------------------------------------------------------------------

    @property
    def session_id(self) -> Optional[str]:
        """Return the bound session ID (if any)."""
        return self._session_id

    @property
    def config(self) -> ReconciliationConfig:
        """Return current reconciliation configuration."""
        return self._config

    @property
    def metrics(self) -> ReconciliationMetrics:
        """Return a copy of the reconciliation telemetry metrics."""
        return self._metrics.model_copy()

    @property
    def final_segments(self) -> List[TranscriptSegment]:
        """Return an immutable snapshot list of committed final segments."""
        return list(self._final_segments)

    @property
    def active_interim(self) -> Optional[TranscriptSegment]:
        """Return the current active interim hypothesis (or None)."""
        return self._active_interim

    @property
    def latest_final_end_time_ms(self) -> int:
        """Return the maximum end_time_ms across all committed final segments."""
        if not self._final_segments:
            return 0
        return max(s.end_time_ms for s in self._final_segments)

    # --------------------------------------------------------------------------
    # Reconciliation Pipeline
    # --------------------------------------------------------------------------

    def reconcile_event(self, event: TranscriptEvent) -> Optional[TranscriptEvent]:
        """Process and reconcile an incoming TranscriptEvent.

        Returns:
            The reconciled TranscriptEvent to be dispatched downstream, or None
            if the event was filtered/suppressed (e.g. duplicate or stale interim).

        Raises:
            InvalidEventError: If event is None or malformed.
            SessionMismatchError: If event session_id conflicts with bound session.
            DuplicateSegmentError: If duplicate segment is rejected by configuration.
        """
        if not isinstance(event, TranscriptEvent):
            raise InvalidEventError(
                f"Expected TranscriptEvent instance, received '{type(event).__name__}'."
            )

        self._metrics.total_events_processed += 1

        # Enforce session correlation
        if self._config.enforce_session_id:
            if self._session_id is None:
                self._session_id = event.session_id
            elif self._session_id != event.session_id:
                raise SessionMismatchError(
                    f"Event session_id '{event.session_id}' does not match reconciler session '{self._session_id}'."
                )

        # 1. Event-level deduplication
        if self._config.deduplicate_events:
            if event.event_id in self._seen_event_ids:
                self._metrics.duplicates_suppressed += 1
                self._metrics.duplicate_events_count += 1
                logger.debug("Suppressed duplicate event_id '%s'", event.event_id)
                return None
            self._seen_event_ids.add(event.event_id)

        # 2. Dispatch based on event type
        if event.event_type == TranscriptEventType.FINAL_TRANSCRIPT:
            if event.segment is None:
                raise InvalidEventError("FINAL_TRANSCRIPT event missing required segment payload.")
            reconciled_segment = self.reconcile_final_segment(event.segment)
            if reconciled_segment is None:
                return None
            # Return event with reconciled segment
            return event.model_copy(update={"segment": reconciled_segment})

        elif event.event_type == TranscriptEventType.INTERIM_TRANSCRIPT:
            if event.segment is None:
                raise InvalidEventError("INTERIM_TRANSCRIPT event missing required segment payload.")
            reconciled_segment = self.reconcile_interim_segment(event.segment)
            if reconciled_segment is None:
                return None
            return event.model_copy(update={"segment": reconciled_segment})

        elif event.event_type == TranscriptEventType.SPEECH_ENDED:
            return self._handle_speech_ended(event)

        elif event.event_type == TranscriptEventType.SPEECH_STARTED:
            return event

        elif event.event_type == TranscriptEventType.ERROR:
            if event.error is None:
                raise InvalidEventError("ERROR event missing required error payload.")
            return event

        return event

    def reconcile_final_segment(self, segment: TranscriptSegment) -> Optional[TranscriptSegment]:
        """Reconcile and commit a final TranscriptSegment.

        Returns:
            The committed TranscriptSegment, or None if suppressed as a duplicate.

        Raises:
            DuplicateSegmentError: If segment ID was already committed and deduplicate_segments_by_id=False.
        """
        if not segment.is_final:
            raise InvalidEventError("Cannot commit segment with is_final=False as a final segment.")

        # Check duplicate segment ID
        if segment.id in self._final_segment_ids:
            if self._config.deduplicate_segments_by_id:
                self._metrics.duplicates_suppressed += 1
                self._metrics.duplicate_segments_count += 1
                logger.debug("Suppressed duplicate final segment id '%s'", segment.id)
                return None
            raise DuplicateSegmentError(f"Segment with id '{segment.id}' has already been committed.")

        # Check content and temporal duplicate (exact same time window and text)
        content_key = (segment.start_time_ms, segment.end_time_ms, segment.text.strip().lower())
        if self._config.deduplicate_by_content and content_key in self._committed_content_keys:
            self._metrics.duplicates_suppressed += 1
            self._metrics.content_duplicates_count += 1
            logger.debug("Suppressed duplicate content segment at [%d, %d]: '%s'",
                         segment.start_time_ms, segment.end_time_ms, segment.text)
            return None

        # Check if segment arrived out-of-order relative to the latest committed segment
        if self._final_segments and segment.start_time_ms < self._final_segments[-1].start_time_ms:
            self._metrics.out_of_order_resolved += 1
            logger.debug(
                "Detected out-of-order final segment '%s' (start: %dms < latest: %dms)",
                segment.id,
                segment.start_time_ms,
                self._final_segments[-1].start_time_ms,
            )

        # Commit segment to history
        self._final_segment_ids.add(segment.id)
        self._committed_content_keys.add(content_key)
        self._metrics.finals_committed += 1

        # Reconcile active interim hypothesis
        if self._active_interim is not None:
            if (
                self._active_interim.id == segment.id
                or self._active_interim.end_time_ms <= segment.end_time_ms
            ):
                # Active interim is fully committed or superseded by this final segment
                self._active_interim = None
                self._last_emitted_interim_text = None
            elif (
                self._config.reconcile_overlapping_interims
                and self._active_interim.start_time_ms < segment.end_time_ms < self._active_interim.end_time_ms
            ):
                # Active interim extends beyond this final segment: trim start_time_ms
                self._active_interim = self._active_interim.model_copy(
                    update={"start_time_ms": segment.end_time_ms}
                )

        # Insert into chronological order
        if self._config.auto_sort_finals:
            self._insert_sorted(segment)
        else:
            self._final_segments.append(segment)

        return segment

    def reconcile_interim_segment(self, segment: TranscriptSegment) -> Optional[TranscriptSegment]:
        """Reconcile an incoming interim speculative hypothesis.

        Returns:
            The reconciled TranscriptSegment, or None if stale, repeated, or suppressed.
        """
        if segment.is_final:
            raise InvalidEventError("Cannot reconcile segment with is_final=True as interim hypothesis.")

        norm_text = segment.text.strip()

        # 1. Suppress stale interims (speech window already finalized)
        if self._config.suppress_stale_interims and self._final_segments:
            latest_final_end = self.latest_final_end_time_ms
            if segment.end_time_ms <= latest_final_end:
                self._metrics.stale_interims_count += 1
                self._metrics.duplicates_suppressed += 1
                logger.debug(
                    "Dropped stale interim segment (end: %dms <= finalized: %dms): '%s'",
                    segment.end_time_ms,
                    latest_final_end,
                    norm_text,
                )
                return None

        # 2. Suppress consecutive repeated identical interim text
        if self._config.suppress_repeated_interims:
            if self._last_emitted_interim_text == norm_text:
                self._metrics.repeated_interims_count += 1
                self._metrics.duplicates_suppressed += 1
                logger.debug("Suppressed repeated interim hypothesis: '%s'", norm_text)
                return None

        # 3. Reconcile overlapping interim boundaries if interim starts before committed speech ends
        if (
            self._config.reconcile_overlapping_interims
            and self._final_segments
            and segment.start_time_ms < self.latest_final_end_time_ms
        ):
            trimmed_start = self.latest_final_end_time_ms
            if trimmed_start < segment.end_time_ms:
                segment = segment.model_copy(update={"start_time_ms": trimmed_start})

        # Update active interim state
        self._active_interim = segment
        self._last_emitted_interim_text = norm_text
        return segment

    def _handle_speech_ended(self, event: TranscriptEvent) -> TranscriptEvent:
        """Handle SPEECH_ENDED boundary and optional interim promotion."""
        if self._config.promote_interim_on_speech_ended and self._active_interim is not None:
            # Promote active interim into committed final segment
            promoted_segment = self._active_interim.model_copy(update={"is_final": True})
            self._metrics.interims_promoted += 1
            logger.info("Promoting unfinalized interim segment '%s' to final on SPEECH_ENDED", promoted_segment.id)
            self.reconcile_final_segment(promoted_segment)

        self._active_interim = None
        self._last_emitted_interim_text = None
        return event

    def _insert_sorted(self, segment: TranscriptSegment) -> None:
        """Insert segment into _final_segments maintaining strict chronological order."""
        # Multi-key sorting: (start_time_ms, end_time_ms, id)
        sort_keys = [(s.start_time_ms, s.end_time_ms, s.id) for s in self._final_segments]
        target_key = (segment.start_time_ms, segment.end_time_ms, segment.id)
        insert_idx = bisect.bisect_left(sort_keys, target_key)
        self._final_segments.insert(insert_idx, segment)

    # --------------------------------------------------------------------------
    # Downstream Text Projections
    # --------------------------------------------------------------------------

    def get_final_text(self) -> str:
        """Return clean concatenated text of all committed final segments in speech order."""
        return " ".join(s.text.strip() for s in self._final_segments if s.text.strip())

    def get_interim_text(self) -> str:
        """Return text of current speculative interim hypothesis, or empty string."""
        if self._active_interim and self._active_interim.text:
            return self._active_interim.text.strip()
        return ""

    def get_full_text(self) -> str:
        """Return combined transcript text (committed final + active interim)."""
        final_part = self.get_final_text()
        interim_part = self.get_interim_text()
        if final_part and interim_part:
            return f"{final_part} {interim_part}"
        elif final_part:
            return final_part
        return interim_part

    def reset(self) -> None:
        """Reset reconciler state, clearing history, interims, and deduplication caches."""
        self._final_segments.clear()
        self._final_segment_ids.clear()
        self._committed_content_keys.clear()
        self._seen_event_ids.clear()
        self._active_interim = None
        self._last_emitted_interim_text = None
        self._metrics = ReconciliationMetrics()

