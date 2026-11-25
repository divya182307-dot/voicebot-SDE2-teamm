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
    AudioPreprocessingError,
    DuplicateSegmentError,
    InvalidConfidenceError,
    InvalidEventError,
    InvalidTimeRangeError,
    OrchestratorError,
    OrchestratorStateError,
    RetryExhaustedError,
    SchemaValidationError,
    SessionMismatchError,
    TranscriberAudioError,
    TranscriberAuthenticationError,
    TranscriberConnectionError,
    TranscriberError,
    TranscriberRateLimitError,
    TranscriberServiceUnavailableError,
    TranscriberStateError,
    TranscriberTimeoutError,
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
from src.voice.orchestrator import (
    OrchestratorConfig,
    OrchestratorMetrics,
    OrchestratorState,
    TranscriptionOrchestrator,
)
from src.voice.preprocessing import (
    AudioPreprocessor,
    AudioPreprocessorConfig,
    AudioPreprocessorMetrics,
    convert_stereo_to_mono,
    normalize_amplitude_pcm16,
    resample_pcm16,
)
from src.voice.reconciliation import (
    ReconciliationConfig,
    ReconciliationMetrics,
    TranscriptReconciler,
)
from src.voice.resilience import (
    ErrorNormalizer,
    ResilienceMetrics,
    ResilientTranscriberWrapper,
    RetryConfig,
    RetryPolicy,
    TimeoutConfig,
    TimeoutPolicy,
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
    "TranscriberTimeoutError",
    "TranscriberRateLimitError",
    "TranscriberAuthenticationError",
    "TranscriberServiceUnavailableError",
    "TranscriberStateError",
    "TranscriberAudioError",
    "AccumulatorError",
    "SessionMismatchError",
    "InvalidEventError",
    "DuplicateSegmentError",
    "OrchestratorError",
    "OrchestratorStateError",
    "AudioPreprocessingError",
    "RetryExhaustedError",
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
    # Transcription Orchestrator (Days 8-9)
    "OrchestratorState",
    "OrchestratorMetrics",
    "OrchestratorConfig",
    "TranscriptionOrchestrator",
    # Reconciliation & Deduplication (Days 10-11)
    "ReconciliationConfig",
    "ReconciliationMetrics",
    "TranscriptReconciler",
    # Audio Preprocessing (Days 12-13)
    "resample_pcm16",
    "convert_stereo_to_mono",
    "normalize_amplitude_pcm16",
    "AudioPreprocessorConfig",
    "AudioPreprocessorMetrics",
    "AudioPreprocessor",
    # Resilience & Error Normalization (Days 12-13)
    "RetryConfig",
    "TimeoutConfig",
    "ResilienceMetrics",
    "ErrorNormalizer",
    "RetryPolicy",
    "TimeoutPolicy",
    "ResilientTranscriberWrapper",
    # Test Fixtures & Generators
    "make_segment",
    "make_event",
    "single_utterance_events",
    "multi_utterance_events",
    "out_of_order_final_events",
    "duplicate_final_events",
    "error_event_stream",
]
