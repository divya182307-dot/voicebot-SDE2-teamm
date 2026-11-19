"""Provider-neutral Speech-to-Text (STT) adapter interfaces and audio configuration.

This module defines the abstract contracts and data types for speech-to-text transcribers,
enabling interchangeable implementations (e.g., Deepgram, Whisper, Google Cloud Speech,
Azure Speech, and local or fake test transcribers).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from enum import Enum
import inspect
import logging
from typing import (
    Any,
    AsyncIterable,
    AsyncIterator,
    Callable,
    List,
    Optional,
    Set,
    Union,
)

from pydantic import BaseModel, ConfigDict, Field

from src.voice.exceptions import (
    TranscriberAudioError,
    TranscriberError,
    TranscriberStateError,
)
from src.voice.schemas import (
    TranscriptError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
    WordTiming,
)

logger = logging.getLogger(__name__)

# Type alias for event callbacks (synchronous or asynchronous)
EventListener = Callable[[TranscriptEvent], Union[None, asyncio.Future[None], Any]]


class AudioEncoding(str, Enum):
    """Supported audio encodings for voice stream ingestion."""

    PCM_S16LE = "pcm_s16le"  # 16-bit linear PCM (signed integer, little-endian)
    PCM_F32LE = "pcm_f32le"  # 32-bit linear PCM (IEEE float, little-endian)
    OPUS = "opus"            # Opus compressed audio
    MULAW = "mulaw"          # 8-bit G.711 mu-law
    ALAW = "alaw"            # 8-bit G.711 a-law


class AudioConfig(BaseModel):
    """Audio stream specification and format parameters.

    Fields:
        sample_rate_hertz: Audio sample rate in Hz (e.g., 16000 for standard speech).
        channels: Number of audio channels (1 for mono, 2 for stereo).
        encoding: Audio encoding format (defaults to PCM_S16LE).
        chunk_duration_ms: Duration of an individual audio chunk in milliseconds.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_rate_hertz: int = Field(
        default=16000,
        ge=8000,
        le=48000,
        description="Audio sampling rate in Hertz (e.g., 8000, 16000, 44100, 48000)",
    )
    channels: int = Field(
        default=1,
        ge=1,
        le=2,
        description="Channel count (1=mono, 2=stereo)",
    )
    encoding: AudioEncoding = Field(
        default=AudioEncoding.PCM_S16LE,
        description="Audio codec or sample format",
    )
    chunk_duration_ms: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Duration of each audio frame/chunk in milliseconds",
    )

    @property
    def bytes_per_sample(self) -> int:
        """Return the number of bytes per audio sample."""
        if self.encoding == AudioEncoding.PCM_S16LE:
            return 2
        elif self.encoding == AudioEncoding.PCM_F32LE:
            return 4
        elif self.encoding in (AudioEncoding.MULAW, AudioEncoding.ALAW):
            return 1
        return 2  # Fallback standard

    @property
    def bytes_per_second(self) -> int:
        """Calculate bytes transferred per second for raw linear PCM."""
        return self.sample_rate_hertz * self.channels * self.bytes_per_sample

    @property
    def chunk_size_bytes(self) -> int:
        """Calculate nominal size in bytes for a chunk of `chunk_duration_ms`."""
        return (self.bytes_per_second * self.chunk_duration_ms) // 1000

    def bytes_to_duration_ms(self, byte_count: int) -> int:
        """Convert a byte count to audio duration in milliseconds."""
        if self.bytes_per_second == 0:
            return 0
        return (byte_count * 1000) // self.bytes_per_second

    def duration_ms_to_bytes(self, duration_ms: int) -> int:
        """Convert duration in milliseconds to expected raw byte count."""
        return (duration_ms * self.bytes_per_second) // 1000


class TranscriberState(str, Enum):
    """Lifecycle state machine for a transcriber instance."""

    IDLE = "idle"            # Initialized, not yet started
    STARTING = "starting"    # Connection/handshake in progress
    LISTENING = "listening"  # Actively receiving audio and emitting events
    STOPPING = "stopping"    # Flushed and closing down
    STOPPED = "stopped"      # Gracefully terminated
    ERROR = "error"          # Unrecoverable operational failure


class TranscriberConfig(BaseModel):
    """Configuration options for speech-to-text transcribers.

    Fields:
        audio_config: Audio input specification.
        language: BCP-47 / ISO language code (e.g. 'en-US', 'es-419').
        interim_results: Whether to emit speculative interim transcripts.
        punctuate: Whether to apply automatic punctuation and capitalization.
        word_timings: Whether to include sub-segment WordTiming breakdowns.
        endpointing_silence_ms: Silence duration in ms to treat as turn completion.
        model: Provider-specific model name (e.g. 'nova-2', 'whisper-large-v3').
        provider_options: Arbitrary provider-specific settings.
    """

    model_config = ConfigDict(extra="forbid")

    audio_config: AudioConfig = Field(
        default_factory=AudioConfig,
        description="Audio stream format and timing configuration",
    )
    language: str = Field(
        default="en-US",
        description="Target speech language tag",
    )
    interim_results: bool = Field(
        default=True,
        description="If True, emit uncommitted hypothesis events during speech",
    )
    punctuate: bool = Field(
        default=True,
        description="If True, enable automatic punctuation and formatting",
    )
    word_timings: bool = Field(
        default=True,
        description="If True, generate word-level timestamp breakdowns",
    )
    endpointing_silence_ms: int = Field(
        default=500,
        ge=100,
        le=5000,
        description="Milliseconds of silence required to detect turn finalization",
    )
    model: Optional[str] = Field(
        default=None,
        description="Optional provider model identifier",
    )
    provider_options: dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible provider-specific configuration flags",
    )


class BaseTranscriber(ABC):
    """Abstract base class defining the provider-neutral Speech-to-Text adapter contract.

    This class handles:
    - Lifecycle state machine (IDLE -> STARTING -> LISTENING -> STOPPING -> STOPPED / ERROR).
    - Asynchronous context manager support (`async with transcriber:`).
    - Event subscriber broadcasting for both async streaming iterators and callback listeners.
    - Standard audio ingestion validation and completion signaling.
    - Batch transcription helpers for single-shot buffers.
    """

    def __init__(
        self,
        session_id: str,
        config: Optional[TranscriberConfig] = None,
    ) -> None:
        """Initialize the transcriber adapter.

        Args:
            session_id: Unique interaction/client session identifier.
            config: Optional transcriber configuration (uses defaults if omitted).

        Raises:
            ValueError: If session_id is empty or whitespace.
        """
        stripped_id = session_id.strip() if session_id else ""
        if not stripped_id:
            raise ValueError("session_id must be a non-empty string.")

        self._session_id: str = stripped_id
        self._config: TranscriberConfig = config or TranscriberConfig()
        self._state: TranscriberState = TranscriberState.IDLE
        self._listeners: Set[EventListener] = set()
        self._subscribers: Set[asyncio.Queue[Optional[TranscriptEvent]]] = set()
        self._events_history: List[TranscriptEvent] = []
        self._sequence_counter: int = 0
        self._state_lock = asyncio.Lock()

    @property
    def session_id(self) -> str:
        """Return the active session ID."""
        return self._session_id

    @property
    def config(self) -> TranscriberConfig:
        """Return current transcriber configuration."""
        return self._config

    @property
    def state(self) -> TranscriberState:
        """Return current operational state."""
        return self._state

    @property
    def is_listening(self) -> bool:
        """True if transcriber is actively ready to receive audio."""
        return self._state == TranscriberState.LISTENING

    @property
    def is_closed(self) -> bool:
        """True if transcriber has concluded or errored."""
        return self._state in (TranscriberState.STOPPED, TranscriberState.ERROR)

    @property
    def events_history(self) -> List[TranscriptEvent]:
        """Return chronological record of all events emitted in this session."""
        return list(self._events_history)

    async def start(self) -> None:
        """Transition transcriber to active listening state.

        Raises:
            TranscriberStateError: If transcriber is already listening or stopping.
        """
        async with self._state_lock:
            if self._state not in (TranscriberState.IDLE, TranscriberState.STOPPED):
                raise TranscriberStateError(
                    f"Cannot start transcriber in state '{self._state.value}'. Expected IDLE or STOPPED."
                )
            self._state = TranscriberState.STARTING

        try:
            await self._on_start()
            async with self._state_lock:
                self._state = TranscriberState.LISTENING
            logger.debug("Transcriber session '%s' is now LISTENING.", self._session_id)
        except Exception as exc:
            async with self._state_lock:
                self._state = TranscriberState.ERROR
            logger.error("Failed to start transcriber session '%s': %s", self._session_id, exc)
            if not isinstance(exc, TranscriberError):
                raise TranscriberError(f"Transcriber startup failed: {exc}") from exc
            raise

    async def stop(self) -> None:
        """Conclude active session, flush pending events, and release resources."""
        async with self._state_lock:
            if self._state in (TranscriberState.STOPPED, TranscriberState.ERROR):
                return
            self._state = TranscriberState.STOPPING

        try:
            await self._on_stop()
        finally:
            async with self._state_lock:
                self._state = TranscriberState.STOPPED

            # Notify all active stream subscribers of stream termination (sentinel None)
            for queue in list(self._subscribers):
                await queue.put(None)
            logger.debug("Transcriber session '%s' has STOPPED.", self._session_id)

    async def __aenter__(self) -> BaseTranscriber:
        """Enter asynchronous context, auto-starting the transcriber."""
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit asynchronous context, auto-stopping the transcriber."""
        await self.stop()

    async def push_audio(self, chunk: bytes) -> None:
        """Ingest a chunk of raw audio bytes into the transcription stream.

        Args:
            chunk: Audio bytes adhering to the configured AudioConfig.

        Raises:
            TranscriberStateError: If called when not in LISTENING state.
            TranscriberAudioError: If audio chunk is empty or invalid.
        """
        if self._state != TranscriberState.LISTENING:
            raise TranscriberStateError(
                f"Cannot push audio in state '{self._state.value}'. Transcriber must be in LISTENING state."
            )

        if not isinstance(chunk, (bytes, bytearray)):
            raise TranscriberAudioError("Audio chunk must be an instance of bytes or bytearray.")

        if len(chunk) == 0:
            raise TranscriberAudioError("Audio chunk cannot be empty.")

        await self._process_audio_chunk(bytes(chunk))

    async def finish_audio(self) -> None:
        """Signal that no more audio will be pushed, finalizing any pending utterance."""
        if self._state != TranscriberState.LISTENING:
            raise TranscriberStateError(
                f"Cannot finish audio in state '{self._state.value}'. Transcriber must be in LISTENING state."
            )
        await self._on_finish_audio()

    def add_event_listener(self, listener: EventListener) -> None:
        """Register a callback to receive emitted TranscriptEvents."""
        self._listeners.add(listener)

    def remove_event_listener(self, listener: EventListener) -> None:
        """Unregister a previously added event callback."""
        self._listeners.discard(listener)

    async def stream(self) -> AsyncIterator[TranscriptEvent]:
        """Asynchronously stream TranscriptEvents as they are emitted.

        Yields:
            TranscriptEvent instances until session termination.
        """
        queue: asyncio.Queue[Optional[TranscriptEvent]] = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            self._subscribers.discard(queue)

    async def transcribe_audio(self, audio_data: bytes) -> List[TranscriptEvent]:
        """Batch-transcribe a complete audio byte buffer.

        Starts the session if not running, pushes audio chunks sized according to
        AudioConfig, signals completion, and returns all emitted TranscriptEvents.

        Args:
            audio_data: Full raw audio byte buffer.

        Returns:
            List of generated TranscriptEvent objects in chronological order.
        """
        events: List[TranscriptEvent] = []
        queue: asyncio.Queue[Optional[TranscriptEvent]] = asyncio.Queue()
        self._subscribers.add(queue)

        async def _collector() -> None:
            while True:
                item = await queue.get()
                if item is None:
                    break
                events.append(item)

        collector_task = asyncio.create_task(_collector())

        try:
            started_here = False
            if self._state != TranscriberState.LISTENING:
                await self.start()
                started_here = True

            chunk_size = self._config.audio_config.chunk_size_bytes
            for offset in range(0, len(audio_data), chunk_size):
                chunk = audio_data[offset : offset + chunk_size]
                if chunk:
                    await self.push_audio(chunk)

            await self.finish_audio()

            if started_here:
                await self.stop()
            else:
                # Signal collector completion
                await queue.put(None)

            await collector_task
            return events
        finally:
            self._subscribers.discard(queue)
            if not collector_task.done():
                collector_task.cancel()

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterable[bytes],
    ) -> AsyncIterator[TranscriptEvent]:
        """Pipe an async iterable of audio chunks and yield events as they arrive.

        Args:
            audio_stream: Asynchronous iterable yielding audio byte chunks.

        Yields:
            TranscriptEvent objects emitted during the stream.
        """
        output_queue: asyncio.Queue[Optional[TranscriptEvent]] = asyncio.Queue()
        self._subscribers.add(output_queue)

        async def _audio_feeder() -> None:
            try:
                async for chunk in audio_stream:
                    if chunk:
                        await self.push_audio(chunk)
                await self.finish_audio()
            except Exception as e:
                logger.error("Error feeding audio stream: %s", e)
            finally:
                await output_queue.put(None)

        feeder_task = asyncio.create_task(_audio_feeder())

        try:
            while True:
                item = await output_queue.get()
                if item is None:
                    break
                yield item
        finally:
            self._subscribers.discard(output_queue)
            if not feeder_task.done():
                feeder_task.cancel()

    async def _emit_event(self, event: TranscriptEvent) -> None:
        """Internal helper to dispatch a TranscriptEvent to all subscribers and listeners."""
        self._sequence_counter += 1
        if event.sequence_number is None:
            # Assign monotonic sequence number if not already populated
            event = event.model_copy(update={"sequence_number": self._sequence_counter})

        self._events_history.append(event)

        # Distribute to queue subscribers (async iterators)
        for queue in list(self._subscribers):
            await queue.put(event)

        # Distribute to registered callback listeners
        for listener in list(self._listeners):
            try:
                res = listener(event)
                if inspect.isawaitable(res):
                    await res
            except Exception as exc:
                logger.warning("Error in event listener %s: %s", listener, exc)

    # --------------------------------------------------------------------------
    # Abstract template methods for provider-specific implementations
    # --------------------------------------------------------------------------

    @abstractmethod
    async def _on_start(self) -> None:
        """Provider-specific startup logic (e.g., connect WebSocket, handshake)."""
        pass

    @abstractmethod
    async def _on_stop(self) -> None:
        """Provider-specific shutdown logic (e.g., close connections, free buffers)."""
        pass

    @abstractmethod
    async def _process_audio_chunk(self, chunk: bytes) -> None:
        """Provider-specific audio chunk ingestion and frame processing."""
        pass

    @abstractmethod
    async def _on_finish_audio(self) -> None:
        """Provider-specific stream termination and finalization flush."""
        pass
