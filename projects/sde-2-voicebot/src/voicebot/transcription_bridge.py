"""Transcription Bridge for SDE Team 2, Week 3 (Days 19-20).

This module bridges the Audio & VAD processing pipeline (Workstream W1)
with the team's speech-to-text (STT) transcription and accumulation module (src.voice):
- Ingests typed AudioEvents (SpeechStartedEvent, AudioFrameEvent, SpeechEndedEvent).
- Preserves end-to-end tracing by tracking session_id and correlation_id.
- Safely enriches emitted TranscriptEvents with correlation_id metadata without violating
  frozen dataclass immutability or schema validation rules.
- Detects sequence gaps and missing audio chunks, logging telemetry without synthesizing
  fake audio padding.
- Enforces strict chronological turn finalization upon SpeechEndedEvent.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, AsyncIterable, Iterable, List, Optional, Union

from voicebot.events import (
    AudioEvent,
    AudioFrameEvent,
    EventType,
    SpeechEndedEvent,
    SpeechStartedEvent,
)
from voicebot.schemas import AudioError

# Import teammate Speech-to-Text contracts and adapters
from src.voice.accumulator import SegmentAccumulator
from src.voice.adapter import BaseTranscriber, TranscriberState
from src.voice.schemas import TranscriptEvent, TranscriptEventType

logger = logging.getLogger(__name__)


class TranscriptionBridge:
    """Bridge connecting AudioEvent streams to BaseTranscriber and SegmentAccumulator.

    Guarantees:
        - Traceability: session_id is preserved; correlation_id is attached to all
          emitted TranscriptEvents via event.metadata["correlation_id"].
        - Immutability: AudioEvent and AudioFrameEvent instances are NEVER mutated.
          All sequence gap statistics are stored in bridge telemetry.
        - Sequence Integrity: Gaps in chunk_sequence_id are detected and recorded in
          telemetry; only genuine audio bytes are pushed (never fake PCM).
        - Order Enforcement: SpeechEndedEvent triggers transcriber.finish_audio(),
          guaranteeing FINAL_TRANSCRIPT is emitted before utterance completion.
    """

    def __init__(
        self,
        transcriber: BaseTranscriber,
        accumulator: Optional[SegmentAccumulator] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Initialize the TranscriptionBridge.

        Args:
            transcriber: Downstream BaseTranscriber implementation (e.g. FakeTranscriber).
            accumulator: Optional SegmentAccumulator to receive and organize transcript segments.
            session_id: Interaction session ID (defaults to transcriber.session_id if omitted).

        Raises:
            AudioError: If transcriber is not provided.
        """
        if transcriber is None or not isinstance(transcriber, BaseTranscriber):
            raise AudioError("transcriber must be an instance of BaseTranscriber.")

        self._transcriber = transcriber
        self._accumulator = accumulator
        self._session_id = session_id.strip() if session_id else transcriber.session_id

        # Utterance tracking state
        self._active_correlation_id: Optional[str] = None
        self._is_in_speech: bool = False
        self._expected_sequence_id: int = 0

        # Sequence gap and frame telemetry (stored internally; never mutates AudioEvent)
        self._gap_count: int = 0
        self._missing_chunks_total: int = 0
        self._gaps: List[dict[str, Any]] = []
        self._frames_processed: int = 0
        self._bytes_forwarded: int = 0
        self._speech_turns_completed: int = 0

        # Chronological history of enriched TranscriptEvents emitted during session
        self._transcript_events: List[TranscriptEvent] = []

        # Hook listener to attach correlation_id to all emitted TranscriptEvents
        self._transcriber.add_event_listener(self._on_transcriber_event)

    @property
    def transcriber(self) -> BaseTranscriber:
        """Return the bound BaseTranscriber instance."""
        return self._transcriber

    @property
    def accumulator(self) -> Optional[SegmentAccumulator]:
        """Return the bound SegmentAccumulator instance, if any."""
        return self._accumulator

    @property
    def session_id(self) -> str:
        """Return the active interaction session ID."""
        return self._session_id

    @property
    def is_in_speech(self) -> bool:
        """True if the bridge is currently in an active speech turn."""
        return self._is_in_speech

    @property
    def active_correlation_id(self) -> Optional[str]:
        """Correlation ID of the active speech turn, or None if idle."""
        return self._active_correlation_id

    def _on_transcriber_event(self, event: TranscriptEvent) -> None:
        """Callback listener invoked whenever the transcriber emits a TranscriptEvent.

        Safely attaches the active correlation_id to the event's metadata dictionary
        and routes the enriched event to the SegmentAccumulator (if configured).
        """
        if self._active_correlation_id:
            meta = dict(event.metadata) if event.metadata else {}
            meta["correlation_id"] = self._active_correlation_id
            event.metadata = meta

        self._transcript_events.append(event)

        if self._accumulator is not None:
            try:
                self._accumulator.add_event(event)
            except Exception as exc:
                logger.warning("SegmentAccumulator failed to process event %s: %s", event.event_id, exc)

    async def handle_audio_event(self, event: AudioEvent) -> None:
        """Process an individual AudioEvent emitted by the audio/VAD pipeline.

        Args:
            event: Typed AudioEvent (SpeechStartedEvent, AudioFrameEvent, or SpeechEndedEvent).

        Raises:
            AudioError: If event is None or of an unrecognized type.
        """
        if event is None or not isinstance(event, AudioEvent):
            raise AudioError(f"Expected AudioEvent instance, received '{type(event).__name__}'.")

        # ----------------------------------------------------------------------
        # 1. Speech Started Event
        # ----------------------------------------------------------------------
        if isinstance(event, SpeechStartedEvent):
            self._active_correlation_id = event.correlation_id
            self._expected_sequence_id = event.initial_sequence_id
            self._is_in_speech = True

            # Ensure downstream transcriber is in active LISTENING state
            if self._transcriber.state in (TranscriberState.IDLE, TranscriberState.STOPPED):
                await self._transcriber.start()

            logger.debug(
                "Speech started for turn correlation_id=%s, initial_seq=%d",
                self._active_correlation_id,
                self._expected_sequence_id,
            )

        # ----------------------------------------------------------------------
        # 2. Audio Frame Event
        # ----------------------------------------------------------------------
        elif isinstance(event, AudioFrameEvent):
            # Auto-initialize speech turn if frame arrives without explicit onset event
            if not self._is_in_speech:
                self._active_correlation_id = event.correlation_id
                self._expected_sequence_id = event.chunk_sequence_id
                self._is_in_speech = True
                if self._transcriber.state in (TranscriberState.IDLE, TranscriberState.STOPPED):
                    await self._transcriber.start()

            # Detect sequence gaps (never mutates event.metadata)
            if event.chunk_sequence_id > self._expected_sequence_id:
                missing = event.chunk_sequence_id - self._expected_sequence_id
                self._gap_count += 1
                self._missing_chunks_total += missing
                self._gaps.append(
                    {
                        "expected_sequence_id": self._expected_sequence_id,
                        "received_sequence_id": event.chunk_sequence_id,
                        "missing_chunks": missing,
                        "correlation_id": self._active_correlation_id,
                        "timestamp": event.timestamp,
                    }
                )
                logger.warning(
                    "Sequence gap detected: expected %d, got %d (%d missing chunks)",
                    self._expected_sequence_id,
                    event.chunk_sequence_id,
                    missing,
                )

            self._expected_sequence_id = event.chunk_sequence_id + 1

            # Forward genuine normalized audio bytes to transcriber (never push fake padding)
            if event.chunk is not None and event.chunk.data and len(event.chunk.data) > 0:
                self._frames_processed += 1
                self._bytes_forwarded += len(event.chunk.data)
                if self._transcriber.is_listening:
                    await self._transcriber.push_audio(event.chunk.data)

        # ----------------------------------------------------------------------
        # 3. Speech Ended Event
        # ----------------------------------------------------------------------
        elif isinstance(event, SpeechEndedEvent):
            if self._is_in_speech:
                # Conclude utterance in transcriber; emits FINAL_TRANSCRIPT & SPEECH_ENDED
                if self._transcriber.is_listening:
                    await self._transcriber.finish_audio()

                self._speech_turns_completed += 1
                self._is_in_speech = False
                logger.debug(
                    "Speech ended for turn correlation_id=%s, frames=%d, duration=%.1fms",
                    self._active_correlation_id,
                    event.total_frames,
                    event.total_speech_duration_ms,
                )
                self._active_correlation_id = None

    async def process_event_stream(
        self,
        event_stream: Union[AsyncIterable[AudioEvent], Iterable[AudioEvent]],
    ) -> None:
        """Consume an entire stream of AudioEvents until completion.

        Args:
            event_stream: Asynchronous or synchronous iterable of AudioEvent instances.
        """
        if hasattr(event_stream, "__aiter__"):
            async for event in event_stream:  # type: ignore
                await self.handle_audio_event(event)
        else:
            for event in event_stream:  # type: ignore
                await self.handle_audio_event(event)

    def get_telemetry(self) -> dict[str, Any]:
        """Return diagnostic snapshot of bridge operations, gaps, and throughput."""
        return {
            "session_id": self._session_id,
            "active_correlation_id": self._active_correlation_id,
            "is_in_speech": self._is_in_speech,
            "expected_sequence_id": self._expected_sequence_id,
            "gap_count": self._gap_count,
            "missing_chunks_total": self._missing_chunks_total,
            "gaps": list(self._gaps),
            "frames_processed": self._frames_processed,
            "bytes_forwarded": self._bytes_forwarded,
            "speech_turns_completed": self._speech_turns_completed,
            "transcript_events_count": len(self._transcript_events),
        }

    def get_transcript_events(self) -> List[TranscriptEvent]:
        """Return a copy of all emitted and correlation-enriched TranscriptEvents."""
        return list(self._transcript_events)
