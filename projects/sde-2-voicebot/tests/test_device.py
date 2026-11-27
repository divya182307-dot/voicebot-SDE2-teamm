"""Comprehensive unit tests for AudioDevice, PermissionState, and MockAudioDeviceAdapter.

Week 2 (Days 8-9) Deliverables for SDE Team 2.
"""

from dataclasses import FrozenInstanceError
import unittest

from voicebot.device import (
    AudioDevice,
    AudioDeviceAdapter,
    MockAudioDeviceAdapter,
    PermissionState,
)
from voicebot.schemas import AudioChunk, AudioError, AudioFormat


class TestPermissionState(unittest.TestCase):
    """Test suite for PermissionState enum."""

    def test_permission_state_values(self):
        """Verify all required permission states exist with correct string representations."""
        self.assertEqual(PermissionState.PROMPT, "PROMPT")
        self.assertEqual(PermissionState.GRANTED, "GRANTED")
        self.assertEqual(PermissionState.DENIED, "DENIED")
        self.assertEqual(PermissionState.UNAVAILABLE, "UNAVAILABLE")

    def test_permission_state_count(self):
        """Verify the exact set of permission states."""
        expected = {"PROMPT", "GRANTED", "DENIED", "UNAVAILABLE"}
        actual = {state.value for state in PermissionState}
        self.assertEqual(expected, actual)


class TestAudioDevice(unittest.TestCase):
    """Test suite for AudioDevice dataclass validation and immutability."""

    def test_valid_audio_device_mono(self):
        """Verify creation of a standard mono audio device."""
        device = AudioDevice(
            device_id="mic-01",
            name="Built-in Microphone",
            channels=1,
            default_sample_rate=16000,
            is_default=True,
            sample_width=2,
        )
        self.assertEqual(device.device_id, "mic-01")
        self.assertEqual(device.name, "Built-in Microphone")
        self.assertEqual(device.channels, 1)
        self.assertEqual(device.default_sample_rate, 16000)
        self.assertTrue(device.is_default)
        self.assertEqual(device.sample_width, 2)

    def test_valid_audio_device_stereo(self):
        """Verify creation of a stereo audio device."""
        device = AudioDevice(
            device_id="headset-01",
            name="Stereo Headset",
            channels=2,
            default_sample_rate=48000,
            is_default=False,
        )
        self.assertEqual(device.channels, 2)
        self.assertEqual(device.default_sample_rate, 48000)
        self.assertFalse(device.is_default)
        self.assertEqual(device.sample_width, 2)

    def test_audio_device_default_format_property(self):
        """Verify default_format property returns a matching AudioFormat instance."""
        device = AudioDevice(
            device_id="mic-01",
            name="Studio Mic",
            channels=1,
            default_sample_rate=44100,
            sample_width=2,
        )
        fmt = device.default_format
        self.assertIsInstance(fmt, AudioFormat)
        self.assertEqual(fmt.sample_rate, 44100)
        self.assertEqual(fmt.channels, 1)
        self.assertEqual(fmt.sample_width, 2)

    def test_audio_device_immutability(self):
        """Verify AudioDevice is frozen and cannot be mutated."""
        device = AudioDevice(
            device_id="mic-01",
            name="Studio Mic",
            channels=1,
            default_sample_rate=16000,
        )
        with self.assertRaises(FrozenInstanceError):
            device.name = "Modified Name"  # type: ignore

    def test_invalid_device_id(self):
        """Verify invalid or empty device_id raises AudioError."""
        for invalid_id in ["", "   ", None, 123, True]:
            with self.subTest(invalid_id=invalid_id):
                with self.assertRaises(AudioError):
                    AudioDevice(
                        device_id=invalid_id,  # type: ignore
                        name="Mic",
                        channels=1,
                        default_sample_rate=16000,
                    )

    def test_invalid_name(self):
        """Verify invalid or empty name raises AudioError."""
        for invalid_name in ["", "   ", None, 456, False]:
            with self.subTest(invalid_name=invalid_name):
                with self.assertRaises(AudioError):
                    AudioDevice(
                        device_id="mic-01",
                        name=invalid_name,  # type: ignore
                        channels=1,
                        default_sample_rate=16000,
                    )

    def test_invalid_channels(self):
        """Verify invalid channel counts raise AudioError."""
        for invalid_ch in [0, 3, -1, True, False, "mono", 1.5]:
            with self.subTest(invalid_ch=invalid_ch):
                with self.assertRaises(AudioError):
                    AudioDevice(
                        device_id="mic-01",
                        name="Mic",
                        channels=invalid_ch,  # type: ignore
                        default_sample_rate=16000,
                    )

    def test_invalid_sample_rate(self):
        """Verify invalid sample rates raise AudioError."""
        for invalid_rate in [0, -16000, True, False, "16000", 16000.5]:
            with self.subTest(invalid_rate=invalid_rate):
                with self.assertRaises(AudioError):
                    AudioDevice(
                        device_id="mic-01",
                        name="Mic",
                        channels=1,
                        default_sample_rate=invalid_rate,  # type: ignore
                    )

    def test_invalid_sample_width(self):
        """Verify invalid sample widths raise AudioError."""
        for invalid_width in [0, 5, -2, True, False, "2", 2.0]:
            with self.subTest(invalid_width=invalid_width):
                with self.assertRaises(AudioError):
                    AudioDevice(
                        device_id="mic-01",
                        name="Mic",
                        channels=1,
                        default_sample_rate=16000,
                        sample_width=invalid_width,  # type: ignore
                    )

    def test_invalid_is_default(self):
        """Verify non-boolean is_default raises AudioError."""
        for invalid_default in [1, 0, "true", None]:
            with self.subTest(invalid_default=invalid_default):
                with self.assertRaises(AudioError):
                    AudioDevice(
                        device_id="mic-01",
                        name="Mic",
                        channels=1,
                        default_sample_rate=16000,
                        is_default=invalid_default,  # type: ignore
                    )


class TestMockAudioDeviceAdapter(unittest.TestCase):
    """Test suite for MockAudioDeviceAdapter operations, selection, and permissions."""

    def setUp(self):
        """Set up a fresh MockAudioDeviceAdapter before each test."""
        self.adapter = MockAudioDeviceAdapter()

    def test_implements_abstract_interface(self):
        """Verify MockAudioDeviceAdapter inherits from AudioDeviceAdapter."""
        self.assertIsInstance(self.adapter, AudioDeviceAdapter)

    def test_default_devices_initialization(self):
        """Verify adapter initializes with standard mock devices."""
        devices = self.adapter.list_devices()
        self.assertEqual(len(devices), 2)
        device_ids = [d.device_id for d in devices]
        self.assertIn("mock-default-mic", device_ids)
        self.assertIn("mock-usb-headset", device_ids)

    def test_list_devices_returns_shallow_copy(self):
        """Verify list_devices returns a copy that does not mutate internal list."""
        devs = self.adapter.list_devices()
        devs.clear()
        self.assertEqual(len(self.adapter.list_devices()), 2)

    def test_get_default_device(self):
        """Verify get_default_device returns the device flagged is_default=True."""
        default_dev = self.adapter.get_default_device()
        self.assertEqual(default_dev.device_id, "mock-default-mic")
        self.assertTrue(default_dev.is_default)

    def test_get_selected_device_defaults_to_default(self):
        """Verify get_selected_device initially returns the default device."""
        selected = self.adapter.get_selected_device()
        self.assertEqual(selected.device_id, "mock-default-mic")

    def test_select_device_success(self):
        """Verify selecting an available device updates the selected device."""
        selected = self.adapter.select_device("mock-usb-headset")
        self.assertEqual(selected.device_id, "mock-usb-headset")
        self.assertEqual(self.adapter.get_selected_device().device_id, "mock-usb-headset")

    def test_select_device_not_found_raises_audio_error(self):
        """Verify selecting a non-existent device raises AudioError."""
        with self.assertRaises(AudioError) as ctx:
            self.adapter.select_device("unknown-device-id")
        self.assertIn("not found", str(ctx.exception))

    def test_select_device_invalid_type_raises_audio_error(self):
        """Verify selecting non-string device_id raises AudioError."""
        with self.assertRaises(AudioError):
            self.adapter.select_device(12345)  # type: ignore

    def test_custom_device_initialization(self):
        """Verify adapter initializes with custom device list."""
        custom_devices = [
            AudioDevice(
                device_id="custom-mic",
                name="Custom Microphone",
                channels=1,
                default_sample_rate=32000,
                is_default=True,
            )
        ]
        adapter = MockAudioDeviceAdapter(devices=custom_devices)
        self.assertEqual(len(adapter.list_devices()), 1)
        self.assertEqual(adapter.get_default_device().device_id, "custom-mic")

    def test_empty_devices_raises_on_get_default(self):
        """Verify get_default_device raises AudioError when device list is empty."""
        adapter = MockAudioDeviceAdapter(devices=[])
        with self.assertRaises(AudioError):
            adapter.get_default_device()

    def test_set_devices_updates_available_hardware(self):
        """Verify set_devices simulates plugging/unplugging hardware."""
        new_device = AudioDevice(
            device_id="mic-plugged",
            name="Hotplug Mic",
            channels=1,
            default_sample_rate=16000,
            is_default=True,
        )
        self.adapter.set_devices([new_device])
        self.assertEqual(len(self.adapter.list_devices()), 1)
        self.assertEqual(self.adapter.get_selected_device().device_id, "mic-plugged")


class TestPermissionWorkflow(unittest.TestCase):
    """Test suite for microphone permission states, denials, and transitions."""

    def test_initial_permission_state_is_prompt(self):
        """Verify fresh adapter starts in PROMPT state."""
        adapter = MockAudioDeviceAdapter()
        self.assertEqual(adapter.get_permission_state(), PermissionState.PROMPT)

    def test_request_permission_grants_by_default(self):
        """Verify default request_permission() transitions from PROMPT to GRANTED."""
        adapter = MockAudioDeviceAdapter()
        res = adapter.request_permission()
        self.assertEqual(res, PermissionState.GRANTED)
        self.assertEqual(adapter.get_permission_state(), PermissionState.GRANTED)

    def test_request_permission_denial_simulation(self):
        """Verify configuring permission denial returns DENIED state."""
        adapter = MockAudioDeviceAdapter(
            permission_response=PermissionState.DENIED,
        )
        res = adapter.request_permission()
        self.assertEqual(res, PermissionState.DENIED)
        self.assertEqual(adapter.get_permission_state(), PermissionState.DENIED)

    def test_set_permission_response_updates_subsequent_request(self):
        """Verify set_permission_response alters future request_permission() results."""
        adapter = MockAudioDeviceAdapter()
        adapter.set_permission_response(PermissionState.DENIED)
        self.assertEqual(adapter.request_permission(), PermissionState.DENIED)

    def test_set_permission_state_simulates_external_revocation(self):
        """Verify set_permission_state simulates OS settings permission change."""
        adapter = MockAudioDeviceAdapter(initial_permission=PermissionState.GRANTED)
        self.assertEqual(adapter.get_permission_state(), PermissionState.GRANTED)

        adapter.set_permission_state(PermissionState.DENIED)
        self.assertEqual(adapter.get_permission_state(), PermissionState.DENIED)

    def test_invalid_permission_enum_raises_audio_error(self):
        """Verify setting invalid permission state types raises AudioError."""
        adapter = MockAudioDeviceAdapter()
        with self.assertRaises(AudioError):
            adapter.set_permission_state("INVALID_STATE")  # type: ignore
        with self.assertRaises(AudioError):
            adapter.set_permission_response(None)  # type: ignore


class TestStreamCreationAndSecurity(unittest.TestCase):
    """Test suite for audio stream creation, security boundaries, and schema compatibility."""

    def test_create_stream_without_permission_prompt_raises_audio_error(self):
        """Verify attempting to stream while in PROMPT state raises AudioError."""
        adapter = MockAudioDeviceAdapter(initial_permission=PermissionState.PROMPT)
        with self.assertRaises(AudioError) as ctx:
            list(adapter.create_stream())
        self.assertIn("has not been requested", str(ctx.exception))

    def test_create_stream_with_permission_denied_raises_audio_error(self):
        """Verify attempting to stream when permission is DENIED raises AudioError (PRD Sec 19)."""
        adapter = MockAudioDeviceAdapter(initial_permission=PermissionState.DENIED)
        with self.assertRaises(AudioError) as ctx:
            list(adapter.create_stream())
        self.assertIn("permission denied", str(ctx.exception))

    def test_create_stream_with_device_unavailable_raises_audio_error(self):
        """Verify attempting to stream when device is UNAVAILABLE raises AudioError."""
        adapter = MockAudioDeviceAdapter(initial_permission=PermissionState.UNAVAILABLE)
        with self.assertRaises(AudioError) as ctx:
            list(adapter.create_stream())
        self.assertIn("unavailable", str(ctx.exception))

    def test_create_stream_success_when_permission_granted(self):
        """Verify streaming succeeds when permission is GRANTED and emits valid AudioChunks."""
        adapter = MockAudioDeviceAdapter()
        adapter.request_permission()  # Transitions to GRANTED

        chunks = list(adapter.create_stream(chunk_count=3, frames_per_chunk=8))
        self.assertEqual(len(chunks), 3)

        for i, chunk in enumerate(chunks):
            self.assertIsInstance(chunk, AudioChunk)
            self.assertEqual(chunk.sequence_id, i)
            self.assertEqual(chunk.audio_format.sample_rate, 16000)
            self.assertEqual(chunk.audio_format.channels, 1)
            self.assertEqual(chunk.frame_count, 8)
            self.assertGreater(len(chunk.data), 0)

    def test_create_stream_from_stereo_device(self):
        """Verify streaming from selected stereo device emits stereo AudioChunks."""
        adapter = MockAudioDeviceAdapter()
        adapter.request_permission()
        adapter.select_device("mock-usb-headset")

        chunks = list(adapter.create_stream(chunk_count=2, frames_per_chunk=10))
        self.assertEqual(len(chunks), 2)

        for chunk in chunks:
            self.assertEqual(chunk.audio_format.sample_rate, 48000)
            self.assertEqual(chunk.audio_format.channels, 2)
            self.assertEqual(chunk.audio_format.bytes_per_frame, 4)  # 2 channels * 2 bytes
            self.assertEqual(chunk.frame_count, 10)
            self.assertEqual(len(chunk.data), 40)  # 10 frames * 4 bytes

    def test_create_stream_with_raw_pcm_bytes(self):
        """Verify streaming pre-recorded raw PCM bytes through the mock adapter."""
        adapter = MockAudioDeviceAdapter()
        adapter.request_permission()

        raw_bytes = bytes([0x12, 0x34] * 16)  # 16 mono 16-bit frames = 32 bytes
        chunks = list(adapter.create_stream(frames_per_chunk=4, raw_data=raw_bytes))
        self.assertEqual(len(chunks), 4)
        concatenated = b"".join(c.data for c in chunks)
        self.assertEqual(concatenated, raw_bytes)


if __name__ == "__main__":
    unittest.main()

