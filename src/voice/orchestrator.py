"""Speech-to-Text Transcription Orchestrator.

This module provides the central coordination layer bridging incoming audio chunk streams,
audio preprocessing (resampling & normalization), provider adapters (e.g., FakeTranscriber or vendor engines),
bounded retry & timeout resilience, event publishing, the ordered segment accumulator, and transcript reconciliation.
"""

from __future__ import annotations

import asyncio
from enum import Enum
import inspect
import logging
from typing import (
    Any,
    AsyncIterator,
    Callable,
    List,
    Optional,
    Set,
    Union,
)

from pydantic import BaseModel, ConfigDict, Field

from src.voice.accumulator import (
    AccumulatedTranscript,
    AccumulatorConfig,
    SegmentAccumulator,
)
from src.voice.adapter import (
    AudioConfig,
    BaseTranscriber,
    EventListener,
    TranscriberConfig,
    TranscriberState,
)
from src.voice.exceptions import (
    AudioPreprocessingError,
    OrchestratorError,
    OrchestratorStateError,
    TranscriberAudioError,
    TranscriberError,
)
from src.voice.fake_transcriber import FakeTranscriber
from src.voice.preprocessing import (
    AudioPreprocessor,
    AudioPreprocessorConfig,
)
from src.voice.reconciliation import (
    ReconciliationConfig,
    ReconciliationMetrics,
    TranscriptReconciler,
)
from src.voice.resilience import (
    ErrorNormalizer,
    ResilienceMetrics,
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
)

logger = logging.getLogger(__name__)


class OrchestratorState(str, Enum):
    """Operational lifecycle state machine for TranscriptionOrchestrator."""

    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class OrchestratorMetrics(BaseModel):
    """Session telemetry and streaming ingestion metrics."""

    model_config = ConfigDict(extra="forbid")

    chunks_ingested: int = Field(default=0, ge=0, description="Total audio chunks ingested")
    bytes_ingested: int = Field(default=0, ge=0, description="Total raw audio bytes ingested")
    audio_duration_ms: int = Field(default=0, ge=0, description="Cumulative audio duration in ms")
    events_emitted: int = Field(default=0, ge=0, description="Count of transcript events produced")
    speech_turns_detected: int = Field(default=0, ge=0, description="Count of speech_started events")
    final_segments_count: int = Field(default=0, ge=0, description="Count of final_transcript events")
    duplicates_suppressed: int = Field(default=0, ge=0, description="Count of duplicate events/segments suppressed")
    out_of_order_resolved: int = Field(default=0, ge=0, description="Count of out-of-order segments reordered")
    stale_interims_suppressed: int = Field(default=0, ge=0, description="Count of stale interim events dropped")
    repeated_interims_suppressed: int = Field(default=0, ge=0, description="Count of repeated interim hypotheses filtered")
    chunks_preprocessed: int = Field(default=0, ge=0, description="Count of chunks processed through AudioPreprocessor")
    retries_attempted: int = Field(default=0, ge=0, description="Count of provider retry attempts executed")
    retries_succeeded: int = Field(default=0, ge=0, description="Count of operations that recovered via retry")
    retries_exhausted: int = Field(default=0, ge=0, description="Count of operations where retries were exhausted")
    timeouts_encountered: int = Field(default=0, ge=0, description="Count of timeout events encountered")
    errors_normalized: int = Field(default=0, ge=0, description="Count of raw exceptions normalized into domain models")


class OrchestratorConfig(BaseModel):
    """Configuration options for TranscriptionOrchestrator behavior."""

    model_config = ConfigDict(extra="forbid")

    auto_start: bool = Field(
        default=True,
        description="Automatically start the orchestrator on first push_audio call if IDLE",
    )
    chunk_buffer_size: int = Field(
        default=200,
        ge=10,
        le=5000,
        description="Maximum capacity of asynchronous audio chunk ingestion queue",
    )
    enable_reconciliation: bool = Field(
        default=True,
        description="Enable ordering, deduplication, and interim reconciliation layer",
    )
    enable_preprocessing: bool = Field(
        default=False,
        description="Enable automatic audio preprocessing (resampling & volume normalization)",
    )
    preprocessor_config: Optional[AudioPreprocessorConfig] = Field(
        default=None,
        description="Configuration for audio resampling and amplitude normalization",
    )
    retry_config: Optional[RetryConfig] = Field(
        default=None,
        description="Bounded retry policy for provider operations",
    )
    timeout_config: Optional[TimeoutConfig] = Field(
        default=None,
        description="Timeout thresholds for connect, chunk processing, and operations",
    )
    transcriber_config: Optional[TranscriberConfig] = Field(
        default=None,
        description="Configuration passed to default transcriber if created internally",
    )
    accumulator_config: Optional[AccumulatorConfig] = Field(
        default=None,
        description="Configuration for internal SegmentAccumulator",
    )
    reconciliation_config: Optional[ReconciliationConfig] = Field(
        default=None,
        description="Configuration for stream ordering and duplicate suppression",
    )


class TranscriptionOrchestrator:
    """Orchestrates audio chunk ingestion, transcriber adapters, and transcript events.

    Core Responsibilities (Days 8–13):
    1. **Streaming Audio Ingestion & Preprocessing**: Safely queues, downmixes, resamples, and normalizes audio chunks.
    2. **Fault Tolerance & Resilience**: Applies bounded retries and timeouts, normalizing raw errors so none leak.
    3. **Ordering & Deduplication**: Reconciles out-of-order segments and suppresses duplicates via TranscriptReconciler.
    4. **Transcript Aggregation**: Connects the streaming event pipeline to the ordered SegmentAccumulator.
    5. **Multi-Subscriber Dispatch**: Broadcasts clean reconciled events to async iterators (`stream()`)
       and registered callback listeners.
    6. **Telemetry & State Management**: Tracks ingestion, preprocessing, deduplication, retry, and ordering metrics.
    """

    def __init__(
        self,
        session_id: str,
        transcriber: Optional[BaseTranscriber] = None,
        config: Optional[OrchestratorConfig] = None,
        accumulator: Optional[SegmentAccumulator] = None,
        reconciler: Optional[TranscriptReconciler] = None,
        preprocessor: Optional[AudioPreprocessor] = None,
        script: Optional[Union[str, List[str]]] = None,
    ) -> None:
        """Initialize the transcription orchestrator.

        Args:
            session_id: Non-empty session identifier.
            transcriber: Optional BaseTranscriber instance. Defaults to FakeTranscriber in mock mode.
            config: Optional orchestrator configuration.
            accumulator: Optional SegmentAccumulator instance. Created automatically if omitted.
            reconciler: Optional TranscriptReconciler instance. Created automatically if omitted.
            preprocessor: Optional AudioPreprocessor instance. Created automatically if omitted.
            script: Optional speech script used when instantiating default FakeTranscriber.

        Raises:
            ValueError: If session_id is empty or whitespace.
        """
        stripped_id = session_id.strip() if session_id else ""
        if not stripped_id:
            raise ValueError("session_id must be a non-empty string.")

        self._session_id: str = stripped_id
        self._config: OrchestratorConfig = config or OrchestratorConfig()

        # Initialize or bind transcriber adapter
        if transcriber is not None:
            self._transcriber: BaseTranscriber = transcriber
        else:
            self._transcriber = FakeTranscriber(
                session_id=self._session_id,
                script=script,
                config=self._config.transcriber_config,
            )

        # Initialize or bind segment accumulator
        if accumulator is not None:
            self._accumulator: SegmentAccumulator = accumulator
        else:
            self._accumulator = SegmentAccumulator(
                session_id=self._session_id,
                config=self._config.accumulator_config,
            )

        # Initialize or bind transcript reconciler (Days 10-11)
        if reconciler is not None:
            self._reconciler: TranscriptReconciler = reconciler
        else:
            self._reconciler = TranscriptReconciler(
                session_id=self._session_id,
                config=self._config.reconciliation_config,
            )

        # Initialize or bind audio preprocessor (Days 12-13)
        if preprocessor is not None:
            self._preprocessor: AudioPreprocessor = preprocessor
        else:
            self._preprocessor = AudioPreprocessor(
                config=self._config.preprocessor_config,
            )

        # Resilience layer: retries, timeouts, and error normalizer (Days 12-13)
        self._retry_policy: RetryPolicy = RetryPolicy(config=self._config.retry_config)
        self._timeout_policy: TimeoutPolicy = TimeoutPolicy(config=self._config.timeout_config)
        self._resilience_metrics: ResilienceMetrics = ResilienceMetrics()

        # Lifecycle state & concurrency primitives
        self._state: OrchestratorState = OrchestratorState.IDLE
        self._state_lock: asyncio.Lock = asyncio.Lock()

        # Audio ingestion queue (None is sentinel for completion)
        self._audio_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue(
            maxsize=self._config.chunk_buffer_size
        )

        # Event distribution
        self._listeners: Set[EventListener] = set()
        self._subscribers: Set[asyncio.Queue[Optional[TranscriptEvent]]] = set()
        self._events_history: List[TranscriptEvent] = []

        # Background worker task
        self._audio_worker_task: Optional[asyncio.Task[None]] = None

        # Telemetry metrics
        self._metrics: OrchestratorMetrics = OrchestratorMetrics()

    # --------------------------------------------------------------------------
    # Properties
    # --------------------------------------------------------------------------

    @property
    def session_id(self) -> str:
        """Return the active session identifier."""
        return self._session_id

    @property
    def state(self) -> OrchestratorState:
        """Return the current lifecycle state."""
        return self._state

    @property
    def is_running(self) -> bool:
        """True if the orchestrator is running and actively processing."""
        return self._state == OrchestratorState.RUNNING

    @property
    def is_closed(self) -> bool:
        """True if the orchestrator has stopped or encountered an error."""
        return self._state in (OrchestratorState.STOPPED, OrchestratorState.ERROR)

    @property
    def transcriber(self) -> BaseTranscriber:
        """Return the underlying transcriber adapter."""
        return self._transcriber

    @property
    def accumulator(self) -> SegmentAccumulator:
        """Return the bound segment accumulator."""
        return self._accumulator

    @property
    def reconciler(self) -> TranscriptReconciler:
        """Return the stream reconciler instance."""
        return self._reconciler

    @property
    def preprocessor(self) -> AudioPreprocessor:
        """Return the audio preprocessor instance."""
        return self._preprocessor

    @property
    def retry_policy(self) -> RetryPolicy:
        """Return active bounded retry policy."""
        return self._retry_policy

    @property
    def timeout_policy(self) -> TimeoutPolicy:
        """Return active timeout policy."""
        return self._timeout_policy

    @property
    def config(self) -> OrchestratorConfig:
        """Return the active orchestrator configuration."""
        return self._config

    @property
    def metrics(self) -> OrchestratorMetrics:
        """Return current session telemetry metrics."""
        return self._metrics.model_copy()

    @property
    def events_history(self) -> List[TranscriptEvent]:
        """Return a chronological snapshot list of all emitted transcript events."""
        return list(self._events_history)

    # --------------------------------------------------------------------------
    # Lifecycle Management
    # --------------------------------------------------------------------------

    async def start(self) -> None:
        """Start the orchestrator and initialize background processing workers.

        Raises:
            OrchestratorStateError: If already running or starting.
        """
        async with self._state_lock:
            if self._state not in (OrchestratorState.IDLE, OrchestratorState.STOPPED):
                raise OrchestratorStateError(
                    f"Cannot start orchestrator in state '{self._state.value}'. Expected IDLE or STOPPED."
                )
            self._state = OrchestratorState.STARTING

        try:
            # Register event listener directly on adapter to guarantee zero-latency capture
            self._transcriber.add_event_listener(self._on_transcriber_event)

            # Start provider adapter guarded with timeout and retry
            if not self._transcriber.is_listening:
                connect_timeout = self._timeout_policy.config.connect_timeout_seconds

                async def _do_start() -> None:
                    await self._timeout_policy.execute(
                        self._transcriber.start,
                        timeout_seconds=connect_timeout,
                        metrics=self._resilience_metrics,
                        context={"phase": "start", "session_id": self._session_id},
                    )

                await self._retry_policy.execute(
                    _do_start,
                    metrics=self._resilience_metrics,
                    context={"phase": "start", "session_id": self._session_id},
                )

            # Launch background audio worker
            self._audio_worker_task = asyncio.create_task(
                self._run_audio_worker(),
                name=f"orch-audio-worker-{self._session_id}",
            )

            async with self._state_lock:
                self._state = OrchestratorState.RUNNING

            self._sync_resilience_metrics()
            logger.info("TranscriptionOrchestrator '%s' is RUNNING.", self._session_id)
        except Exception as exc:
            async with self._state_lock:
                self._state = OrchestratorState.ERROR
            self._sync_resilience_metrics()
            norm_err = ErrorNormalizer.normalize_exception(exc, {"session_id": self._session_id, "phase": "start"})
            logger.error("Failed to start orchestrator '%s': %s", self._session_id, norm_err)
            raise norm_err from exc

    async def stop(self) -> None:
        """Gracefully conclude the orchestration session, drain pipelines, and close workers."""
        async with self._state_lock:
            if self._state in (OrchestratorState.STOPPED, OrchestratorState.ERROR):
                return
            self._state = OrchestratorState.STOPPING

        try:
            # Signal audio worker to finish if still alive
            if self._audio_worker_task and not self._audio_worker_task.done():
                try:
                    self._audio_queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass
                try:
                    await asyncio.wait_for(self._audio_worker_task, timeout=2.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    self._audio_worker_task.cancel()

            # Stop provider transcriber
            if not self._transcriber.is_closed:
                await self._transcriber.stop()

            # Remove event listener
            self._transcriber.remove_event_listener(self._on_transcriber_event)

        finally:
            async with self._state_lock:
                self._state = OrchestratorState.STOPPED

            # Notify all active stream subscribers of stream conclusion
            for queue in list(self._subscribers):
                try:
                    queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass

            self._sync_resilience_metrics()
            logger.info("TranscriptionOrchestrator '%s' has STOPPED.", self._session_id)

    async def __aenter__(self) -> TranscriptionOrchestrator:
        """Asynchronous context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Asynchronous context manager exit."""
        await self.stop()

    # --------------------------------------------------------------------------
    # Audio Ingestion
    # --------------------------------------------------------------------------

    async def push_audio(
        self,
        chunk: bytes,
        sample_rate: Optional[int] = None,
        channels: Optional[int] = None,
    ) -> None:
        """Ingest a chunk of raw audio bytes into the transcription pipeline.

        Applies audio preprocessing (resampling & normalization) if enabled,
        auto-starts if idle, and places chunk into the asynchronous ingestion queue.

        Args:
            chunk: Audio bytes.
            sample_rate: Optional input sample rate in Hz (e.g. 48000, 44100, 8000).
            channels: Optional input channel count (1 or 2).

        Raises:
            OrchestratorStateError: If called when orchestrator is not running and cannot auto-start.
            TranscriberAudioError: If audio chunk is empty or not bytes-like.
        """
        if not isinstance(chunk, (bytes, bytearray)):
            raise TranscriberAudioError("Audio chunk must be an instance of bytes or bytearray.")

        if len(chunk) == 0:
            raise TranscriberAudioError("Audio chunk cannot be empty.")

        # Audio Preprocessing step (Days 12-13)
        if self._config.enable_preprocessing or self._config.preprocessor_config is not None:
            try:
                chunk = self._preprocessor.process_chunk(
                    chunk=chunk,
                    in_sample_rate=sample_rate,
                    in_channels=channels,
                )
                self._metrics.chunks_preprocessed += 1
            except Exception as prep_exc:
                norm_audio_err = ErrorNormalizer.normalize_exception(prep_exc, {"action": "preprocessing"})
                raise norm_audio_err from prep_exc

        # Auto-start if configured and currently idle
        if self._state == OrchestratorState.IDLE and self._config.auto_start:
            await self.start()

        if self._state != OrchestratorState.RUNNING:
            raise OrchestratorStateError(
                f"Cannot push audio in state '{self._state.value}'. Orchestrator must be in RUNNING state."
            )

        # Update telemetry metrics
        chunk_len = len(chunk)
        self._metrics.chunks_ingested += 1
        self._metrics.bytes_ingested += chunk_len

        # Estimate chunk duration from transcriber audio config
        audio_config = getattr(self._transcriber.config, "audio_config", None)
        if audio_config and hasattr(audio_config, "bytes_to_duration_ms"):
            self._metrics.audio_duration_ms += audio_config.bytes_to_duration_ms(chunk_len)

        # Put audio into async buffer
        await self._audio_queue.put(bytes(chunk))

    async def finish_audio(self) -> None:
        """Signal that no more audio will be sent, flushing pending audio and awaiting events.

        Raises:
            OrchestratorStateError: If called when not in RUNNING state.
        """
        if self._state != OrchestratorState.RUNNING:
            raise OrchestratorStateError(
                f"Cannot finish audio in state '{self._state.value}'. Expected RUNNING."
            )

        # Signal completion to audio worker via sentinel
        await self._audio_queue.put(None)

        # Wait for audio worker to complete pushing and call finish_audio on adapter
        if self._audio_worker_task:
            await self._audio_worker_task

    # --------------------------------------------------------------------------
    # Event Streaming & Listeners
    # --------------------------------------------------------------------------

    def add_event_listener(self, listener: EventListener) -> None:
        """Register a synchronous or asynchronous callback for emitted TranscriptEvents."""
        self._listeners.add(listener)

    def remove_event_listener(self, listener: EventListener) -> None:
        """Unregister a previously attached event callback."""
        self._listeners.discard(listener)

    async def stream(self, replay_existing: bool = False) -> AsyncIterator[TranscriptEvent]:
        """Asynchronously stream TranscriptEvents as they are emitted by the orchestrator.

        Args:
            replay_existing: If True, yields previously recorded events from this session
                prior to streaming subsequent live events.

        Yields:
            TranscriptEvent instances until the session concludes.
        """
        queue: asyncio.Queue[Optional[TranscriptEvent]] = asyncio.Queue()
        if replay_existing:
            for past_event in list(self._events_history):
                await queue.put(past_event)

        self._subscribers.add(queue)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            self._subscribers.discard(queue)

    async def process_audio(
        self,
        audio_data: bytes,
        sample_rate: Optional[int] = None,
        channels: Optional[int] = None,
    ) -> List[TranscriptEvent]:
        """Process a complete audio buffer end-to-end and return all resulting events.

        Slices audio into chunks matching AudioConfig, streams them through the pipeline,
        finalizes the audio stream, stops the orchestrator, and returns the event list.

        Args:
            audio_data: Full raw audio byte buffer.
            sample_rate: Optional source sample rate.
            channels: Optional source channel count.

        Returns:
            Chronological list of all emitted TranscriptEvent objects.
        """
        if not isinstance(audio_data, (bytes, bytearray)):
            raise TranscriberAudioError("Audio data must be bytes or bytearray.")

        if self._state != OrchestratorState.RUNNING:
            await self.start()

        audio_config = getattr(self._transcriber.config, "audio_config", None)
        chunk_size = getattr(audio_config, "chunk_size_bytes", 3200)

        for offset in range(0, len(audio_data), chunk_size):
            chunk = audio_data[offset : offset + chunk_size]
            if chunk:
                await self.push_audio(chunk, sample_rate=sample_rate, channels=channels)

        await self.finish_audio()
        await self.stop()
        return self.events_history

    # --------------------------------------------------------------------------
    # Segment Accumulator Projections
    # --------------------------------------------------------------------------

    def get_final_text(self) -> str:
        """Return concatenated string of all committed final speech segments."""
        return self._accumulator.get_final_text()

    def get_interim_text(self) -> str:
        """Return active speculative interim hypothesis string."""
        return self._accumulator.get_interim_text()

    def get_full_text(self) -> str:
        """Return combined real-time transcript (committed final + active interim)."""
        return self._accumulator.get_full_text()

    def get_snapshot(self) -> AccumulatedTranscript:
        """Return an immutable snapshot of current accumulated transcript state."""
        return self._accumulator.get_snapshot()

    # --------------------------------------------------------------------------
    # Internal Handlers & Workers
    # --------------------------------------------------------------------------

    def _sync_resilience_metrics(self) -> None:
        """Synchronize resilience metrics into public orchestrator metrics."""
        self._metrics.retries_attempted = self._resilience_metrics.retries_attempted
        self._metrics.retries_succeeded = self._resilience_metrics.retries_succeeded
        self._metrics.retries_exhausted = self._resilience_metrics.retries_exhausted
        self._metrics.timeouts_encountered = self._resilience_metrics.timeouts_encountered
        self._metrics.errors_normalized = self._resilience_metrics.errors_normalized

    def _on_transcriber_event(self, event: TranscriptEvent) -> None:
        """Synchronously receive, reconcile, and dispatch events emitted by the transcriber."""
        # 1. Reconcile, order, and deduplicate event if enabled (Days 10-11)
        if self._config.enable_reconciliation:
            reconciled_event = self._reconciler.reconcile_event(event)

            # Sync reconciliation telemetry into orchestrator metrics
            rec_metrics = self._reconciler.metrics
            self._metrics.duplicates_suppressed = rec_metrics.duplicates_suppressed
            self._metrics.out_of_order_resolved = rec_metrics.out_of_order_resolved
            self._metrics.stale_interims_suppressed = rec_metrics.stale_interims_count
            self._metrics.repeated_interims_suppressed = rec_metrics.repeated_interims_count

            # If event was filtered (e.g. duplicate or stale interim), drop it cleanly
            if reconciled_event is None:
                return
            event = reconciled_event

        # 2. Feed into accumulator
        try:
            self._accumulator.add_event(event)
        except Exception as acc_exc:
            logger.warning("SegmentAccumulator error in session '%s': %s", self._session_id, acc_exc)

        # 3. Record in chronological history
        self._events_history.append(event)
        self._metrics.events_emitted += 1

        # 4. Update telemetry metrics
        if event.event_type == TranscriptEventType.SPEECH_STARTED:
            self._metrics.speech_turns_detected += 1
        elif event.event_type == TranscriptEventType.FINAL_TRANSCRIPT:
            self._metrics.final_segments_count += 1

        # 5. Broadcast to async stream subscribers
        for sub_queue in list(self._subscribers):
            try:
                sub_queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Subscriber event queue full for session '%s'", self._session_id)

        # 6. Broadcast to callback listeners
        for listener in list(self._listeners):
            try:
                res = listener(event)
                if inspect.isawaitable(res):
                    asyncio.create_task(res)
            except Exception as cb_exc:
                logger.warning("Listener callback error in session '%s': %s", self._session_id, cb_exc)

    async def _run_audio_worker(self) -> None:
        """Background worker consuming audio chunks from queue and piping to transcriber."""
        chunk_timeout = self._timeout_policy.config.chunk_timeout_seconds
        finish_timeout = self._timeout_policy.config.operation_timeout_seconds

        try:
            while True:
                chunk = await self._audio_queue.get()
                if chunk is None:
                    # Sentinel reached: signal completion to transcriber guarded by timeout & retries
                    self._audio_queue.task_done()
                    if self._transcriber.is_listening:
                        try:
                            async def _do_finish():
                                await self._timeout_policy.execute(
                                    self._transcriber.finish_audio,
                                    timeout_seconds=finish_timeout,
                                    metrics=self._resilience_metrics,
                                    context={"action": "finish_audio", "session_id": self._session_id},
                                )

                            await self._retry_policy.execute(
                                _do_finish,
                                metrics=self._resilience_metrics,
                                context={"action": "finish_audio", "session_id": self._session_id},
                            )
                        except Exception as finish_err:
                            self._handle_provider_worker_error(finish_err, "finish_audio")
                    break

                try:
                    if self._transcriber.is_listening:
                        async def _do_push():
                            await self._timeout_policy.execute(
                                self._transcriber.push_audio,
                                timeout_seconds=chunk_timeout,
                                chunk=chunk,
                                metrics=self._resilience_metrics,
                                context={"action": "push_audio", "chunk_len": len(chunk)},
                            )

                        await self._retry_policy.execute(
                            _do_push,
                            metrics=self._resilience_metrics,
                            context={"action": "push_audio", "chunk_len": len(chunk)},
                        )
                except Exception as push_err:
                    self._handle_provider_worker_error(push_err, "push_audio")
                finally:
                    self._audio_queue.task_done()
                    self._sync_resilience_metrics()

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Error in orchestrator audio worker for session '%s': %s", self._session_id, exc)
            self._state = OrchestratorState.ERROR
            self._sync_resilience_metrics()
            raise

    def _handle_provider_worker_error(self, exc: Exception, phase: str) -> None:
        """Normalize raw worker exception and emit as standardized TranscriptEvent(ERROR)."""
        self._sync_resilience_metrics()
        error_event = ErrorNormalizer.to_error_event(
            session_id=self._session_id,
            exc=exc,
            context={"phase": phase, "session_id": self._session_id},
        )
        self._on_transcriber_event(error_event)
        self._state = OrchestratorState.ERROR
