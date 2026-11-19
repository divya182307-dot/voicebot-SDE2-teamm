"""Unit test suite for device-loss recovery, auto-reconnection, and cancellation.

Week 3 (Days 17-18) validation for SDE Team 2.
"""

import math
import struct
import unittest

from voicebot.buffer import BoundedAudioBuffer, DropStrategy
from voicebot.device import (
    AudioDevice,
    MockAudioDeviceAdapter,
    PermissionState,
)
from voicebot.events import SpeechEventProcessor
from voicebot.lifecycle import AudioLifecycleController, LifecycleState
from voicebot.schemas import AudioChunk, AudioError, AudioFormat
from voicebot.vad import VoiceActivityDetector


class TestDeviceRecoveryAndCancellation(unittest.TestCase):
    """Test cases for cancellation, device disconnection, and auto-reconnect."""

    def setUp(self) -> None:
        self.device_headset = AudioDevice(
            device_id="mock-usb-headset",
            name="Mock USB Stereo Headset",
            channels=1,
            default_sample_rate=16000,
            is_default=False,
            sample_width=2,
        )
        self.device_builtin = AudioDevice(
            device_id="mock-default-mic",
            name="Mock Built-in Microphone",
            channels=1,
            default_sample_rate=16000,
            is_default=True,
            sample_width=2,
        )
        self.adapter = MockAudioDeviceAdapter(
            devices=[self.device_headset, self.device_builtin],
            initial_permission=PermissionState.GRANTED,
        )
        self.adapter.select_device("mock-usb-headset")
        self.controller = AudioLifecycleController(
            self.adapter,
            max_reconnect_attempts=3,
            reconnect_delay_seconds=0.0,
            auto_reconnect=True,
        )

    def _make_speech_chunk(self, seq_id: int, timestamp: float, amp: int = 15000) -> AudioChunk:
        fmt = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        samples = [int(amp * math.sin(2.0 * math.pi * 440.0 * (i / 16000.0))) for i in range(320)]
        data = struct.pack(f"<{len(samples)}h", *samples)
        return AudioChunk(
            sequence_id=seq_id,
            timestamp=timestamp,
            audio_format=fmt,
            data=data,
        )

    # -------------------------------------------------------------------------
    # Cancellation Tests
    # -------------------------------------------------------------------------

    def test_cancel_transitions_to_cancelled_state(self) -> None:
        """Verify cancel() transitions controller to CANCELLED and marks is_cancelled."""
        self.controller.start()
        self.assertEqual(self.controller.state, LifecycleState.RECORDING)
        self.assertFalse(self.controller.is_cancelled)

        self.controller.cancel()

        self.assertEqual(self.controller.state, LifecycleState.CANCELLED)
        self.assertTrue(self.controller.is_cancelled)

    def test_cancel_stops_capture_stream_immediately(self) -> None:
        """Verify calling cancel() terminates capture_stream without yielding more chunks."""
        self.controller.start()

        emitted_chunks = []
        for chunk in self.controller.capture_stream(chunk_count=10, frames_per_chunk=4):
            emitted_chunks.append(chunk)
            if len(emitted_chunks) == 2:
                self.controller.cancel()

        self.assertEqual(len(emitted_chunks), 2)
        self.assertEqual(self.controller.state, LifecycleState.CANCELLED)

    def test_cancel_flushes_and_releases_bounded_buffer(self) -> None:
        """Verify cancel(buffer=...) purges and releases queued chunks in BoundedAudioBuffer."""
        self.controller.start()
        buffer = BoundedAudioBuffer(max_chunks=20, drop_strategy=DropStrategy.DROP_OLDEST)

        # Push chunks into buffer
        for i in range(5):
            buffer.push(self._make_speech_chunk(i, i * 0.02))

        self.assertEqual(buffer.get_stats().current_occupancy, 5)

        # Cancel with buffer
        self.controller.cancel(buffer=buffer)

        self.assertEqual(self.controller.state, LifecycleState.CANCELLED)
        self.assertEqual(buffer.get_stats().current_occupancy, 0)
        self.assertIsNone(buffer.pull())

    def test_cancel_flushes_active_speech_turn_in_processor(self) -> None:
        """Verify cancel(processor=...) flushes SpeechEventProcessor cleanly."""
        self.controller.start()
        vad = VoiceActivityDetector(energy_threshold=0.02, min_speech_duration_ms=60.0)
        processor = SpeechEventProcessor(vad=vad, session_id=self.controller.session_id)

        # Feed 4 speech chunks to confirm speech onset (4 * 20ms = 80ms >= 60ms)
        for i in range(4):
            processor.process_chunk(self._make_speech_chunk(i, i * 0.02))

        self.assertTrue(processor.is_in_speech)
        self.assertIsNotNone(processor.active_correlation_id)

        # Cancel controller with processor
        self.controller.cancel(processor=processor)

        self.assertEqual(self.controller.state, LifecycleState.CANCELLED)
        self.assertFalse(processor.is_in_speech)
        self.assertIsNone(processor.active_correlation_id)
        self.assertEqual(vad.continuous_speech_duration_ms, 0.0)

    def test_cancel_is_safe_and_idempotent_from_any_state(self) -> None:
        """Verify cancel() can be invoked from INITIALIZED, PAUSED, STOPPED or CANCELLED."""
        # From INITIALIZED
        ctrl1 = AudioLifecycleController(self.adapter)
        ctrl1.cancel()
        self.assertEqual(ctrl1.state, LifecycleState.CANCELLED)

        # Idempotent (calling again)
        ctrl1.cancel()
        self.assertEqual(ctrl1.state, LifecycleState.CANCELLED)

        # From PAUSED
        self.controller.start()
        self.controller.pause()
        self.controller.cancel()
        self.assertEqual(self.controller.state, LifecycleState.CANCELLED)

        # From STOPPED
        self.controller.start()
        self.controller.stop()
        self.controller.cancel()
        self.assertEqual(self.controller.state, LifecycleState.CANCELLED)

    # -------------------------------------------------------------------------
    # Device-Loss Recovery and Auto-Reconnect Tests
    # -------------------------------------------------------------------------

    def test_midstream_device_disconnect_auto_reconnects_to_fallback(self) -> None:
        """Verify controller detects midstream disconnection, auto-reconnects to fallback, and finishes stream."""
        self.controller.start()
        original_session = self.controller.session_id
        self.assertEqual(self.adapter.get_selected_device().device_id, "mock-usb-headset")

        # Simulate disconnection after yielding 2 chunks
        self.adapter.simulate_disconnect_after(2)

        # Request 5 chunks total
        stream = self.controller.capture_stream(chunk_count=5, frames_per_chunk=4)
        chunks = list(stream)

        # All 5 chunks successfully received without host crash
        self.assertEqual(len(chunks), 5)
        self.assertEqual(self.controller.chunks_emitted, 5)

        # Telemetry verifies successful recovery
        self.assertGreater(self.controller.reconnect_count, 0)
        self.assertEqual(self.controller.successful_reconnects, 1)
        self.assertEqual(self.controller.last_recovery_device, "mock-default-mic")

        # Session ID preserved end-to-end
        self.assertEqual(self.controller.session_id, original_session)
        self.assertEqual(self.controller.state, LifecycleState.RECORDING)

    def test_reconnect_exhausted_when_no_devices_remain(self) -> None:
        """Verify controller transitions to ERROR and raises AudioError when all devices are lost."""
        single_dev = AudioDevice(
            device_id="only-mic",
            name="Single Mic",
            channels=1,
            default_sample_rate=16000,
            is_default=True,
            sample_width=2,
        )
        adapter = MockAudioDeviceAdapter(
            devices=[single_dev],
            initial_permission=PermissionState.GRANTED,
        )
        ctrl = AudioLifecycleController(adapter, max_reconnect_attempts=2, auto_reconnect=True)
        ctrl.start()

        # Simulate disconnect and remove all devices
        adapter.simulate_disconnect_after(1)
        adapter.set_devices([])  # No fallback available

        with self.assertRaises(AudioError) as ctx:
            list(ctrl.capture_stream(chunk_count=4, frames_per_chunk=4))

        self.assertIn("Audio capture aborted", str(ctx.exception))
        self.assertEqual(ctrl.state, LifecycleState.ERROR)

    def test_auto_reconnect_disabled_aborts_immediately(self) -> None:
        """Verify when auto_reconnect=False, device loss immediately raises AudioError without retrying."""
        ctrl = AudioLifecycleController(
            self.adapter,
            auto_reconnect=False,
            max_reconnect_attempts=0,
        )
        ctrl.start()
        self.adapter.simulate_disconnect_after(1)

        with self.assertRaises(AudioError) as ctx:
            list(ctrl.capture_stream(chunk_count=4, frames_per_chunk=4))

        self.assertIn("Audio capture aborted", str(ctx.exception))
        self.assertEqual(ctrl.state, LifecycleState.ERROR)
        self.assertEqual(ctrl.reconnect_count, 0)

    def test_explicit_reconnect_method(self) -> None:
        """Verify manual invocation of reconnect() establishes connection to healthy device."""
        self.controller.start()
        # Disconnect active headset
        self.adapter.disconnect_device("mock-usb-headset")

        # Manually trigger reconnect
        success = self.controller.reconnect()

        self.assertTrue(success)
        self.assertEqual(self.controller.successful_reconnects, 1)
        self.assertEqual(self.controller.last_recovery_device, "mock-default-mic")
        self.assertEqual(self.adapter.get_selected_device().device_id, "mock-default-mic")

    def test_controller_initialization_validation(self) -> None:
        """Verify AudioLifecycleController rejects invalid reconnect configuration parameters."""
        with self.assertRaises(AudioError):
            AudioLifecycleController(self.adapter, max_reconnect_attempts=-1)
        with self.assertRaises(AudioError):
            AudioLifecycleController(self.adapter, max_reconnect_attempts=True)  # type: ignore
        with self.assertRaises(AudioError):
            AudioLifecycleController(self.adapter, reconnect_delay_seconds=-0.5)
        with self.assertRaises(AudioError):
            AudioLifecycleController(self.adapter, auto_reconnect="yes")  # type: ignore


if __name__ == "__main__":
    unittest.main()
