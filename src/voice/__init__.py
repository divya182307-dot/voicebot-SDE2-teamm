"""Voice and Speech-to-Text package."""

from src.voice.accumulator import (
    AccumulatedTranscript,
    AccumulatorConfig,
    SegmentAccumulator,
)
from src.voice.adapter import (
    AudioConfig,
    AudioEncoding,
    BaseTranscriber,
    EventListener,
    TranscriberConfig,
    TranscriberState,
)
from src.voice.exceptions import (
    AccumulatorError,
    DuplicateSegmentError,
    InvalidConfidenceError,
    InvalidEventError,
    InvalidTimeRangeError,
    SchemaValidationError,
    SessionMismatchError,
    TranscriberAudioError,
    TranscriberConnectionError,
    TranscriberError,
    TranscriberStateError,
    VoiceError,
)
from src.voice.fake_transcriber import (
    FakeTranscriber,
    FakeUtterance,
    generate_deterministic_words,
    generate_progressive_interims,
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

__all__ = [
    # Domain Exceptions
    "VoiceError",
    "SchemaValidationError",
    "InvalidTimeRangeError",
    "InvalidConfidenceError",
    "TranscriberError",
    "TranscriberConnectionError",
    "TranscriberStateError",
    "TranscriberAudioError",
    "AccumulatorError",
    "SessionMismatchError",
    "InvalidEventError",
    "DuplicateSegmentError",
    # Data Contracts & Schemas
    "WordTiming",
    "TranscriptSegment",
    "TranscriptError",
    "TranscriptEventType",
    "TranscriptEvent",
    # Adapter Contracts & Audio Configuration
    "AudioEncoding",
    "AudioConfig",
    "TranscriberState",
    "TranscriberConfig",
    "BaseTranscriber",
    "EventListener",
    # Deterministic Fake Transcriber
    "FakeUtterance",
    "FakeTranscriber",
    "generate_deterministic_words",
    "generate_progressive_interims",
    # Ordered Segment Accumulator
    "AccumulatorConfig",
    "AccumulatedTranscript",
    "SegmentAccumulator",
    # Test Fixtures & Generators
    "make_segment",
    "make_event",
    "single_utterance_events",
    "multi_utterance_events",
    "out_of_order_final_events",
    "duplicate_final_events",
    "error_event_stream",
]
