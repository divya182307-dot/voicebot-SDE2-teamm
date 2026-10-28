"""Deterministic fake speech-to-text transcriber for testing and offline simulation.

This module provides a fully deterministic STT adapter adhering to `BaseTranscriber`.
Given the same input (audio bytes, script, seed, or session parameters), it guarantees
identical, reproducible output events, segments, word timings, sequence numbers, and IDs.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import re
from typing import Any, List, Optional, Sequence, Union
import uuid

from pydantic import BaseModel, ConfigDict, Field

from src.voice.adapter import (
    AudioConfig,
    BaseTranscriber,
    TranscriberConfig,
    TranscriberState,
)
from src.voice.exceptions import TranscriberError
from src.voice.schemas import (
    TranscriptError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
    WordTiming,
)

# Canonical academic corpus for deterministic fallback generation
DEFAULT_ACADEMIC_CORPUS: List[str] = [
    "Can you explain the difference between processes and threads?",
    "How does Dijkstra's shortest path algorithm work?",
    "What is the time complexity of quicksort in the worst case?",
    "Why is my recursive function causing a stack overflow?",
    "Explain how the attention mechanism works in transformer models?",
    "How do I prevent SQL injection in my web backend?",
    "What is the CAP theorem in distributed systems?",
    "Could you review this pull request and suggest optimizations?",
]

# Fixed reference epoch for 100% deterministic, reproducible timestamps across test runs
DEFAULT_REFERENCE_TIMESTAMP: datetime = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class FakeUtterance(BaseModel):
    """Specification of an utterance to be simulated by the fake transcriber.

    Fields:
        text: Final transcribed sentence or phrase.
        duration_ms: Expected spoken duration of the utterance in milliseconds.
        confidence: Normalized confidence score [0.0, 1.0].
        language: BCP-47 / ISO language code.
        words: Optional explicit word timings (computed deterministically if omitted).
        interim_steps: Optional explicit progressive interim texts.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, description="Transcribed utterance text")
    duration_ms: int = Field(
        default=1200,
        ge=100,
        description="Spoken duration of this utterance in milliseconds",
    )
    confidence: float = Field(
        default=0.98,
        ge=0.0,
        le=1.0,
        description="Confidence score for this utterance",
    )
    language: str = Field(
        default="en-US",
        description="Language code for the utterance",
    )
    words: Optional[List[WordTiming]] = Field(
        default=None,
        description="Optional custom word timings",
    )
    interim_steps: Optional[List[str]] = Field(
        default=None,
        description="Optional custom interim text progression",
    )


def generate_deterministic_words(
    text: str,
    start_time_ms: int,
    end_time_ms: int,
    base_confidence: float = 0.96,
) -> List[WordTiming]:
    """Deterministically slice an utterance into WordTiming entries with realistic pacing.

    Args:
        text: Spoken utterance text.
        start_time_ms: Start offset of the utterance.
        end_time_ms: End offset of the utterance.
        base_confidence: Target confidence score.

    Returns:
        List of strictly validated WordTiming models.
    """
    raw_tokens = text.strip().split()
    if not raw_tokens:
        return []

    # Clean punctuation for token words while keeping tokens valid
    tokens = [re.sub(r"[^\w\'-]", "", t) for t in raw_tokens]
    tokens = [t if t else raw_tokens[i] for i, t in enumerate(tokens)]

    total_duration = max(end_time_ms - start_time_ms, len(tokens) * 50)
    total_chars = sum(len(t) for t in tokens) or len(tokens)

    word_timings: List[WordTiming] = []
    current_time = start_time_ms

    for idx, token in enumerate(tokens):
        # Character-weighted duration allocation
        token_share = len(token) / total_chars
        token_duration = max(int(total_duration * token_share), 60)

        # Allocate small gap (10ms) between words except the last
        is_last = idx == len(tokens) - 1
        word_start = current_time
        word_end = end_time_ms if is_last else min(current_time + token_duration - 10, end_time_ms)
        if word_end < word_start:
            word_end = word_start + 10

        # Deterministic micro-variance in confidence using token hash
        h = int(hashlib.md5(token.encode("utf-8")).hexdigest()[:4], 16)
        variance = ((h % 9) - 4) * 0.01  # range: -0.04 to +0.04
        word_confidence = round(max(0.70, min(1.0, base_confidence + variance)), 4)

        word_timings.append(
            WordTiming(
                word=token,
                start_time_ms=word_start,
                end_time_ms=word_end,
                confidence=word_confidence,
            )
        )
        current_time = word_end + 10

    return word_timings


def generate_progressive_interims(text: str) -> List[str]:
    """Generate progressive partial phrases for streaming interim hypotheses.

    For example: 'Why is this failing' -> ['Why', 'Why is', 'Why is this', 'Why is this failing']
    """
    words = text.strip().split()
    if not words:
        return [text]
    return [" ".join(words[: i + 1]) for i in range(len(words))]


class FakeTranscriber(BaseTranscriber):
    """Deterministic Fake Speech-to-Text transcriber.

    Guarantees:
    - Same inputs (audio bytes, script, seed) -> 100% IDENTICAL transcript events.
    - Reproducible UUID5 event and segment IDs.
    - Reproducible timestamps based on a reference epoch plus audio offset.
    - Adheres to full BaseTranscriber contract and state machine.
    - Supports simulated real-time delay or zero-latency test execution.
    - Supports deterministic error injection to test failure handling.
    """

    def __init__(
        self,
        session_id: str,
        config: Optional[TranscriberConfig] = None,
        script: Optional[Union[str, Sequence[Union[str, FakeUtterance]]]] = None,
        seed: int = 42,
        base_timestamp: Optional[datetime] = None,
        simulate_realtime: bool = False,
        error_after_chunks: Optional[int] = None,
        simulated_error: Optional[TranscriptError] = None,
    ) -> None:
        """Initialize the deterministic FakeTranscriber.

        Args:
            session_id: Client interaction session ID.
            config: Transcriber configuration (audio formats, language, etc.).
            script: Pre-scripted utterance(s) to emit. Can be a string, list of strings,
                or list of FakeUtterance objects. If None, derived deterministically from audio.
            seed: Deterministic integer seed for reproducible fallbacks.
            base_timestamp: Fixed reference UTC datetime for timestamps (defaults to 2026-01-01T12:00:00Z).
            simulate_realtime: If True, uses asyncio.sleep to mimic natural speech cadence.
            error_after_chunks: If specified, emits an ERROR event after N chunks.
            simulated_error: Custom TranscriptError payload for injected failure testing.
        """
        super().__init__(session_id=session_id, config=config)
        self._seed = seed
        self._base_timestamp = base_timestamp or DEFAULT_REFERENCE_TIMESTAMP
        self._simulate_realtime = simulate_realtime
        self._error_after_chunks = error_after_chunks
        self._simulated_error = simulated_error

        # Normalize and store configured utterances
        self._configured_utterances: Optional[List[FakeUtterance]] = None
        if script is not None:
            self._configured_utterances = self._normalize_script(script)

        # Internal audio stream state
        self._chunk_count: int = 0
        self._total_bytes_received: int = 0
        self._audio_hasher = hashlib.sha256()
        self._audio_time_ms: int = 0

        # Utterance tracking
        self._current_utterance_idx: int = 0
        self._utterance_started: bool = False
        self._interim_step_idx: int = 0
        self._active_utterance: Optional[FakeUtterance] = None
        self._active_segment_id: Optional[str] = None
        self._utterance_start_audio_ms: int = 0

    def _normalize_script(
        self,
        script: Union[str, Sequence[Union[str, FakeUtterance]]],
    ) -> List[FakeUtterance]:
        """Convert string or list inputs into canonical FakeUtterance instances."""
        if isinstance(script, str):
            script_items = [script]
        else:
            script_items = list(script)

        utterances: List[FakeUtterance] = []
        for item in script_items:
            if isinstance(item, FakeUtterance):
                utterances.append(item)
            elif isinstance(item, str):
                utterances.append(
                    FakeUtterance(
                        text=item.strip(),
                        duration_ms=max(1000, len(item.split()) * 250),
                        language=self._config.language,
                    )
                )
            else:
                raise TypeError(f"Invalid script item type: {type(item)}. Expected str or FakeUtterance.")

        return utterances

    def _deterministic_uuid(self, *parts: Any) -> str:
        """Derive a deterministic UUID5 string based on session ID and event components."""
        namespace = uuid.NAMESPACE_DNS
        key = f"voicebot:{self._session_id}:" + ":".join(str(p) for p in parts)
        return str(uuid.uuid5(namespace, key))

    def _current_timestamp(self) -> datetime:
        """Derive reproducible UTC timestamp offset by audio elapsed milliseconds."""
        return self._base_timestamp + timedelta(milliseconds=self._audio_time_ms)

    def _select_or_create_utterance(self) -> Optional[FakeUtterance]:
        """Return the active FakeUtterance based on script or audio hash."""
        if self._configured_utterances is not None:
            if self._current_utterance_idx < len(self._configured_utterances):
                return self._configured_utterances[self._current_utterance_idx]
            # All configured utterances in script have completed
            return None

        # Audio-driven determinism: derive utterance from audio hash fingerprint
        audio_digest = self._audio_hasher.hexdigest()
        digest_int = int(audio_digest[:8], 16) + self._seed + self._current_utterance_idx
        idx = digest_int % len(DEFAULT_ACADEMIC_CORPUS)
        text = DEFAULT_ACADEMIC_CORPUS[idx]

        return FakeUtterance(
            text=text,
            duration_ms=max(1200, len(text.split()) * 250),
            language=self._config.language,
        )

    # --------------------------------------------------------------------------
    # Lifecycle hooks
    # --------------------------------------------------------------------------

    async def _on_start(self) -> None:
        """Reset internal stream counters for a new clean run."""
        self._chunk_count = 0
        self._total_bytes_received = 0
        self._audio_time_ms = 0
        self._current_utterance_idx = 0
        self._utterance_started = False
        self._interim_step_idx = 0
        self._active_utterance = None
        self._active_segment_id = None
        self._utterance_start_audio_ms = 0
        self._audio_hasher = hashlib.sha256()

    async def _on_stop(self) -> None:
        """Flush any pending utterance before concluding."""
        if self._utterance_started:
            await self._finalize_current_utterance()

    # --------------------------------------------------------------------------
    # Audio ingestion
    # --------------------------------------------------------------------------

    async def _process_audio_chunk(self, chunk: bytes) -> None:
        """Process incoming audio bytes deterministically."""
        self._chunk_count += 1
        self._total_bytes_received += len(chunk)
        self._audio_hasher.update(chunk)

        # Check for deterministic error injection trigger
        if self._error_after_chunks is not None and self._chunk_count >= self._error_after_chunks:
            error_payload = self._simulated_error or TranscriptError(
                code="SIMULATED_TRANSCRIBER_ERROR",
                message=f"Deterministic failure injected after chunk {self._chunk_count}.",
                details={"chunk_count": self._chunk_count, "bytes": len(chunk)},
            )
            event_id = self._deterministic_uuid("error", self._chunk_count)
            error_event = TranscriptEvent(
                event_id=event_id,
                session_id=self._session_id,
                event_type=TranscriptEventType.ERROR,
                timestamp=self._current_timestamp(),
                error=error_payload,
            )
            await self._emit_event(error_event)
            self._state = TranscriberState.ERROR
            return

        chunk_ms = self._config.audio_config.bytes_to_duration_ms(len(chunk))
        self._audio_time_ms += chunk_ms

        # Real-time simulation delay if enabled
        if self._simulate_realtime and chunk_ms > 0:
            await asyncio.sleep(chunk_ms / 1000.0)

        # Prepare active utterance if needed
        if self._active_utterance is None:
            self._active_utterance = self._select_or_create_utterance()
            if self._active_utterance is None:
                # Script completed; no further utterances to emit
                return
            self._utterance_start_audio_ms = self._audio_time_ms - chunk_ms
            self._active_segment_id = self._deterministic_uuid(
                "segment", self._current_utterance_idx, self._active_utterance.text
            )

        # 1. Emit SPEECH_STARTED on onset
        if not self._utterance_started:
            self._utterance_started = True
            speech_started_event = TranscriptEvent(
                event_id=self._deterministic_uuid("speech_started", self._current_utterance_idx),
                session_id=self._session_id,
                event_type=TranscriptEventType.SPEECH_STARTED,
                timestamp=self._current_timestamp(),
            )
            await self._emit_event(speech_started_event)

        # 2. Emit INTERIM_TRANSCRIPT progression if enabled
        if self._config.interim_results:
            interim_steps = self._active_utterance.interim_steps or generate_progressive_interims(
                self._active_utterance.text
            )
            elapsed_in_utterance = self._audio_time_ms - self._utterance_start_audio_ms
            step_duration = max(self._active_utterance.duration_ms // max(len(interim_steps), 1), 100)
            target_step = min(elapsed_in_utterance // step_duration, len(interim_steps) - 1)

            if target_step >= self._interim_step_idx:
                step_text = interim_steps[self._interim_step_idx]
                interim_segment = TranscriptSegment(
                    id=self._active_segment_id or "seg-default",
                    start_time_ms=self._utterance_start_audio_ms,
                    end_time_ms=self._audio_time_ms,
                    text=step_text,
                    confidence=round(min(0.75 + (self._interim_step_idx * 0.05), 0.95), 4),
                    is_final=False,
                    language=self._active_utterance.language,
                )
                interim_event = TranscriptEvent(
                    event_id=self._deterministic_uuid("interim", self._current_utterance_idx, self._interim_step_idx),
                    session_id=self._session_id,
                    event_type=TranscriptEventType.INTERIM_TRANSCRIPT,
                    timestamp=self._current_timestamp(),
                    segment=interim_segment,
                )
                await self._emit_event(interim_event)
                self._interim_step_idx += 1

        # 3. Finalize utterance if enough audio received for its duration
        elapsed_in_utterance = self._audio_time_ms - self._utterance_start_audio_ms
        if elapsed_in_utterance >= self._active_utterance.duration_ms:
            await self._finalize_current_utterance()

    async def _finalize_current_utterance(self) -> None:
        """Lock in FINAL_TRANSCRIPT and emit SPEECH_ENDED for current utterance."""
        if not self._active_utterance:
            return

        utterance = self._active_utterance
        seg_start = self._utterance_start_audio_ms
        seg_end = self._audio_time_ms

        # Compute word timings deterministically if requested
        words: Optional[List[WordTiming]] = None
        if self._config.word_timings:
            words = utterance.words or generate_deterministic_words(
                text=utterance.text,
                start_time_ms=seg_start,
                end_time_ms=seg_end,
                base_confidence=utterance.confidence,
            )

        final_segment = TranscriptSegment(
            id=self._active_segment_id or "seg-default",
            start_time_ms=seg_start,
            end_time_ms=seg_end,
            text=utterance.text,
            confidence=utterance.confidence,
            is_final=True,
            language=utterance.language,
            words=words,
        )

        final_event = TranscriptEvent(
            event_id=self._deterministic_uuid("final", self._current_utterance_idx),
            session_id=self._session_id,
            event_type=TranscriptEventType.FINAL_TRANSCRIPT,
            timestamp=self._current_timestamp(),
            segment=final_segment,
        )
        await self._emit_event(final_event)

        speech_ended_event = TranscriptEvent(
            event_id=self._deterministic_uuid("speech_ended", self._current_utterance_idx),
            session_id=self._session_id,
            event_type=TranscriptEventType.SPEECH_ENDED,
            timestamp=self._current_timestamp(),
        )
        await self._emit_event(speech_ended_event)

        # Advance to next utterance slot
        self._current_utterance_idx += 1
        self._utterance_started = False
        self._interim_step_idx = 0
        self._active_utterance = None
        self._active_segment_id = None
        self._utterance_start_audio_ms = self._audio_time_ms

    async def _on_finish_audio(self) -> None:
        """Flush and lock active utterance upon stream completion."""
        if self._utterance_started and self._active_utterance is not None:
            await self._finalize_current_utterance()
        elif not self._utterance_started and self._configured_utterances:
            # If finish_audio was invoked directly on pre-scripted utterances
            while self._current_utterance_idx < len(self._configured_utterances):
                self._active_utterance = self._configured_utterances[self._current_utterance_idx]
                self._active_segment_id = self._deterministic_uuid(
                    "segment", self._current_utterance_idx, self._active_utterance.text
                )
                self._audio_time_ms += self._active_utterance.duration_ms

                # Emit SPEECH_STARTED
                await self._emit_event(
                    TranscriptEvent(
                        event_id=self._deterministic_uuid("speech_started", self._current_utterance_idx),
                        session_id=self._session_id,
                        event_type=TranscriptEventType.SPEECH_STARTED,
                        timestamp=self._current_timestamp(),
                    )
                )
                # Emit FINAL and ENDED
                await self._finalize_current_utterance()
