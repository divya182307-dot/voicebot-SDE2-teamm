"""Unit tests for AudioLifecycleController and LifecycleState.

Week 2 (Days 10-11) Deliverables for SDE Team 2.
"""

import unittest

from voicebot.device import MockAudioDeviceAdapter, PermissionState
from voicebot.lifecycle import AudioLifecycleController, LifecycleState
from voicebot.schemas import AudioChunk, AudioError


class TestLifecycleStateTransitions(unittest.TestCase):
    """Test suite for legal and illegal lifecycle state transitions."""

    def setUp(self):
        """Create fresh mock adapter with granted permission and controller."""
        self.adapter = MockAudioDeviceAdapter(
            initial_permission=PermissionState.GRANTED
        )
        self.controller = AudioLifecycleController(self.adapter)

    def test_initial_state_is_initialized(self):
        """Verify new controller begins in INITIALIZED state."""
        self.assertEqual(self.controller.state, LifecycleState.INITIALIZED)
        self.assertFalse(self.controller.is_active)
        self.assertFalse(self.controller.is_recording)
        self.assertFalse(self.controller.is_paused)
        self.assertIsNone(self.controller.session_id)

    def test_legal_full_lifecycle(self):
        """Verify normal start -> pause -> resume -> stop transition path."""
        # start
        self.controller.start()
        self.assertEqual(self.controller.state, LifecycleState.RECORDING)
        self.assertTrue(self.controller.is_active)
        self.assertTrue(self.controller.is_recording)
        self.assertIsNotNone(self.controller.session_id)

        # pause
        self.controller.pause()
        self.assertEqual(self.controller.state, LifecycleState.PAUSED)
        self.assertTrue(self.controller.is_active)
        self.assertTrue(self.controller.is_paused)
        self.assertFalse(self.controller.is_recording)

        # resume
        self.controller.resume()
        self.assertEqual(self.controller.state, LifecycleState.RECORDING)
        self.assertTrue(self.controller.is_recording)

        # stop
        self.controller.stop()
        self.assertEqual(self.controller.state, LifecycleState.STOPPED)
        self.assertFalse(self.controller.is_active)
        self.assertIsNone(self.controller.session_id)

    def test_start_from_stopped_allowed(self):
        """Verify a stopped controller can start a new capture session."""
        self.controller.start()
        session1 = self.controller.session_id
        self.controller.stop()

        self.controller.start()
        session2 = self.controller.session_id
        self.assertEqual(self.controller.state, LifecycleState.RECORDING)
        self.assertNotEqual(session1, session2)

    def test_stop_from_paused_allowed(self):
        """Verify controller can transition directly from PAUSED to STOPPED."""
        self.controller.start()
        self.controller.pause()
        self.controller.stop()
        self.assertEqual(self.controller.state, LifecycleState.STOPPED)

    def test_stop_from_initialized_allowed(self):
        """Verify controller can transition directly from INITIALIZED to STOPPED."""
        self.controller.stop()
        self.assertEqual(self.controller.state, LifecycleState.STOPPED)

    def test_stop_is_idempotent(self):
        """Verify calling stop() repeatedly does not raise errors."""
        self.controller.start()
        self.controller.stop()
        self.controller.stop()
        self.controller.stop()
        self.assertEqual(self.controller.state, LifecycleState.STOPPED)

    def test_pause_from_initialized_raises_audio_error(self):
        """Verify pause() before start() raises AudioError."""
        with self.assertRaises(AudioError) as ctx:
            self.controller.pause()
        self.assertIn("not in RECORDING state", str(ctx.exception))

    def test_pause_from_paused_raises_audio_error(self):
        """Verify calling pause() when already paused raises AudioError."""
        self.controller.start()
        self.controller.pause()
        with self.assertRaises(AudioError) as ctx:
            self.controller.pause()
        self.assertIn("already paused", str(ctx.exception))

    def test_pause_from_stopped_raises_audio_error(self):
        """Verify calling pause() when stopped raises AudioError."""
        self.controller.start()
        self.controller.stop()
        with self.assertRaises(AudioError):
            self.controller.pause()

    def test_resume_from_initialized_raises_audio_error(self):
        """Verify resume() before pause() raises AudioError."""
        with self.assertRaises(AudioError) as ctx:
            self.controller.resume()
        self.assertIn("not in PAUSED state", str(ctx.exception))

    def test_resume_from_recording_raises_audio_error(self):
        """Verify calling resume() while already recording raises AudioError."""
        self.controller.start()
        with self.assertRaises(AudioError) as ctx:
            self.controller.resume()
        self.assertIn("already recording", str(ctx.exception))

    def test_resume_from_stopped_raises_audio_error(self):
        """Verify calling resume() when stopped raises AudioError."""
        self.controller.start()
        self.controller.stop()
        with self.assertRaises(AudioError):
            self.controller.resume()

    def test_start_when_already_recording_raises_audio_error(self):
        """Verify calling start() while recording raises AudioError."""
        self.controller.start()
        with self.assertRaises(AudioError) as ctx:
            self.controller.start()
        self.assertIn("already recording", str(ctx.exception))

    def test_start_when_paused_raises_audio_error(self):
        """Verify calling start() while paused instructs caller to use resume()."""
        self.controller.start()
        self.controller.pause()
        with self.assertRaises(AudioError) as ctx:
            self.controller.start()
        self.assertIn("Call resume()", str(ctx.exception))

    def test_reset_restores_initialized_state(self):
        """Verify reset() restores clean INITIALIZED state."""
        self.controller.start()
        self.controller.pause()
        self.controller.reset()
        self.assertEqual(self.controller.state, LifecycleState.INITIALIZED)
        self.assertIsNone(self.controller.session_id)
        self.assertEqual(self.controller.chunks_emitted, 0)
        self.assertEqual(self.controller.chunks_suppressed, 0)


class TestLifecycleDeviceIntegration(unittest.TestCase):
    """Test suite for lifecycle controller device permissions and hardware errors."""

    def test_start_with_denied_permission_raises_and_transitions_to_error(self):
        """Verify start() with DENIED permission raises AudioError and sets ERROR state."""
        adapter = MockAudioDeviceAdapter(initial_permission=PermissionState.DENIED)
        controller = AudioLifecycleController(adapter)

        with self.assertRaises(AudioError) as ctx:
            controller.start()
        self.assertIn("permission denied", str(ctx.exception))
        self.assertEqual(controller.state, LifecycleState.ERROR)

    def test_start_with_unavailable_device_raises_and_transitions_to_error(self):
        """Verify start() with UNAVAILABLE device raises AudioError and sets ERROR state."""
        adapter = MockAudioDeviceAdapter(initial_permission=PermissionState.UNAVAILABLE)
        controller = AudioLifecycleController(adapter)

        with self.assertRaises(AudioError) as ctx:
            controller.start()
        self.assertIn("unavailable", str(ctx.exception))
        self.assertEqual(controller.state, LifecycleState.ERROR)

    def test_start_with_prompt_permission_requests_and_succeeds(self):
        """Verify start() automatically requests permission if in PROMPT state."""
        adapter = MockAudioDeviceAdapter(
            initial_permission=PermissionState.PROMPT,
            permission_response=PermissionState.GRANTED,
        )
        controller = AudioLifecycleController(adapter)
        controller.start()
        self.assertEqual(controller.state, LifecycleState.RECORDING)

    def test_invalid_adapter_type_raises_audio_error(self):
        """Verify constructor validates AudioDeviceAdapter instance."""
        with self.assertRaises(AudioError):
            AudioLifecycleController(None)  # type: ignore


class TestLifecycleStreamCapture(unittest.TestCase):
    """Test suite for stream capture, pause suppression, and mid-stream revocation."""

    def test_capture_stream_emits_chunks_when_recording(self):
        """Verify capture_stream yields AudioChunk instances while recording."""
        adapter = MockAudioDeviceAdapter(initial_permission=PermissionState.GRANTED)
        controller = AudioLifecycleController(adapter)
        controller.start()

        chunks = list(controller.capture_stream(chunk_count=3, frames_per_chunk=4))
        self.assertEqual(len(chunks), 3)
        self.assertEqual(controller.chunks_emitted, 3)
        self.assertEqual(controller.chunks_suppressed, 0)
        for chunk in chunks:
            self.assertIsInstance(chunk, AudioChunk)

    def test_capture_stream_suppresses_chunks_when_paused(self):
        """Verify chunks are suppressed (not emitted) when controller is paused."""
        adapter = MockAudioDeviceAdapter(initial_permission=PermissionState.GRANTED)
        controller = AudioLifecycleController(adapter)
        controller.start()
        controller.pause()

        # Capture while paused
        chunks = list(controller.capture_stream(chunk_count=3, frames_per_chunk=4))
        self.assertEqual(len(chunks), 0)
        self.assertEqual(controller.chunks_suppressed, 3)
        self.assertEqual(controller.chunks_emitted, 0)

    def test_capture_stream_when_not_active_raises_audio_error(self):
        """Verify capture_stream without start() raises AudioError."""
        adapter = MockAudioDeviceAdapter(initial_permission=PermissionState.GRANTED)
        controller = AudioLifecycleController(adapter)

        with self.assertRaises(AudioError) as ctx:
            list(controller.capture_stream(chunk_count=2))
        self.assertIn("must be RECORDING or PAUSED", str(ctx.exception))

    def test_capture_stream_aborts_on_midstream_revocation(self):
        """Verify capture_stream transitions to ERROR if permission revoked mid-stream."""
        adapter = MockAudioDeviceAdapter(initial_permission=PermissionState.GRANTED)
        controller = AudioLifecycleController(adapter)
        controller.start()

        # Simulate user revoking permission in OS settings
        adapter.set_permission_state(PermissionState.DENIED)

        with self.assertRaises(AudioError) as ctx:
            list(controller.capture_stream(chunk_count=2))
        self.assertIn("Audio capture aborted", str(ctx.exception))
        self.assertEqual(controller.state, LifecycleState.ERROR)


if __name__ == "__main__":
    unittest.main()

