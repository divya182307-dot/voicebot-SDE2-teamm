"""Speech Events and Event Processing Pipeline for SDE Team 2, Week 3 (Days 15-16).

This module defines the canonical typed speech event contracts carrying session and correlation IDs:
- EventType: Enumeration of emitted audio event classifications.
- AudioEvent: Base immutable dataclass for all audio/speech events.
- SpeechStartedEvent: Marks confirmed human speech onset with correlation ID.
- AudioFrameEvent: Carries normalized audio frames with quality metrics and tracing IDs.
- SpeechEndedEvent: Marks end of utterance with duration and frame metrics.
- EventStatistics: Telemetry snapshot of event emissions and speech turns.
- SpeechEventProcessor: Stateful event dispatcher managing pre-roll lookback buffering,
  VAD debouncing, session/correlation ID traceability, and safe utterance termination.
"""

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Iterable, Iterator, List, Optional
import uuid

from voicebot.normalizer import AudioNormalizer, AudioQualityMetrics
from voicebot.schemas import AudioChunk, AudioError
from voicebot.vad import VADResult, VoiceActivityDetector


class EventType(str, Enum):
    """Classification of events emitted across the audio-transcription pipeline."""

    SPEECH_STARTED = "speech_started"
    AUDIO_FRAME = "audio_frame"
    SPEECH_ENDED = "speech_ended"


@dataclass(frozen=True)
class AudioEvent:
    """Base immutable dataclass for all audio pipeline events.

    Fields:
        event_id: Globally unique identifier for this event instance.
        event_type: Classification of the event.
        session_id: Top-level conversation session ID from the lifecycle controller.
        correlation_id: Unique utterance-level ID correlating a speech turn end-to-end.
        timestamp: Monotonic audio/wall-clock timestamp of event emission.
        sequence_number: Monotonically increasing counter ensuring total event ordering.
        metadata: Optional diagnostic or operational attributes.
    """

    event_id: str
    event_type: EventType
    session_id: str
    correlation_id: str
    timestamp: float
    sequence_number: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_id or not isinstance(self.event_id, str):
            raise AudioError("event_id must be a non-empty string.")
        if not isinstance(self.event_type, EventType):
            raise AudioError("event_type must be an EventType enum value.")
        if not self.session_id or not isinstance(self.session_id, str):
            raise AudioError("session_id must be a non-empty string.")
        if not self.correlation_id or not isinstance(self.correlation_id, str):
            raise AudioError("correlation_id must be a non-empty string.")
        if not isinstance(self.timestamp, (int, float)) or self.timestamp < 0.0:
            raise AudioError("timestamp must be a non-negative number.")
        if not isinstance(self.sequence_number, int) or self.sequence_number < 0:
            raise AudioError("sequence_number must be a non-negative integer.")


@dataclass(frozen=True)
class SpeechStartedEvent(AudioEvent):
    """Emitted upon confirmed human speech onset after VAD debouncing.

    Fields:
        onset_timestamp: Precise timestamp of the initial speech frame (including pre-roll).
        initial_sequence_id: Sequence ID of the first audio chunk belonging to this utterance.
    """

    onset_timestamp: float = 0.0
    initial_sequence_id: int = 0


@dataclass(frozen=True)
class AudioFrameEvent(AudioEvent):
    """Carries a single normalized audio chunk during active speech.

    Fields:
        chunk: Normalized AudioChunk ready for downstream speech recognition.
        rms_energy: Normalized RMS energy of the audio chunk [0.0, 1.0].
        peak_amplitude: Normalized peak sample amplitude [0.0, 1.0].
        is_speech: Speech status confirmed by VAD.
        chunk_sequence_id: Raw sequence ID of the embedded AudioChunk.
    """

    chunk: Optional[AudioChunk] = None
    rms_energy: float = 0.0
    peak_amplitude: float = 0.0
    is_speech: bool = True
    chunk_sequence_id: int = 0


@dataclass(frozen=True)
class SpeechEndedEvent(AudioEvent):
    """Emitted when speech ceases (energy drops below threshold after hangover).

    Fields:
        offset_timestamp: Timestamp when speech ceased.
        total_speech_duration_ms: Total duration of active speech in milliseconds.
        total_frames: Total number of AudioFrameEvents emitted for this utterance.
    """

    offset_timestamp: float = 0.0
    total_speech_duration_ms: float = 0.0
    total_frames: int = 0


@dataclass(frozen=True)
class EventStatistics:
    """Telemetry snapshot of events emitted and turns processed.

    Fields:
        total_events_emitted: Cumulative count of all events dispatched.
        speech_started_count: Total speech onset events emitted.
        audio_frame_count: Total audio frame events emitted.
        speech_ended_count: Total speech completion events emitted.
        total_speech_turns: Cumulative number of complete speech utterances.
        active_correlation_id: Correlation ID of the turn currently in progress, or None.
        is_in_speech: True if the processor is currently in an active speech turn.
    """

    total_events_emitted: int
    speech_started_count: int
    audio_frame_count: int
    speech_ended_count: int
    total_speech_turns: int
    active_correlation_id: Optional[str]
    is_in_speech: bool


class SpeechEventProcessor:
    """Stateful event processor bridging audio capture to speech events.

    Guarantees:
        - Lossless Speech Onset: Uses a pre-roll lookback buffer to preserve the first 100ms
          of speech captured during VAD debouncing, preventing syllable clipping.
        - Strict Monotonic Ordering: Emits SpeechStartedEvent -> AudioFrameEvent(s) -> SpeechEndedEvent.
        - Tracing Integrity: Reuses session_id and mints a unique correlation_id per speech turn.
        - Format & Normalization: Automatically applies AudioNormalizer to output frames if provided.
        - Safe Flush: Cleanly terminates open speech turns on stream stop or cancellation.
    """

    def __init__(
        self,
        vad: VoiceActivityDetector,
        normalizer: Optional[AudioNormalizer] = None,
        session_id: Optional[str] = None,
        pre_roll_chunks: int = 8,
    ):
        """Initialize the SpeechEventProcessor.

        Args:
            vad (VoiceActivityDetector): Configured VAD instance for energy and debouncing.
            normalizer (AudioNormalizer, optional): Normalizer to condition PCM audio frames.
            session_id (str, optional): Conversation session ID (defaults to new UUID hex).
            pre_roll_chunks (int): Number of pre-roll chunks to retain for onset recovery (default: 8).

        Raises:
            AudioError: If vad is invalid or pre_roll_chunks <= 0.
        """
        if not isinstance(vad, VoiceActivityDetector):
            raise AudioError("vad must be an instance of VoiceActivityDetector.")
        if normalizer is not None and not isinstance(normalizer, AudioNormalizer):
            raise AudioError("normalizer must be an instance of AudioNormalizer.")
        if isinstance(pre_roll_chunks, bool) or not isinstance(pre_roll_chunks, int) or pre_roll_chunks <= 0:
            raise AudioError("pre_roll_chunks must be a positive integer.")

        self._vad = vad
        self._normalizer = normalizer or AudioNormalizer()
        self._session_id = str(session_id) if session_id else uuid.uuid4().hex
        self._pre_roll_capacity = pre_roll_chunks
        self._pre_roll_buffer: deque[AudioChunk] = deque(maxlen=pre_roll_chunks)

        self._sequence_number: int = 0
        self._is_in_speech: bool = False
        self._active_correlation_id: Optional[str] = None

        # Turn telemetry
        self._current_turn_frames: int = 0
        self._current_turn_onset_timestamp: float = 0.0
        self._current_turn_duration_ms: float = 0.0

        # Cumulative counters
        self._total_events_emitted: int = 0
        self._speech_started_count: int = 0
        self._audio_frame_count: int = 0
        self._speech_ended_count: int = 0
        self._total_speech_turns: int = 0

    @property
    def session_id(self) -> str:
        """Return the active session identifier."""
        return self._session_id

    @session_id.setter
    def session_id(self, value: str) -> None:
        """Update the active session identifier."""
        if not value or not isinstance(value, str):
            raise AudioError("session_id must be a non-empty string.")
        self._session_id = value

    @property
    def active_correlation_id(self) -> Optional[str]:
        """Return the correlation ID of the current speech turn, or None if idle."""
        return self._active_correlation_id

    @property
    def is_in_speech(self) -> bool:
        """Return True if an utterance is actively in progress."""
        return self._is_in_speech

    @property
    def statistics(self) -> EventStatistics:
        """Return a snapshot of event processor telemetry."""
        return EventStatistics(
            total_events_emitted=self._total_events_emitted,
            speech_started_count=self._speech_started_count,
            audio_frame_count=self._audio_frame_count,
            speech_ended_count=self._speech_ended_count,
            total_speech_turns=self._total_speech_turns,
            active_correlation_id=self._active_correlation_id,
            is_in_speech=self._is_in_speech,
        )

    def _next_sequence_number(self) -> int:
        """Increment and return the monotonic sequence number."""
        seq = self._sequence_number
        self._sequence_number += 1
        return seq

    def _create_audio_frame_event(
        self,
        chunk: AudioChunk,
        vad_result: Optional[VADResult] = None,
    ) -> AudioFrameEvent:
        """Construct a normalized AudioFrameEvent for an active speech chunk."""
        normalized_chunk = self._normalizer.normalize_chunk(chunk)
        metrics: AudioQualityMetrics = self._normalizer.analyze_quality(normalized_chunk)
        rms = metrics.rms_energy

        seq = self._next_sequence_number()
        self._total_events_emitted += 1
        self._audio_frame_count += 1
        self._current_turn_frames += 1
        self._current_turn_duration_ms += chunk.duration * 1000.0

        return AudioFrameEvent(
            event_id=uuid.uuid4().hex,
            event_type=EventType.AUDIO_FRAME,
            session_id=self._session_id,
            correlation_id=self._active_correlation_id or "unknown",
            timestamp=chunk.timestamp,
            sequence_number=seq,
            chunk=normalized_chunk,
            rms_energy=rms,
            peak_amplitude=metrics.peak_amplitude,
            is_speech=True,
            chunk_sequence_id=chunk.sequence_id,
        )

    def process_chunk(self, chunk: AudioChunk) -> list[AudioEvent]:
        """Process an incoming AudioChunk and emit appropriate speech events.

        Args:
            chunk (AudioChunk): Audio chunk to process.

        Returns:
            list[AudioEvent]: Ordered list of events generated by this chunk (may be empty).
        """
        if not isinstance(chunk, AudioChunk):
            raise AudioError("chunk must be an instance of AudioChunk.")

        vad_result: VADResult = self._vad.process_chunk(chunk)
        events: list[AudioEvent] = []

        if vad_result.is_speech:
            if not self._is_in_speech:
                # -------------------------------------------------------------
                # Speech Onset Transition (Silence -> Speech)
                # -------------------------------------------------------------
                self._is_in_speech = True
                self._active_correlation_id = uuid.uuid4().hex
                self._total_speech_turns += 1
                self._current_turn_frames = 0
                self._current_turn_duration_ms = 0.0

                # Determine onset timestamp and starting chunk ID from pre-roll
                if self._pre_roll_buffer:
                    onset_ts = self._pre_roll_buffer[0].timestamp
                    initial_seq = self._pre_roll_buffer[0].sequence_id
                else:
                    onset_ts = chunk.timestamp
                    initial_seq = chunk.sequence_id

                self._current_turn_onset_timestamp = onset_ts

                # 1. Emit SpeechStartedEvent first
                start_seq = self._next_sequence_number()
                self._total_events_emitted += 1
                self._speech_started_count += 1

                start_event = SpeechStartedEvent(
                    event_id=uuid.uuid4().hex,
                    event_type=EventType.SPEECH_STARTED,
                    session_id=self._session_id,
                    correlation_id=self._active_correlation_id,
                    timestamp=onset_ts,
                    sequence_number=start_seq,
                    onset_timestamp=onset_ts,
                    initial_sequence_id=initial_seq,
                )
                events.append(start_event)

                # 2. Forward all retained pre-roll frames in order (lossless onset)
                while self._pre_roll_buffer:
                    pre_chunk = self._pre_roll_buffer.popleft()
                    frame_event = self._create_audio_frame_event(pre_chunk)
                    events.append(frame_event)

                # 3. Emit current chunk
                current_frame = self._create_audio_frame_event(chunk, vad_result)
                events.append(current_frame)
            else:
                # -------------------------------------------------------------
                # Continuing Speech
                # -------------------------------------------------------------
                current_frame = self._create_audio_frame_event(chunk, vad_result)
                events.append(current_frame)
        else:
            if self._is_in_speech:
                # -------------------------------------------------------------
                # Speech Cessation Transition (Speech -> Silence)
                # -------------------------------------------------------------
                self._is_in_speech = False
                end_seq = self._next_sequence_number()
                self._total_events_emitted += 1
                self._speech_ended_count += 1

                end_event = SpeechEndedEvent(
                    event_id=uuid.uuid4().hex,
                    event_type=EventType.SPEECH_ENDED,
                    session_id=self._session_id,
                    correlation_id=self._active_correlation_id or "unknown",
                    timestamp=chunk.timestamp,
                    sequence_number=end_seq,
                    offset_timestamp=chunk.timestamp,
                    total_speech_duration_ms=round(self._current_turn_duration_ms, 2),
                    total_frames=self._current_turn_frames,
                )
                events.append(end_event)
                self._active_correlation_id = None
                self._pre_roll_buffer.clear()
            else:
                # -------------------------------------------------------------
                # Silence / Non-Speech
                # -------------------------------------------------------------
                if vad_result.energy_score >= self._vad.energy_threshold:
                    # Candidate speech frame accumulating towards debounce threshold
                    self._pre_roll_buffer.append(chunk)
                else:
                    # Energy below threshold; reset debounce candidate buffer
                    self._pre_roll_buffer.clear()

        return events

    def process_stream(self, chunks: Iterable[AudioChunk]) -> Iterator[AudioEvent]:
        """Process an iterable stream of AudioChunks and yield events sequentially.

        Args:
            chunks (Iterable[AudioChunk]): Stream of audio chunks.

        Yields:
            AudioEvent: Individual speech and frame events in strict monotonic order.
        """
        for chunk in chunks:
            for event in self.process_chunk(chunk):
                yield event
        for event in self.flush():
            yield event

    def flush(self) -> list[AudioEvent]:
        """Flush the event processor, cleanly terminating any active speech turn.

        Guarantees:
            - If stream terminates during active speech, emits closing SpeechEndedEvent.
            - Clears lookback buffers and resets turn state.

        Returns:
            list[AudioEvent]: Any terminal events emitted during flush.
        """
        events: list[AudioEvent] = []
        if self._is_in_speech:
            self._is_in_speech = False
            end_seq = self._next_sequence_number()
            self._total_events_emitted += 1
            self._speech_ended_count += 1

            offset_ts = (
                self._current_turn_onset_timestamp + (self._current_turn_duration_ms / 1000.0)
            )

            end_event = SpeechEndedEvent(
                event_id=uuid.uuid4().hex,
                event_type=EventType.SPEECH_ENDED,
                session_id=self._session_id,
                correlation_id=self._active_correlation_id or "unknown",
                timestamp=offset_ts,
                sequence_number=end_seq,
                offset_timestamp=offset_ts,
                total_speech_duration_ms=round(self._current_turn_duration_ms, 2),
                total_frames=self._current_turn_frames,
            )
            events.append(end_event)
            self._active_correlation_id = None

        self._pre_roll_buffer.clear()
        self._vad.reset()
        return events

    def reset(self) -> None:
        """Reset internal processor state, sequence numbers, and VAD debouncer."""
        self.flush()
        self._vad.reset()
        self._sequence_number = 0
        self._total_events_emitted = 0
        self._speech_started_count = 0
        self._audio_frame_count = 0
        self._speech_ended_count = 0
        self._total_speech_turns = 0
