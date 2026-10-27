"""Comprehensive unit tests for SegmentAccumulator, ordering, interim/final handling, and fixtures."""

import pytest

from src.voice.accumulator import (
    AccumulatedTranscript,
    AccumulatorConfig,
    SegmentAccumulator,
)
from src.voice.exceptions import (
    DuplicateSegmentError,
    InvalidEventError,
    SessionMismatchError,
)
from src.voice.fixtures import (
    duplicate_final_events,
    error_event_stream,
    make_event,
    make_segment,
    multi_utterance_events,
    out_of_order_final_events,
    single_utterance_events,
)
from src.voice.schemas import (
    TranscriptError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
    WordTiming,
)


class TestAccumulatorOrdering:
    """Tests verifying chronological ordering, sorting, and out-of-order event resilience."""

    def test_out_of_order_events_are_chronologically_sorted(self):
        """When segments arrive out-of-order, accumulator automatically sorts them by start_time_ms."""
        acc = SegmentAccumulator(session_id="order-session")

        # Create later segment (start: 2000, end: 3500)
        seg2 = make_segment("Second clause spoken.", 2000, 3500, is_final=True, segment_id="seg-2")
        # Create earlier segment (start: 0, end: 1500)
        seg1 = make_segment("First clause spoken.", 0, 1500, is_final=True, segment_id="seg-1")

        # Ingest seg2 FIRST
        acc.add_event(make_event(TranscriptEventType.FINAL_TRANSCRIPT, "order-session", segment=seg2))
        assert len(acc.final_segments) == 1
        assert acc.final_segments[0].text == "Second clause spoken."

        # Ingest seg1 SECOND (out-of-order)
        acc.add_event(make_event(TranscriptEventType.FINAL_TRANSCRIPT, "order-session", segment=seg1))
        assert len(acc.final_segments) == 2

        # Verify strict chronological order
        assert acc.final_segments[0].id == "seg-1"
        assert acc.final_segments[0].start_time_ms == 0
        assert acc.final_segments[1].id == "seg-2"
        assert acc.final_segments[1].start_time_ms == 2000

        # Verify joined text is in natural speech order
        assert acc.get_final_text() == "First clause spoken. Second clause spoken."

    def test_out_of_order_fixture_stream(self, out_of_order_stream):
        """Verify sorting using the standardized out_of_order_stream fixture."""
        acc = SegmentAccumulator()
        acc.add_events(out_of_order_stream)

        assert len(acc.final_segments) == 2
        assert acc.final_segments[0].start_time_ms == 0
        assert acc.final_segments[0].text == "Introduction to data structures."
        assert acc.final_segments[1].start_time_ms == 2000
        assert acc.final_segments[1].text == "Specifically binary trees and heaps."
        assert acc.get_final_text() == "Introduction to data structures. Specifically binary trees and heaps."

    def test_interleaved_chronological_insertion(self):
        """Insert middle segment between two existing segments."""
        acc = SegmentAccumulator()
        s1 = make_segment("Start", 0, 1000, is_final=True, segment_id="s1")
        s3 = make_segment("End", 3000, 4000, is_final=True, segment_id="s3")
        s2 = make_segment("Middle", 1500, 2500, is_final=True, segment_id="s2")

        acc.add_segment(s1)
        acc.add_segment(s3)
        acc.add_segment(s2)  # Inserted in middle

        texts = [s.text for s in acc.final_segments]
        assert texts == ["Start", "Middle", "End"]

    def test_auto_sort_disabled_preserves_arrival_order(self):
        """When auto_sort=False, arrival order is preserved regardless of timestamps."""
        config = AccumulatorConfig(auto_sort=False)
        acc = SegmentAccumulator(config=config)

        s2 = make_segment("Later", 2000, 3000, is_final=True, segment_id="s2")
        s1 = make_segment("Earlier", 0, 1000, is_final=True, segment_id="s1")

        acc.add_segment(s2)
        acc.add_segment(s1)

        assert [s.id for s in acc.final_segments] == ["s2", "s1"]


class TestAccumulatorInterimAndFinalHandling:
    """Tests for progressive interim hypotheses, finalization, and speech turn boundaries."""

    def test_progressive_interim_replacement(self):
        """Interim hypotheses update the speculative text in-place without adding final segments."""
        acc = SegmentAccumulator(session_id="interim-test")
        seg_id = "live-turn-1"

        # 1. Interim 1: "Why"
        acc.add_event(
            make_event(
                TranscriptEventType.INTERIM_TRANSCRIPT,
                "interim-test",
                segment=make_segment("Why", 0, 200, is_final=False, segment_id=seg_id),
            )
        )
        assert acc.active_interim is not None
        assert acc.active_interim.text == "Why"
        assert len(acc.final_segments) == 0
        assert acc.get_final_text() == ""
        assert acc.get_interim_text() == "Why"
        assert acc.get_full_text() == "Why"

        # 2. Interim 2: "Why is"
        acc.add_event(
            make_event(
                TranscriptEventType.INTERIM_TRANSCRIPT,
                "interim-test",
                segment=make_segment("Why is", 0, 400, is_final=False, segment_id=seg_id),
            )
        )
        assert acc.get_interim_text() == "Why is"
        assert acc.get_full_text() == "Why is"
        assert len(acc.final_segments) == 0

        # 3. Final: "Why is this failing?"
        acc.add_event(
            make_event(
                TranscriptEventType.FINAL_TRANSCRIPT,
                "interim-test",
                segment=make_segment("Why is this failing?", 0, 1200, is_final=True, segment_id=seg_id),
            )
        )
        # Active interim should be cleared
        assert acc.active_interim is None
        assert acc.get_interim_text() == ""
        assert len(acc.final_segments) == 1
        assert acc.get_final_text() == "Why is this failing?"
        assert acc.get_full_text() == "Why is this failing?"

    def test_multi_turn_projection_with_active_interim(self):
        """Full text projection joins committed final segments with current in-flight interim."""
        acc = SegmentAccumulator(session_id="multi-turn")

        # Commit Turn 1
        turn1 = make_segment("What is Dijkstra algorithm?", 0, 1000, is_final=True, segment_id="t1")
        acc.add_segment(turn1)

        # Ingest Turn 2 interim
        turn2_interim = make_segment("Can you explain", 1200, 1600, is_final=False, segment_id="t2")
        acc.add_segment(turn2_interim)

        assert acc.get_final_text() == "What is Dijkstra algorithm?"
        assert acc.get_interim_text() == "Can you explain"
        assert acc.get_full_text() == "What is Dijkstra algorithm? Can you explain"

    def test_speech_started_and_speech_ended_lifecycle(self):
        """Speech activity flags and interim clearing on speech ended."""
        acc = SegmentAccumulator(session_id="vad-session")
        assert not acc.speech_active

        # SPEECH_STARTED
        acc.add_event(make_event(TranscriptEventType.SPEECH_STARTED, "vad-session"))
        assert acc.speech_active

        # Interim received
        acc.add_event(
            make_event(
                TranscriptEventType.INTERIM_TRANSCRIPT,
                "vad-session",
                segment=make_segment("Unfinished thought", 0, 500, is_final=False),
            )
        )
        assert acc.active_interim is not None

        # SPEECH_ENDED -> clears active interim by default
        acc.add_event(make_event(TranscriptEventType.SPEECH_ENDED, "vad-session"))
        assert not acc.speech_active
        assert acc.active_interim is None

    def test_preserve_interim_on_speech_ended_configuration(self):
        """When preserve_interim_on_speech_ended=True, interim is retained upon SPEECH_ENDED."""
        config = AccumulatorConfig(preserve_interim_on_speech_ended=True)
        acc = SegmentAccumulator(config=config)

        acc.add_event(make_event(TranscriptEventType.SPEECH_STARTED))
        acc.add_event(
            make_event(
                TranscriptEventType.INTERIM_TRANSCRIPT,
                segment=make_segment("Preserved thought", 0, 500, is_final=False),
            )
        )
        acc.add_event(make_event(TranscriptEventType.SPEECH_ENDED))

        assert not acc.speech_active
        assert acc.active_interim is not None
        assert acc.get_interim_text() == "Preserved thought"


class TestAccumulatorDeduplication:
    """Tests verifying segment ID deduplication behavior."""

    def test_idempotent_duplicate_final_segments_ignored_by_default(self):
        """Duplicate final segments with same ID are ignored idempotently."""
        acc = SegmentAccumulator()
        seg1 = make_segment("First instance.", 0, 500, is_final=True, segment_id="duplicate-id")
        seg2 = make_segment("First instance duplicate.", 0, 500, is_final=True, segment_id="duplicate-id")

        acc.add_segment(seg1)
        assert len(acc.final_segments) == 1

        acc.add_segment(seg2)  # Duplicate ID
        assert len(acc.final_segments) == 1
        assert acc.final_segments[0].text == "First instance."

    def test_duplicate_rejection_when_deduplicate_disabled(self):
        """When deduplicate_by_id=False, duplicate IDs raise DuplicateSegmentError."""
        config = AccumulatorConfig(deduplicate_by_id=False)
        acc = SegmentAccumulator(config=config)

        seg = make_segment("Duplicate check.", 0, 500, is_final=True, segment_id="unique-dup-id")
        acc.add_segment(seg)

        with pytest.raises(DuplicateSegmentError, match="has already been committed"):
            acc.add_segment(seg)


class TestAccumulatorInvalidInputHandling:
    """Tests verifying strict validation and descriptive rejection of invalid inputs."""

    def test_reject_none_event(self):
        acc = SegmentAccumulator()
        with pytest.raises(InvalidEventError, match="Expected TranscriptEvent instance"):
            acc.add_event(None)

    def test_reject_wrong_event_type(self):
        acc = SegmentAccumulator()
        with pytest.raises(InvalidEventError, match="Expected TranscriptEvent instance"):
            acc.add_event({"event_type": "speech_started"})

    def test_reject_none_segment_in_add_segment(self):
        acc = SegmentAccumulator()
        with pytest.raises(InvalidEventError, match="Expected TranscriptSegment instance"):
            acc.add_segment(None)

    def test_reject_mismatched_session_id(self):
        acc = SegmentAccumulator(session_id="expected-session")
        event = make_event(TranscriptEventType.SPEECH_STARTED, session_id="other-session")
        with pytest.raises(SessionMismatchError, match="does not match accumulator session"):
            acc.add_event(event)

    def test_allow_mismatched_session_when_enforce_disabled(self):
        config = AccumulatorConfig(enforce_session_id=False)
        acc = SegmentAccumulator(session_id="session-1", config=config)
        event = make_event(TranscriptEventType.SPEECH_STARTED, session_id="session-2")
        acc.add_event(event)  # Should not raise

    def test_reject_missing_segment_on_interim_event(self):
        acc = SegmentAccumulator()
        # Create event bypassing pydantic check for testing internal accumulator defense
        event = TranscriptEvent.model_construct(
            event_id="e1",
            session_id="s1",
            event_type=TranscriptEventType.INTERIM_TRANSCRIPT,
            segment=None,
        )
        with pytest.raises(InvalidEventError, match="missing required segment payload"):
            acc.add_event(event)

    def test_reject_missing_segment_on_final_event(self):
        acc = SegmentAccumulator()
        event = TranscriptEvent.model_construct(
            event_id="e2",
            session_id="s1",
            event_type=TranscriptEventType.FINAL_TRANSCRIPT,
            segment=None,
        )
        with pytest.raises(InvalidEventError, match="missing required segment payload"):
            acc.add_event(event)

    def test_reject_missing_error_payload_on_error_event(self):
        acc = SegmentAccumulator()
        event = TranscriptEvent.model_construct(
            event_id="e3",
            session_id="s1",
            event_type=TranscriptEventType.ERROR,
            error=None,
        )
        with pytest.raises(InvalidEventError, match="missing required error payload"):
            acc.add_event(event)


class TestAccumulatorAnalyticsAndSnapshot:
    """Tests for duration, word count, confidence metrics, and snapshot export."""

    def test_metrics_calculation(self):
        acc = SegmentAccumulator(session_id="metrics-session")
        assert acc.is_empty
        assert acc.total_duration_ms == 0
        assert acc.average_confidence == 0.0
        assert acc.word_count == 0

        # Segment 1: duration = 1000ms (0 to 1000), 3 words, confidence = 0.90
        words1 = [
            WordTiming(word="First", start_time_ms=0, end_time_ms=300, confidence=0.90),
            WordTiming(word="test", start_time_ms=310, end_time_ms=600, confidence=0.90),
            WordTiming(word="clause", start_time_ms=610, end_time_ms=1000, confidence=0.90),
        ]
        s1 = make_segment("First test clause", 0, 1000, is_final=True, confidence=0.90, words=words1)
        acc.add_segment(s1)

        # Segment 2: duration = 2000ms (1500 to 3500), 2 words, confidence = 0.99
        s2 = make_segment("Second clause", 1500, 3500, is_final=True, confidence=0.99)
        acc.add_segment(s2)

        assert not acc.is_empty
        assert acc.word_count == 5
        # Total span: 3500 - 0 = 3500ms
        assert acc.total_duration_ms == 3500
        # Weighted confidence: (0.90 * 1000 + 0.99 * 2000) / 3000 = (900 + 1980) / 3000 = 2880 / 3000 = 0.960
        assert acc.average_confidence == 0.96
        assert len(acc.all_words) == 3

    def test_snapshot_generation(self):
        acc = SegmentAccumulator(session_id="snapshot-session")
        s = make_segment("Snapshot test phrase.", 100, 1000, is_final=True)
        acc.add_segment(s)

        snapshot = acc.get_snapshot()
        assert isinstance(snapshot, AccumulatedTranscript)
        assert snapshot.session_id == "snapshot-session"
        assert snapshot.final_text == "Snapshot test phrase."
        assert snapshot.word_count == 3
        assert snapshot.total_duration_ms == 900
        assert len(snapshot.final_segments) == 1

    def test_reset_functionality(self):
        acc = SegmentAccumulator(session_id="reset-session")
        acc.add_segment(make_segment("To be cleared", 0, 500, is_final=True))
        acc.add_segment(make_segment("Interim", 600, 800, is_final=False))
        assert not acc.is_empty

        acc.reset()
        assert acc.is_empty
        assert len(acc.final_segments) == 0
        assert acc.active_interim is None
        assert acc.get_final_text() == ""


class TestAccumulatorWithFixtures:
    """Tests executing standardized fixtures with SegmentAccumulator."""

    def test_single_turn_fixture(self, single_turn_stream):
        acc = SegmentAccumulator()
        acc.add_events(single_turn_stream)

        assert len(acc.final_segments) == 1
        assert acc.get_final_text() == "Why is this application failing?"
        assert acc.active_interim is None
        assert not acc.speech_active
        assert len(acc.all_words) == 5

    def test_multi_turn_fixture(self, multi_turn_stream):
        acc = SegmentAccumulator()
        acc.add_events(multi_turn_stream)

        assert len(acc.final_segments) == 2
        assert acc.final_segments[0].text == "What is quicksort?"
        assert acc.final_segments[1].text == "What is its worst case complexity?"
        assert acc.get_final_text() == "What is quicksort? What is its worst case complexity?"
        assert acc.word_count == 9
        assert len(acc.all_words) == 9

    def test_duplicate_events_fixture(self, duplicate_events_stream):
        acc = SegmentAccumulator()
        acc.add_events(duplicate_events_stream)

        # Deduplication should ensure only 1 segment is kept
        assert len(acc.final_segments) == 1
        assert acc.final_segments[0].text == "Duplicate payload test phrase."

    def test_error_stream_fixture(self, error_stream):
        acc = SegmentAccumulator()
        acc.add_events(error_stream)

        assert len(acc.errors) == 1
        assert acc.errors[0].code == "WEBSOCKET_CONNECTION_RESET"
        assert "reset by peer" in acc.errors[0].message
