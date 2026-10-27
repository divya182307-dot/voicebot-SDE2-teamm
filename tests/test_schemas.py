"""Comprehensive unit tests for TranscriptSegment and TranscriptEvent schemas."""

from datetime import datetime, timezone
import json
import pytest
from pydantic import ValidationError

from src.voice.schemas import (
    TranscriptError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
    WordTiming,
)


class TestWordTiming:
    """Tests for WordTiming model."""

    def test_valid_word_timing(self):
        timing = WordTiming(
            word="error",
            start_time_ms=100,
            end_time_ms=350,
            confidence=0.95,
        )
        assert timing.word == "error"
        assert timing.start_time_ms == 100
        assert timing.end_time_ms == 350
        assert timing.confidence == 0.95

    def test_word_timing_invalid_time_range(self):
        with pytest.raises(ValidationError) as exc_info:
            WordTiming(
                word="test",
                start_time_ms=500,
                end_time_ms=400,
                confidence=0.9,
            )
        assert "cannot be less than start_time_ms" in str(exc_info.value)

    def test_word_timing_invalid_confidence(self):
        with pytest.raises(ValidationError):
            WordTiming(word="test", start_time_ms=0, end_time_ms=100, confidence=1.5)

        with pytest.raises(ValidationError):
            WordTiming(word="test", start_time_ms=0, end_time_ms=100, confidence=-0.1)

    def test_word_timing_empty_word(self):
        with pytest.raises(ValidationError):
            WordTiming(word="", start_time_ms=0, end_time_ms=100, confidence=0.8)


class TestTranscriptSegment:
    """Tests for TranscriptSegment model."""

    def test_valid_segment_creation(self):
        segment = TranscriptSegment(
            start_time_ms=0,
            end_time_ms=1250,
            text="Why is this failing?",
            confidence=0.98,
            is_final=True,
            language="en-US",
        )
        assert segment.text == "Why is this failing?"
        assert segment.duration_ms == 1250
        assert segment.confidence == 0.98
        assert segment.is_final is True
        assert segment.language == "en-US"
        assert len(segment.id) > 0

    def test_segment_with_word_timings(self):
        words = [
            WordTiming(word="Why", start_time_ms=0, end_time_ms=200, confidence=0.99),
            WordTiming(word="is", start_time_ms=210, end_time_ms=350, confidence=0.98),
            WordTiming(word="this", start_time_ms=360, end_time_ms=550, confidence=0.97),
            WordTiming(word="failing", start_time_ms=560, end_time_ms=1000, confidence=0.95),
        ]
        segment = TranscriptSegment(
            start_time_ms=0,
            end_time_ms=1000,
            text="Why is this failing",
            confidence=0.97,
            is_final=True,
            words=words,
        )
        assert segment.words is not None
        assert len(segment.words) == 4
        assert segment.words[0].word == "Why"

    def test_reject_negative_start_time(self):
        with pytest.raises(ValidationError) as exc:
            TranscriptSegment(
                start_time_ms=-10,
                end_time_ms=100,
                text="Negative start",
                confidence=0.9,
            )
        assert "greater than or equal to 0" in str(exc.value)

    def test_reject_end_time_before_start_time(self):
        with pytest.raises(ValidationError) as exc:
            TranscriptSegment(
                start_time_ms=1000,
                end_time_ms=500,
                text="Inverted timing",
                confidence=0.9,
            )
        assert "must be greater than or equal to start_time_ms" in str(exc.value)

    def test_reject_invalid_confidence_bounds(self):
        with pytest.raises(ValidationError):
            TranscriptSegment(
                start_time_ms=0,
                end_time_ms=500,
                text="Out of bounds",
                confidence=1.05,
            )

        with pytest.raises(ValidationError):
            TranscriptSegment(
                start_time_ms=0,
                end_time_ms=500,
                text="Out of bounds",
                confidence=-0.01,
            )

    def test_reject_empty_or_whitespace_text(self):
        with pytest.raises(ValidationError) as exc1:
            TranscriptSegment(
                start_time_ms=0,
                end_time_ms=500,
                text="",
                confidence=0.9,
            )
        assert "must contain at least one non-whitespace character" in str(exc1.value)

        with pytest.raises(ValidationError) as exc2:
            TranscriptSegment(
                start_time_ms=0,
                end_time_ms=500,
                text="     ",
                confidence=0.9,
            )
        assert "must contain at least one non-whitespace character" in str(exc2.value)

    def test_reject_invalid_language_code(self):
        with pytest.raises(ValidationError) as exc:
            TranscriptSegment(
                start_time_ms=0,
                end_time_ms=500,
                text="Test",
                confidence=0.9,
                language="INVALID_LANGUAGE_TAG_12345",
            )
        assert "Invalid language code" in str(exc.value)

    def test_reject_extra_fields(self):
        with pytest.raises(ValidationError) as exc:
            TranscriptSegment(
                start_time_ms=0,
                end_time_ms=500,
                text="Test",
                confidence=0.9,
                unknown_extra_field="malicious",  # type: ignore
            )
        assert "extra_forbidden" in str(exc.value) or "Extra inputs are not permitted" in str(exc.value)

    def test_json_roundtrip_serialization(self):
        segment = TranscriptSegment(
            id="seg-1234",
            start_time_ms=50,
            end_time_ms=1500,
            text="Explain this error",
            confidence=0.92,
            is_final=True,
            language="en",
        )
        json_data = segment.model_dump_json()
        restored = TranscriptSegment.model_validate_json(json_data)
        assert segment == restored
        assert restored.duration_ms == 1450


class TestTranscriptEvent:
    """Tests for TranscriptEvent model and validation invariants."""

    def test_valid_speech_started_event(self):
        event = TranscriptEvent(
            session_id="session-001",
            event_type=TranscriptEventType.SPEECH_STARTED,
        )
        assert event.session_id == "session-001"
        assert event.event_type == TranscriptEventType.SPEECH_STARTED
        assert event.segment is None
        assert event.error is None
        assert isinstance(event.timestamp, datetime)

    def test_valid_interim_transcript_event(self):
        segment = TranscriptSegment(
            start_time_ms=0,
            end_time_ms=800,
            text="why is",
            confidence=0.75,
            is_final=False,
        )
        event = TranscriptEvent(
            session_id="session-001",
            event_type=TranscriptEventType.INTERIM_TRANSCRIPT,
            segment=segment,
            sequence_number=1,
        )
        assert event.segment is not None
        assert event.segment.is_final is False
        assert event.sequence_number == 1

    def test_valid_final_transcript_event(self):
        segment = TranscriptSegment(
            start_time_ms=0,
            end_time_ms=1800,
            text="Why is this code failing?",
            confidence=0.96,
            is_final=True,
        )
        event = TranscriptEvent(
            session_id="session-001",
            event_type=TranscriptEventType.FINAL_TRANSCRIPT,
            segment=segment,
            sequence_number=2,
            metadata={"model": "whisper-large-v3"},
        )
        assert event.segment is not None
        assert event.segment.is_final is True
        assert event.metadata == {"model": "whisper-large-v3"}

    def test_valid_speech_ended_event(self):
        event = TranscriptEvent(
            session_id="session-001",
            event_type=TranscriptEventType.SPEECH_ENDED,
            sequence_number=3,
        )
        assert event.event_type == TranscriptEventType.SPEECH_ENDED

    def test_valid_error_event(self):
        error = TranscriptError(
            code="AUDIO_TIMEOUT",
            message="No speech detected within the allowed time frame.",
            details={"timeout_seconds": 10},
        )
        event = TranscriptEvent(
            session_id="session-001",
            event_type=TranscriptEventType.ERROR,
            error=error,
        )
        assert event.error is not None
        assert event.error.code == "AUDIO_TIMEOUT"
        assert event.error.details == {"timeout_seconds": 10}

    def test_reject_interim_event_without_segment(self):
        with pytest.raises(ValidationError) as exc:
            TranscriptEvent(
                session_id="session-001",
                event_type=TranscriptEventType.INTERIM_TRANSCRIPT,
                segment=None,
            )
        assert "requires a non-null 'segment' field" in str(exc.value)

    def test_reject_final_event_without_segment(self):
        with pytest.raises(ValidationError) as exc:
            TranscriptEvent(
                session_id="session-001",
                event_type=TranscriptEventType.FINAL_TRANSCRIPT,
                segment=None,
            )
        assert "requires a non-null 'segment' field" in str(exc.value)

    def test_reject_final_event_with_interim_segment(self):
        segment = TranscriptSegment(
            start_time_ms=0,
            end_time_ms=800,
            text="unfinished thought",
            confidence=0.6,
            is_final=False,  # Mismatch: event is FINAL but segment is NOT final
        )
        with pytest.raises(ValidationError) as exc:
            TranscriptEvent(
                session_id="session-001",
                event_type=TranscriptEventType.FINAL_TRANSCRIPT,
                segment=segment,
            )
        assert "must have segment.is_final=True" in str(exc.value)

    def test_reject_interim_event_with_final_segment(self):
        segment = TranscriptSegment(
            start_time_ms=0,
            end_time_ms=800,
            text="finished thought",
            confidence=0.9,
            is_final=True,  # Mismatch: event is INTERIM but segment is final
        )
        with pytest.raises(ValidationError) as exc:
            TranscriptEvent(
                session_id="session-001",
                event_type=TranscriptEventType.INTERIM_TRANSCRIPT,
                segment=segment,
            )
        assert "must have segment.is_final=False" in str(exc.value)

    def test_reject_error_event_without_error_payload(self):
        with pytest.raises(ValidationError) as exc:
            TranscriptEvent(
                session_id="session-001",
                event_type=TranscriptEventType.ERROR,
                error=None,
            )
        assert "requires a non-null 'error' field" in str(exc.value)

    def test_reject_speech_started_with_error_payload(self):
        error = TranscriptError(code="INVALID_STATE", message="Oops")
        with pytest.raises(ValidationError) as exc:
            TranscriptEvent(
                session_id="session-001",
                event_type=TranscriptEventType.SPEECH_STARTED,
                error=error,
            )
        assert "must not include an 'error' payload" in str(exc.value)

    def test_reject_blank_session_id(self):
        with pytest.raises(ValidationError) as exc:
            TranscriptEvent(
                session_id="   ",
                event_type=TranscriptEventType.SPEECH_STARTED,
            )
        assert "session_id cannot be empty or blank" in str(exc.value)

    def test_event_json_roundtrip(self):
        segment = TranscriptSegment(
            id="seg-999",
            start_time_ms=100,
            end_time_ms=900,
            text="Open project notes",
            confidence=0.94,
            is_final=True,
        )
        event = TranscriptEvent(
            session_id="session-abc-123",
            event_type=TranscriptEventType.FINAL_TRANSCRIPT,
            segment=segment,
            sequence_number=42,
            metadata={"origin": "mic-0"},
        )
        json_str = event.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["event_type"] == "final_transcript"
        assert parsed["segment"]["text"] == "Open project notes"
        assert parsed["sequence_number"] == 42

        restored_event = TranscriptEvent.model_validate_json(json_str)
        assert restored_event.session_id == event.session_id
        assert restored_event.segment.text == segment.text
