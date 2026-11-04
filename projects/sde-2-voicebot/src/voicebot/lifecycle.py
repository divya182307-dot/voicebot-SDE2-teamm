"""Audio capture lifecycle controls for SDE Team 2, Week 2 (Days 10-11).

This module defines the state machine and controller for managing the audio capture lifecycle:
- LifecycleState: Enum of lifecycle states (INITIALIZED, RECORDING, PAUSED, STOPPED, ERROR).
- AudioLifecycleController: State machine enforcing valid transitions (start, pause, resume, stop),
  integrating with AudioDeviceAdapter, and guarding against permission denials and illegal transitions.
"""

from enum import Enum
from typing import Iterator
import uuid

from voicebot.device import AudioDeviceAdapter, PermissionState
from voicebot.schemas import AudioChunk, AudioError


class LifecycleState(str, Enum):
    """Represents the operational state of the audio capture pipeline."""

    INITIALIZED = "INITIALIZED"  # Controller configured with device adapter, ready to start
    RECORDING = "RECORDING"      # Actively streaming and processing audio frames
    PAUSED = "PAUSED"            # Audio capture paused; frames suppressed/muted
    STOPPED = "STOPPED"          # Capture session terminated; resources released
    ERROR = "ERROR"              # Fatal error state (device loss or revoked permission)


class AudioLifecycleController:
    """Manages the audio capture lifecycle with state validation and device coordination.

    Guarantees:
        - Valid state transitions: start -> pause -> resume -> stop.
        - Protection against illegal state transitions (e.g. pause before start).
        - Permission enforcement before audio capture begins.
        - Graceful error handling on device disconnection or permission revocation.
        - Clean resource release and idempotency on stop.
    """

    def __init__(self, adapter: AudioDeviceAdapter):
        """Initialize the audio lifecycle controller.

        Args:
            adapter (AudioDeviceAdapter): Device adapter providing hardware/mock streams.

        Raises:
            AudioError: If adapter is not an AudioDeviceAdapter instance.
        """
        if not isinstance(adapter, AudioDeviceAdapter):
            raise AudioError("adapter must be an instance of AudioDeviceAdapter.")

        self._adapter = adapter
        self._state = LifecycleState.INITIALIZED
        self._session_id: str | None = None
        self._chunks_emitted: int = 0
        self._chunks_suppressed: int = 0

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
        """Return True if the controller is in RECORDING or PAUSED state."""
        return self._state in (LifecycleState.RECORDING, LifecycleState.PAUSED)

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
        self._session_id = str(uuid.uuid4())
        self._chunks_emitted = 0
        self._chunks_suppressed = 0
        self._state = LifecycleState.RECORDING

    def pause(self) -> None:
        """Pause active audio capture session.

        Transitions state from RECORDING to PAUSED.

        Raises:
            AudioError: If controller is not in RECORDING state.
        """
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
        if self._state == LifecycleState.STOPPED:
            return

        self._state = LifecycleState.STOPPED
        self._session_id = None

    def reset(self) -> None:
        """Reset the controller to its initial state."""
        self._state = LifecycleState.INITIALIZED
        self._session_id = None
        self._chunks_emitted = 0
        self._chunks_suppressed = 0

    def capture_stream(
        self,
        chunk_count: int = 5,
        frames_per_chunk: int = 4,
        raw_data: bytes | None = None,
    ) -> Iterator[AudioChunk]:
        """Capture and stream audio chunks according to active lifecycle state.

        - Yields AudioChunk instances when in RECORDING state.
        - Suppresses chunks when in PAUSED state.
        - Stops cleanly when stop() is called.
        - Transitions to ERROR and raises AudioError if device permission is revoked
          or device becomes unavailable during streaming.

        Yields:
            AudioChunk: Audio chunks emitted while in RECORDING state.

        Raises:
            AudioError: If controller is not started, or device failure occurs mid-stream.
        """
        # Validate active state
        if not self.is_active:
            raise AudioError(
                f"Cannot capture stream: controller is in {self._state.value} state (must be RECORDING or PAUSED)."
            )

        # Validate permission before acquiring stream
        current_perm = self._adapter.get_permission_state()
        if current_perm in (PermissionState.DENIED, PermissionState.UNAVAILABLE):
            self._state = LifecycleState.ERROR
            raise AudioError(f"Audio capture aborted: device became {current_perm.value}.")

        try:
            stream = self._adapter.create_stream(
                chunk_count=chunk_count,
                frames_per_chunk=frames_per_chunk,
                raw_data=raw_data,
            )
        except AudioError as err:
            self._state = LifecycleState.ERROR
            raise AudioError(f"Audio capture aborted: {err}") from err

        for chunk in stream:
            # Check for device disconnection or revoked permission mid-stream
            current_perm = self._adapter.get_permission_state()
            if current_perm in (PermissionState.DENIED, PermissionState.UNAVAILABLE):
                self._state = LifecycleState.ERROR
                raise AudioError(f"Audio capture aborted: device became {current_perm.value}.")

            # Stop immediately terminates stream
            if self._state == LifecycleState.STOPPED:
                break

            # Pause suppresses chunk processing/emission
            if self._state == LifecycleState.PAUSED:
                self._chunks_suppressed += 1
                continue

            # Recording state emits chunk
            if self._state == LifecycleState.RECORDING:
                self._chunks_emitted += 1
                yield chunk
