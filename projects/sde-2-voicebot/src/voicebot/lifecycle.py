"""Audio capture lifecycle controls for SDE Team 2, Week 2 (Days 10-11).

This module defines the state machine and controller for managing the audio capture lifecycle:
- LifecycleState: Enum of lifecycle states (INITIALIZED, RECORDING, PAUSED, STOPPED, ERROR).
- AudioLifecycleController: State machine enforcing valid transitions (start, pause, resume, stop),
  integrating with AudioDeviceAdapter, and guarding against permission denials and illegal transitions.
"""

from enum import Enum
import threading
import time
from typing import Any, Iterator, Optional
import uuid

from voicebot.device import AudioDeviceAdapter, PermissionState
from voicebot.schemas import AudioChunk, AudioError


class LifecycleState(str, Enum):
    """Represents the operational state of the audio capture pipeline."""

    INITIALIZED = "INITIALIZED"    # Controller configured with device adapter, ready to start
    RECORDING = "RECORDING"        # Actively streaming and processing audio frames
    PAUSED = "PAUSED"              # Audio capture paused; frames suppressed/muted
    STOPPED = "STOPPED"            # Capture session terminated; resources released
    RECONNECTING = "RECONNECTING"  # Recovering from mid-stream device loss
    CANCELLED = "CANCELLED"        # Explicitly cancelled; buffer cleared and capture halted
    ERROR = "ERROR"                # Fatal error state (unrecoverable loss or revoked permission)


class AudioLifecycleController:
    """Manages the audio capture lifecycle with state validation and device coordination.

    Guarantees:
        - Valid state transitions: start -> pause -> resume -> stop / cancel.
        - Protection against illegal state transitions (e.g. pause before start).
        - Permission enforcement before audio capture begins.
        - Automatic mid-stream device loss detection and fallback reconnection without crash.
        - Explicit cancellation halting capture, releasing bounded buffer, and flushing processor.
        - Clean resource release and idempotency on stop and cancel.
    """

    def __init__(
        self,
        adapter: AudioDeviceAdapter,
        max_reconnect_attempts: int = 3,
        reconnect_delay_seconds: float = 0.0,
        auto_reconnect: bool = True,
    ):
        """Initialize the audio lifecycle controller.

        Args:
            adapter (AudioDeviceAdapter): Device adapter providing hardware/mock streams.
            max_reconnect_attempts (int): Maximum recovery attempts upon device loss (default: 3).
            reconnect_delay_seconds (float): Delay in seconds between reconnect attempts (default: 0.0s).
            auto_reconnect (bool): Whether to automatically recover from device loss (default: True).

        Raises:
            AudioError: If adapter is not an AudioDeviceAdapter instance or parameters are invalid.
        """
        if not isinstance(adapter, AudioDeviceAdapter):
            raise AudioError("adapter must be an instance of AudioDeviceAdapter.")
        if isinstance(max_reconnect_attempts, bool) or not isinstance(max_reconnect_attempts, int) or max_reconnect_attempts < 0:
            raise AudioError("max_reconnect_attempts must be a non-negative integer.")
        if isinstance(reconnect_delay_seconds, bool) or not isinstance(reconnect_delay_seconds, (int, float)) or reconnect_delay_seconds < 0.0:
            raise AudioError("reconnect_delay_seconds must be a non-negative number.")
        if not isinstance(auto_reconnect, bool):
            raise AudioError("auto_reconnect must be a boolean.")

        self._adapter = adapter
        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_delay_seconds = float(reconnect_delay_seconds)
        self._auto_reconnect = auto_reconnect

        self._lock = threading.RLock()
        self._state = LifecycleState.INITIALIZED
        self._session_id: str | None = None
        self._chunks_emitted: int = 0
        self._chunks_suppressed: int = 0

        # Recovery & cancellation telemetry
        self._reconnect_count: int = 0
        self._successful_reconnects: int = 0
        self._last_recovery_device: str | None = None
        self._is_cancelled: bool = False

    @property
    def state(self) -> LifecycleState:
        """Return the current lifecycle state."""
        return self._state

    @property
    def adapter(self) -> AudioDeviceAdapter:
        """Return the attached audio device adapter."""
        return self._adapter

    @property
    def is_active(self) -> bool:
        """Return True if the controller is in RECORDING, PAUSED, or RECONNECTING state."""
        with self._lock:
            return self._state in (
                LifecycleState.RECORDING,
                LifecycleState.PAUSED,
                LifecycleState.RECONNECTING,
            )

    @property
    def is_cancelled(self) -> bool:
        """Return True if the session was explicitly cancelled."""
        with self._lock:
            return self._is_cancelled

    @property
    def reconnect_count(self) -> int:
        """Return the total number of reconnection attempts."""
        with self._lock:
            return self._reconnect_count

    @property
    def successful_reconnects(self) -> int:
        """Return the number of successful device recovery events."""
        with self._lock:
            return self._successful_reconnects

    @property
    def last_recovery_device(self) -> str | None:
        """Return the device ID of the most recent recovery device."""
        with self._lock:
            return self._last_recovery_device

    @property
    def is_recording(self) -> bool:
        """Return True only if the controller is actively RECORDING."""
        return self._state == LifecycleState.RECORDING

    @property
    def is_paused(self) -> bool:
        """Return True only if the controller is currently PAUSED."""
        return self._state == LifecycleState.PAUSED

    @property
    def session_id(self) -> str | None:
        """Return the current capture session UUID, or None if not active."""
        return self._session_id

    @property
    def chunks_emitted(self) -> int:
        """Return the total number of chunks emitted to downstream consumers."""
        return self._chunks_emitted

    @property
    def chunks_suppressed(self) -> int:
        """Return the total number of chunks suppressed while in PAUSED state."""
        return self._chunks_suppressed

    def start(self) -> None:
        """Start audio capture session.

        Transitions state from INITIALIZED or STOPPED to RECORDING.

        Raises:
            AudioError: If microphone permission is DENIED or UNAVAILABLE, or if
                        the controller is already RECORDING, PAUSED, or in ERROR.
        """
        # Validate device permission before capture begins
        perm = self._adapter.get_permission_state()
        if perm == PermissionState.DENIED:
            self._state = LifecycleState.ERROR
            raise AudioError("Microphone permission denied. Cannot start audio capture.")
        if perm == PermissionState.UNAVAILABLE:
            self._state = LifecycleState.ERROR
            raise AudioError("Audio device is unavailable. Cannot start audio capture.")
        if perm == PermissionState.PROMPT:
            perm = self._adapter.request_permission()
            if perm != PermissionState.GRANTED:
                self._state = LifecycleState.ERROR
                raise AudioError(f"Microphone permission not granted (state: {perm.value}).")

        # Validate lifecycle state transition
        if self._state == LifecycleState.RECORDING:
            raise AudioError("Audio capture is already recording.")
        if self._state == LifecycleState.PAUSED:
            raise AudioError("Audio capture is paused. Call resume() instead of start().")
        if self._state == LifecycleState.ERROR:
            raise AudioError("Cannot start audio capture in ERROR state. Reset controller first.")

        # Valid transition from INITIALIZED or STOPPED
        with self._lock:
            self._session_id = str(uuid.uuid4())
            self._chunks_emitted = 0
            self._chunks_suppressed = 0
            self._is_cancelled = False
            self._state = LifecycleState.RECORDING

    def pause(self) -> None:
        """Pause active audio capture session.

        Transitions state from RECORDING to PAUSED.

        Raises:
            AudioError: If controller is not in RECORDING state.
        """
        with self._lock:
            if self._state == LifecycleState.PAUSED:
                raise AudioError("Audio capture is already paused.")
            if self._state != LifecycleState.RECORDING:
                raise AudioError(
                    f"Cannot pause audio capture: controller is not in RECORDING state (current: {self._state.value})."
                )

            self._state = LifecycleState.PAUSED

    def resume(self) -> None:
        """Resume paused audio capture session.

        Transitions state from PAUSED to RECORDING.

        Raises:
            AudioError: If controller is not in PAUSED state.
        """
        with self._lock:
            if self._state == LifecycleState.RECORDING:
                raise AudioError("Audio capture is already recording.")
            if self._state != LifecycleState.PAUSED:
                raise AudioError(
                    f"Cannot resume audio capture: controller is not in PAUSED state (current: {self._state.value})."
                )

            self._state = LifecycleState.RECORDING

    def stop(self) -> None:
        """Stop audio capture session and release resources.

        Transitions state to STOPPED from any state. Safe and idempotent.
        """
        with self._lock:
            if self._state == LifecycleState.STOPPED:
                return

            self._state = LifecycleState.STOPPED
            self._session_id = None

    def cancel(
        self,
        buffer: Optional[Any] = None,
        processor: Optional[Any] = None,
    ) -> None:
        """Cancel active audio capture session and release associated resources.

        Transitions state to CANCELLED, sets is_cancelled=True, immediately stops capture,
        flushes/clears any attached BoundedAudioBuffer, and flushes any active speech
        turns in SpeechEventProcessor.

        Args:
            buffer: Optional BoundedAudioBuffer instance to clear and release.
            processor: Optional SpeechEventProcessor instance to flush.
        """
        with self._lock:
            if self._state == LifecycleState.CANCELLED:
                return

            self._state = LifecycleState.CANCELLED
            self._is_cancelled = True

            # Release bounded buffer memory
            if buffer is not None and hasattr(buffer, "clear"):
                buffer.clear()

            # Cleanly flush active speech turn
            if processor is not None and hasattr(processor, "flush"):
                processor.flush()

    def reset(self) -> None:
        """Reset the controller to its initial state."""
        with self._lock:
            self._state = LifecycleState.INITIALIZED
            self._session_id = None
            self._chunks_emitted = 0
            self._chunks_suppressed = 0
            self._is_cancelled = False
            self._reconnect_count = 0
            self._successful_reconnects = 0
            self._last_recovery_device = None

    def reconnect(self, fallback_device_id: Optional[str] = None) -> bool:
        """Attempt to recover from device loss by reconnecting or switching to a fallback device.

        Args:
            fallback_device_id: Optional specific device ID to select as recovery target.

        Returns:
            bool: True if device was successfully connected with GRANTED permission; False otherwise.
        """
        with self._lock:
            self._reconnect_count += 1
            try:
                devices = self._adapter.list_devices()
            except Exception:
                return False

            if not devices:
                return False

            target_device = None
            if fallback_device_id:
                for d in devices:
                    if d.device_id == fallback_device_id:
                        target_device = d
                        break

            if target_device is None:
                try:
                    target_device = self._adapter.get_default_device()
                except Exception:
                    target_device = devices[0]

            try:
                self._adapter.select_device(target_device.device_id)
            except Exception:
                return False

            perm = self._adapter.get_permission_state()
            if perm in (PermissionState.PROMPT, PermissionState.UNAVAILABLE):
                perm = self._adapter.request_permission()

            if perm == PermissionState.GRANTED:
                self._successful_reconnects += 1
                self._last_recovery_device = target_device.device_id
                return True

            return False

    def capture_stream(
        self,
        chunk_count: int = 5,
        frames_per_chunk: int = 4,
        raw_data: bytes | None = None,
    ) -> Iterator[AudioChunk]:
        """Capture and stream audio chunks according to active lifecycle state.

        - Yields AudioChunk instances when in RECORDING state.
        - Suppresses chunks when in PAUSED state.
        - Stops cleanly when stop() or cancel() is called.
        - Automatically recovers from mid-stream device loss if auto_reconnect=True.
        - Transitions to ERROR and raises AudioError if permission is revoked or
          reconnection attempts fail.

        Yields:
            AudioChunk: Audio chunks emitted while in RECORDING state.

        Raises:
            AudioError: If controller is not started, or device failure occurs mid-stream.
        """
        if not self.is_active:
            raise AudioError(
                f"Cannot capture stream: controller is in {self._state.value} state (must be RECORDING or PAUSED)."
            )

        current_perm = self._adapter.get_permission_state()
        if current_perm == PermissionState.DENIED:
            self._state = LifecycleState.ERROR
            raise AudioError(f"Audio capture aborted: device became {current_perm.value}.")

        if current_perm == PermissionState.UNAVAILABLE:
            if not self._auto_reconnect or not self.reconnect():
                self._state = LifecycleState.ERROR
                raise AudioError(f"Audio capture aborted: device became {current_perm.value}.")

        try:
            stream = self._adapter.create_stream(
                chunk_count=chunk_count,
                frames_per_chunk=frames_per_chunk,
                raw_data=raw_data,
            )
        except AudioError as err:
            if self._auto_reconnect and self.reconnect():
                stream = self._adapter.create_stream(
                    chunk_count=chunk_count,
                    frames_per_chunk=frames_per_chunk,
                    raw_data=raw_data,
                )
            else:
                self._state = LifecycleState.ERROR
                raise AudioError(f"Audio capture aborted: {err}") from err

        while True:
            if self._state in (LifecycleState.STOPPED, LifecycleState.CANCELLED):
                break

            current_perm = self._adapter.get_permission_state()
            if current_perm == PermissionState.DENIED:
                self._state = LifecycleState.ERROR
                raise AudioError(f"Audio capture aborted: device became {current_perm.value}.")

            if current_perm == PermissionState.UNAVAILABLE:
                if self._auto_reconnect and self._reconnect_count < self._max_reconnect_attempts:
                    prev_state = self._state
                    self._state = LifecycleState.RECONNECTING
                    reconnected = False
                    for _ in range(self._max_reconnect_attempts):
                        if self._reconnect_delay_seconds > 0.0:
                            time.sleep(self._reconnect_delay_seconds)
                        if self.reconnect():
                            reconnected = True
                            break
                    if reconnected:
                        self._state = prev_state
                        remaining = max(0, chunk_count - self._chunks_emitted)
                        if remaining == 0 and chunk_count > 0:
                            break
                        stream = self._adapter.create_stream(
                            chunk_count=remaining,
                            frames_per_chunk=frames_per_chunk,
                            raw_data=raw_data,
                        )
                    else:
                        self._state = LifecycleState.ERROR
                        raise AudioError("Audio capture aborted: device became UNAVAILABLE.")
                else:
                    self._state = LifecycleState.ERROR
                    raise AudioError(f"Audio capture aborted: device became {current_perm.value}.")

            try:
                chunk = next(stream)
            except StopIteration:
                break
            except AudioError as err:
                if self._auto_reconnect and self._reconnect_count < self._max_reconnect_attempts:
                    prev_state = self._state
                    self._state = LifecycleState.RECONNECTING
                    reconnected = False
                    for _ in range(self._max_reconnect_attempts):
                        if self._reconnect_delay_seconds > 0.0:
                            time.sleep(self._reconnect_delay_seconds)
                        if self.reconnect():
                            reconnected = True
                            break
                    if reconnected:
                        self._state = prev_state
                        remaining = max(0, chunk_count - self._chunks_emitted)
                        if remaining == 0 and chunk_count > 0:
                            break
                        stream = self._adapter.create_stream(
                            chunk_count=remaining,
                            frames_per_chunk=frames_per_chunk,
                            raw_data=raw_data,
                        )
                        continue
                    else:
                        self._state = LifecycleState.ERROR
                        raise AudioError(f"Audio capture aborted: {err}") from err
                else:
                    self._state = LifecycleState.ERROR
                    raise AudioError(f"Audio capture aborted: {err}") from err

            if self._state in (LifecycleState.STOPPED, LifecycleState.CANCELLED):
                break

            if self._state == LifecycleState.PAUSED:
                self._chunks_suppressed += 1
                continue

            if self._state == LifecycleState.RECORDING:
                self._chunks_emitted += 1
                yield chunk
