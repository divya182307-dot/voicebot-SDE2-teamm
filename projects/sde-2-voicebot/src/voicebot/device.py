"""Audio device adapter and permission management for SDE Team 2, Week 2 (Day 8-9).

This module defines the hardware abstraction layer for audio devices and permissions:
- PermissionState: Security enum representing microphone permission states.
- AudioDevice: Immutable description of an audio capture device.
- AudioDeviceAdapter: Abstract base class defining the hardware interface.
- MockAudioDeviceAdapter: Deterministic mock implementation for offline testing.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Iterator

from voicebot.mock_microphone import MockMicrophone
from voicebot.schemas import AudioChunk, AudioError, AudioFormat


class PermissionState(str, Enum):
    """Represents the authorization state for accessing audio capture hardware.

    Aligns with PRD Section 19 (Privacy) and Non-Goals (NG3: Never capture audio without
    explicit user consent).
    """

    PROMPT = "PROMPT"              # Permission has not yet been requested
    GRANTED = "GRANTED"            # User granted microphone access
    DENIED = "DENIED"              # User/system denied access (capture prohibited)
    UNAVAILABLE = "UNAVAILABLE"    # Device physically disconnected or missing


@dataclass(frozen=True)
class AudioDevice:
    """Immutable representation of an audio input device.

    Fields:
        device_id: Unique string identifier for the device (e.g. 'mock-default-mic').
        name: Human-readable display label.
        channels: Channel count (1 for mono, 2 for stereo).
        default_sample_rate: Native sampling rate in Hz (e.g. 16000).
        is_default: Whether this is the primary system default device.
        sample_width: Bytes per sample per channel (default: 2 bytes = 16-bit PCM).
    """

    device_id: str
    name: str
    channels: int
    default_sample_rate: int
    is_default: bool = False
    sample_width: int = 2

    def __post_init__(self):
        if not isinstance(self.device_id, str) or not self.device_id.strip():
            raise AudioError("device_id must be a non-empty string.")

        if not isinstance(self.name, str) or not self.name.strip():
            raise AudioError("name must be a non-empty string.")

        if isinstance(self.channels, bool) or not isinstance(self.channels, int):
            raise AudioError("channels must be an integer.")
        if self.channels not in (1, 2):
            raise AudioError("channels must be 1 (mono) or 2 (stereo).")

        if isinstance(self.default_sample_rate, bool) or not isinstance(self.default_sample_rate, int):
            raise AudioError("default_sample_rate must be an integer in Hz.")
        if self.default_sample_rate <= 0:
            raise AudioError("default_sample_rate must be greater than 0 Hz.")

        if not isinstance(self.is_default, bool):
            raise AudioError("is_default must be a boolean.")

        if isinstance(self.sample_width, bool) or not isinstance(self.sample_width, int):
            raise AudioError("sample_width must be an integer in bytes.")
        if self.sample_width not in (1, 2, 3, 4):
            raise AudioError("sample_width must be 1, 2, 3, or 4 bytes.")

    @property
    def default_format(self) -> AudioFormat:
        """Create an AudioFormat instance reflecting this device's configuration."""
        return AudioFormat(
            sample_rate=self.default_sample_rate,
            channels=self.channels,
            sample_width=self.sample_width,
        )


class AudioDeviceAdapter(ABC):
    """Abstract interface for audio capture devices and permission control."""

    @abstractmethod
    def list_devices(self) -> list[AudioDevice]:
        """List all available audio input devices."""

    @abstractmethod
    def get_default_device(self) -> AudioDevice:
        """Retrieve the primary default audio input device."""

    @abstractmethod
    def get_selected_device(self) -> AudioDevice:
        """Retrieve the currently selected audio input device."""

    @abstractmethod
    def select_device(self, device_id: str) -> AudioDevice:
        """Select an audio device by its unique device_id."""

    @abstractmethod
    def request_permission(self) -> PermissionState:
        """Request microphone access permission from the user/system."""

    @abstractmethod
    def get_permission_state(self) -> PermissionState:
        """Get the current permission state."""

    @abstractmethod
    def create_stream(
        self,
        chunk_count: int = 5,
        frames_per_chunk: int = 4,
        raw_data: bytes | None = None,
    ) -> Iterator[AudioChunk]:
        """Open an audio stream and yield AudioChunk instances.

        Raises:
            AudioError: If permission is DENIED, PROMPT, or device is UNAVAILABLE.
        """


class MockAudioDeviceAdapter(AudioDeviceAdapter):
    """Deterministic mock adapter for audio devices and permissions.

    Provides configurable device lists and controllable permission transitions
    for reproducible offline unit testing without real audio hardware.
    """

    def __init__(
        self,
        devices: list[AudioDevice] | None = None,
        initial_permission: PermissionState = PermissionState.PROMPT,
        permission_response: PermissionState = PermissionState.GRANTED,
    ):
        """Initialize the mock audio device adapter.

        Args:
            devices: Optional list of simulated AudioDevice instances. Defaults to
                     standard built-in mic and stereo headset mocks.
            initial_permission: Initial state of permission (default: PROMPT).
            permission_response: What request_permission() will return (default: GRANTED).
        """
        if not isinstance(initial_permission, PermissionState):
            raise AudioError("initial_permission must be a PermissionState enum value.")
        if not isinstance(permission_response, PermissionState):
            raise AudioError("permission_response must be a PermissionState enum value.")

        if devices is None:
            self._devices = [
                AudioDevice(
                    device_id="mock-default-mic",
                    name="Mock Built-in Microphone",
                    channels=1,
                    default_sample_rate=16000,
                    is_default=True,
                    sample_width=2,
                ),
                AudioDevice(
                    device_id="mock-usb-headset",
                    name="Mock USB Stereo Headset",
                    channels=2,
                    default_sample_rate=48000,
                    is_default=False,
                    sample_width=2,
                ),
            ]
        else:
            if not isinstance(devices, list):
                raise AudioError("devices must be a list of AudioDevice instances.")
            for dev in devices:
                if not isinstance(dev, AudioDevice):
                    raise AudioError("All items in devices must be AudioDevice instances.")
            self._devices = list(devices)

        self._permission_state = initial_permission
        self._permission_response = permission_response

        # Default selected device is the default device (or first available)
        self._selected_device: AudioDevice | None = None
        if self._devices:
            self._selected_device = self._find_default_device()

    def _find_default_device(self) -> AudioDevice:
        """Find the device marked is_default=True, or fall back to the first device."""
        if not self._devices:
            raise AudioError("No audio devices available.")
        for dev in self._devices:
            if dev.is_default:
                return dev
        return self._devices[0]

    def list_devices(self) -> list[AudioDevice]:
        """Return a copy of the available devices list."""
        return list(self._devices)

    def get_default_device(self) -> AudioDevice:
        """Return the default audio input device."""
        return self._find_default_device()

    def get_selected_device(self) -> AudioDevice:
        """Return the currently selected device."""
        if self._selected_device is None:
            return self._find_default_device()
        return self._selected_device

    def select_device(self, device_id: str) -> AudioDevice:
        """Select an audio device by its unique ID.

        Raises:
            AudioError: If device_id is not found among available devices.
        """
        if not isinstance(device_id, str):
            raise AudioError("device_id must be a string.")

        for dev in self._devices:
            if dev.device_id == device_id:
                self._selected_device = dev
                return dev

        raise AudioError(f"Audio device '{device_id}' not found.")

    def request_permission(self) -> PermissionState:
        """Simulate user response to a permission request."""
        self._permission_state = self._permission_response
        return self._permission_state

    def get_permission_state(self) -> PermissionState:
        """Return the current permission state."""
        return self._permission_state

    def set_permission_state(self, state: PermissionState) -> None:
        """Simulate an external permission change (e.g. user revokes in OS settings)."""
        if not isinstance(state, PermissionState):
            raise AudioError("state must be a PermissionState enum value.")
        self._permission_state = state

    def set_permission_response(self, response: PermissionState) -> None:
        """Configure what future request_permission() calls will return."""
        if not isinstance(response, PermissionState):
            raise AudioError("response must be a PermissionState enum value.")
        self._permission_response = response

    def set_devices(self, devices: list[AudioDevice]) -> None:
        """Simulate hardware addition or removal (e.g. plugging/unplugging)."""
        if not isinstance(devices, list):
            raise AudioError("devices must be a list of AudioDevice instances.")
        for dev in devices:
            if not isinstance(dev, AudioDevice):
                raise AudioError("All items in devices must be AudioDevice instances.")
        self._devices = list(devices)

        # Update selected device if disconnected
        if self._selected_device and self._devices:
            if not any(d.device_id == self._selected_device.device_id for d in self._devices):
                self._selected_device = self._devices[0]
        elif not self._devices:
            self._selected_device = None

    def create_stream(
        self,
        chunk_count: int = 5,
        frames_per_chunk: int = 4,
        raw_data: bytes | None = None,
    ) -> Iterator[AudioChunk]:
        """Create and yield AudioChunk stream from the selected device.

        Raises:
            AudioError: If permission is DENIED, PROMPT, or device is UNAVAILABLE.
        """
        if self._permission_state == PermissionState.DENIED:
            raise AudioError("Microphone permission denied.")
        if self._permission_state == PermissionState.UNAVAILABLE:
            raise AudioError("Audio device is unavailable.")
        if self._permission_state == PermissionState.PROMPT:
            raise AudioError("Microphone permission has not been requested.")

        device = self.get_selected_device()
        if not any(d.device_id == device.device_id for d in self._devices):
            raise AudioError(f"Selected audio device '{device.device_id}' is unavailable.")

        # Stream deterministic chunks through Week 1 MockMicrophone
        mock_mic = MockMicrophone(
            sample_rate=device.default_sample_rate,
            channels=device.channels,
            chunk_count=chunk_count,
            frames_per_chunk=frames_per_chunk,
            sample_width=device.sample_width,
            raw_data=raw_data,
        )
        yield from mock_mic.stream()

