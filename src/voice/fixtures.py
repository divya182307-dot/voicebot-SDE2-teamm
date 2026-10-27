"""Standardized transcript fixtures and event stream generators for testing.

These fixtures provide canonical scenarios for unit testing, integration testing,
UI simulation, and agent orchestrator evaluation across subteams.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional
import uuid

from src.voice.schemas import (
    TranscriptError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
    WordTiming,
)

REFERENCE_FIXTURE_TIME: datetime = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def make_segment(
    text: str,
    start_time_ms: int,
    end_time_ms: int,
    is_final: bool = False,
    confidence: float = 0.95,
    segment_id: Optional[str] = None,
    language: str = "en-US",
    words: Optional[List[WordTiming]] = None,
) -> TranscriptSegment:
    """Helper to quickly construct a valid TranscriptSegment."""
    return TranscriptSegment(
        id=segment_id or str(uuid.uuid4()),
        start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
        text=text,
        confidence=confidence,
        is_final=is_final,
        language=language,
        words=words,
    )


def make_event(
    event_type: TranscriptEventType,
    session_id: str = "test-session",
    segment: Optional[TranscriptSegment] = None,
    error: Optional[TranscriptError] = None,
    sequence_number: Optional[int] = None,
    timestamp_offset_ms: int = 0,
    event_id: Optional[str] = None,
) -> TranscriptEvent:
    """Helper to quickly construct a valid TranscriptEvent."""
    return TranscriptEvent(
        event_id=event_id or str(uuid.uuid4()),
        session_id=session_id,
        event_type=event_type,
        timestamp=REFERENCE_FIXTURE_TIME + timedelta(milliseconds=timestamp_offset_ms),
        segment=segment,
        error=error,
        sequence_number=sequence_number,
    )


def single_utterance_events(session_id: str = "fixture-session-1") -> List[TranscriptEvent]:
    """Generate a canonical single-turn speech event stream.

    Sequence:
    1. SPEECH_STARTED
    2. INTERIM_TRANSCRIPT ('Why')
    3. INTERIM_TRANSCRIPT ('Why is')
    4. INTERIM_TRANSCRIPT ('Why is this')
    5. FINAL_TRANSCRIPT ('Why is this application failing?', with WordTimings)
    6. SPEECH_ENDED
    """
    seg_id = "seg-fixed-001"
    words = [
        WordTiming(word="Why", start_time_ms=100, end_time_ms=300, confidence=0.99),
        WordTiming(word="is", start_time_ms=310, end_time_ms=450, confidence=0.98),
        WordTiming(word="this", start_time_ms=460, end_time_ms=700, confidence=0.97),
        WordTiming(word="application", start_time_ms=710, end_time_ms=1300, confidence=0.98),
        WordTiming(word="failing", start_time_ms=1310, end_time_ms=1800, confidence=0.96),
    ]

    return [
        make_event(
            event_type=TranscriptEventType.SPEECH_STARTED,
            session_id=session_id,
            sequence_number=1,
            timestamp_offset_ms=0,
            event_id="evt-001",
        ),
        make_event(
            event_type=TranscriptEventType.INTERIM_TRANSCRIPT,
            session_id=session_id,
            segment=make_segment("Why", 100, 300, is_final=False, confidence=0.85, segment_id=seg_id),
            sequence_number=2,
            timestamp_offset_ms=300,
            event_id="evt-002",
        ),
        make_event(
            event_type=TranscriptEventType.INTERIM_TRANSCRIPT,
            session_id=session_id,
            segment=make_segment("Why is", 100, 450, is_final=False, confidence=0.90, segment_id=seg_id),
            sequence_number=3,
            timestamp_offset_ms=450,
            event_id="evt-003",
        ),
        make_event(
            event_type=TranscriptEventType.INTERIM_TRANSCRIPT,
            session_id=session_id,
            segment=make_segment("Why is this", 100, 700, is_final=False, confidence=0.92, segment_id=seg_id),
            sequence_number=4,
            timestamp_offset_ms=700,
            event_id="evt-004",
        ),
        make_event(
            event_type=TranscriptEventType.FINAL_TRANSCRIPT,
            session_id=session_id,
            segment=make_segment(
                "Why is this application failing?",
                100,
                1800,
                is_final=True,
                confidence=0.98,
                segment_id=seg_id,
                words=words,
            ),
            sequence_number=5,
            timestamp_offset_ms=1800,
            event_id="evt-005",
        ),
        make_event(
            event_type=TranscriptEventType.SPEECH_ENDED,
            session_id=session_id,
            sequence_number=6,
            timestamp_offset_ms=1850,
            event_id="evt-006",
        ),
    ]


def multi_utterance_events(session_id: str = "fixture-session-2") -> List[TranscriptEvent]:
    """Generate a sequence of two consecutive utterances representing a multi-clause question.

    Turn 1: "What is quicksort?"
    Turn 2: "What is its worst case complexity?"
    """
    events: List[TranscriptEvent] = []

    # Turn 1
    events.append(make_event(TranscriptEventType.SPEECH_STARTED, session_id, sequence_number=1, timestamp_offset_ms=0))
    events.append(
        make_event(
            TranscriptEventType.INTERIM_TRANSCRIPT,
            session_id,
            segment=make_segment("What", 0, 200, is_final=False, segment_id="seg-1"),
            sequence_number=2,
            timestamp_offset_ms=200,
        )
    )
    events.append(
        make_event(
            TranscriptEventType.FINAL_TRANSCRIPT,
            session_id,
            segment=make_segment(
                "What is quicksort?",
                0,
                800,
                is_final=True,
                confidence=0.99,
                segment_id="seg-1",
                words=[
                    WordTiming(word="What", start_time_ms=0, end_time_ms=200, confidence=0.99),
                    WordTiming(word="is", start_time_ms=210, end_time_ms=350, confidence=0.99),
                    WordTiming(word="quicksort", start_time_ms=360, end_time_ms=800, confidence=0.98),
                ],
            ),
            sequence_number=3,
            timestamp_offset_ms=800,
        )
    )
    events.append(make_event(TranscriptEventType.SPEECH_ENDED, session_id, sequence_number=4, timestamp_offset_ms=850))

    # Turn 2
    events.append(make_event(TranscriptEventType.SPEECH_STARTED, session_id, sequence_number=5, timestamp_offset_ms=1200))
    events.append(
        make_event(
            TranscriptEventType.INTERIM_TRANSCRIPT,
            session_id,
            segment=make_segment("What is its", 1200, 1600, is_final=False, segment_id="seg-2"),
            sequence_number=6,
            timestamp_offset_ms=1600,
        )
    )
    events.append(
        make_event(
            TranscriptEventType.FINAL_TRANSCRIPT,
            session_id,
            segment=make_segment(
                "What is its worst case complexity?",
                1200,
                2400,
                is_final=True,
                confidence=0.97,
                segment_id="seg-2",
                words=[
                    WordTiming(word="What", start_time_ms=1200, end_time_ms=1350, confidence=0.98),
                    WordTiming(word="is", start_time_ms=1360, end_time_ms=1450, confidence=0.98),
                    WordTiming(word="its", start_time_ms=1460, end_time_ms=1600, confidence=0.97),
                    WordTiming(word="worst", start_time_ms=1610, end_time_ms=1850, confidence=0.98),
                    WordTiming(word="case", start_time_ms=1860, end_time_ms=2050, confidence=0.96),
                    WordTiming(word="complexity", start_time_ms=2060, end_time_ms=2400, confidence=0.97),
                ],
            ),
            sequence_number=7,
            timestamp_offset_ms=2400,
        )
    )
    events.append(make_event(TranscriptEventType.SPEECH_ENDED, session_id, sequence_number=8, timestamp_offset_ms=2450))

    return events


def out_of_order_final_events(session_id: str = "fixture-session-ooo") -> List[TranscriptEvent]:
    """Generate final events that arrive out-of-order due to simulated network jitter.

    Arrival sequence:
    1. Second utterance (start_time_ms = 2000, end_time_ms = 3500)
    2. First utterance (start_time_ms = 0, end_time_ms = 1500)
    """
    first_segment = make_segment(
        text="Introduction to data structures.",
        start_time_ms=0,
        end_time_ms=1500,
        is_final=True,
        confidence=0.98,
        segment_id="seg-part-1",
    )
    second_segment = make_segment(
        text="Specifically binary trees and heaps.",
        start_time_ms=2000,
        end_time_ms=3500,
        is_final=True,
        confidence=0.96,
        segment_id="seg-part-2",
    )

    # Deliver second segment first!
    return [
        make_event(
            event_type=TranscriptEventType.FINAL_TRANSCRIPT,
            session_id=session_id,
            segment=second_segment,
            sequence_number=1,
            timestamp_offset_ms=3500,
        ),
        make_event(
            event_type=TranscriptEventType.FINAL_TRANSCRIPT,
            session_id=session_id,
            segment=first_segment,
            sequence_number=2,
            timestamp_offset_ms=3600,
        ),
    ]


def duplicate_final_events(session_id: str = "fixture-session-dup") -> List[TranscriptEvent]:
    """Generate identical duplicate final events to verify deduplication behavior."""
    seg = make_segment(
        text="Duplicate payload test phrase.",
        start_time_ms=100,
        end_time_ms=1000,
        is_final=True,
        segment_id="seg-dup-unique-id",
    )
    return [
        make_event(TranscriptEventType.FINAL_TRANSCRIPT, session_id, segment=seg, sequence_number=1),
        make_event(TranscriptEventType.FINAL_TRANSCRIPT, session_id, segment=seg, sequence_number=2),
    ]


def error_event_stream(session_id: str = "fixture-session-err") -> List[TranscriptEvent]:
    """Generate an event stream with speech started followed by a network failure error."""
    return [
        make_event(TranscriptEventType.SPEECH_STARTED, session_id, sequence_number=1),
        make_event(
            TranscriptEventType.ERROR,
            session_id,
            error=TranscriptError(
                code="WEBSOCKET_CONNECTION_RESET",
                message="Underlying WebSocket connection was reset by peer.",
                details={"socket_fd": 42},
            ),
            sequence_number=2,
        ),
    ]
