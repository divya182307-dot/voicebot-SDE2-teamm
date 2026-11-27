"""Robustness and integration tests for SDE Team 2 (Week 2, Day 14).

Covers required Day 14 deliverables:
- Tests for sequence gaps (missing audio chunks).
- Tests for late / out-of-order chunks.
- Tests for noise robustness (transient clicks vs ambient noise vs speech).
- End-to-end integration across Adapter, Lifecycle, VAD, Buffer, and Diagnostics.
"""

import math
import struct
import unittest

from voicebot.buffer import BoundedAudioBuffer, DropStrategy
from voicebot.device import MockAudioDeviceAdapter, PermissionState
from voicebot.diagnostics import PipelineDiagnostics, collect_diagnostics
from voicebot.lifecycle import AudioLifecycleController, LifecycleState
from voicebot.schemas import AudioChunk, AudioFormat
from voicebot.vad import VoiceActivityDetector


class TestSequenceGapsAndLateChunks(unittest.TestCase):
    """Test suite for detecting and handling sequence gaps and out-of-order chunks."""

    def setUp(self):
        """Set up standard mono 16kHz audio format fixture."""
        self.format = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        self.buffer = BoundedAudioBuffer(max_chunks=20)

    def _create_chunk(self, sequence_id: int, amplitude: int = 5000) -> AudioChunk:
        """Helper to create dummy 10ms chunk with specified sequence ID."""
        frames = 160  # 10ms at 16kHz
        data = struct.pack(f"<{frames}h", *([amplitude] * frames))
        return AudioChunk(
            sequence_id=sequence_id,
            timestamp=sequence_id * 0.01,
            audio_format=self.format,
            data=data,
        )

    def test_single_sequence_gap_detected(self):
        """Verify buffer detects when chunks skip sequence IDs (e.g. 0, 1 -> 4)."""
        self.buffer.push(self._create_chunk(0))
        self.buffer.push(self._create_chunk(1))
        # Gap: seq 2 and 3 are missing!
        self.buffer.push(self._create_chunk(4))

        gaps = self.buffer.gaps_detected
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0], (2, 3))  # Missing seq 2 through 3

    def test_multiple_sequence_gaps(self):
        """Verify buffer tracks multiple separate sequence gaps in stream."""
        self.buffer.push(self._create_chunk(0))
        self.buffer.push(self._create_chunk(3))  # Gap 1: missing (1, 2)
        self.buffer.push(self._create_chunk(4))
        self.buffer.push(self._create_chunk(7))  # Gap 2: missing (5, 6)

        gaps = self.buffer.gaps_detected
        self.assertEqual(len(gaps), 2)
        self.assertEqual(gaps[0], (1, 2))
        self.assertEqual(gaps[1], (5, 6))

    def test_late_chunk_detected(self):
        """Verify out-of-order chunk arriving after higher sequence ID is flagged."""
        self.buffer.push(self._create_chunk(0))
        self.buffer.push(self._create_chunk(2))
        # Seq 1 arrives late after seq 2 has already been seen
        self.buffer.push(self._create_chunk(1))

        late = self.buffer.late_chunks_detected
        self.assertEqual(len(late), 1)
        self.assertEqual(late[0], 1)

    def test_pipeline_continues_cleanly_after_gaps_and_late_chunks(self):
        """Verify pipeline drains chunks cleanly and does not deadlock after gaps."""
        self.buffer.push(self._create_chunk(0))
        self.buffer.push(self._create_chunk(3))
        self.buffer.push(self._create_chunk(1))  # late
        self.buffer.push(self._create_chunk(4))

        # Draining buffer retrieves all 4 chunks
        pulled = self.buffer.pull_all()
        self.assertEqual(len(pulled), 4)
        self.assertEqual([c.sequence_id for c in pulled], [0, 3, 1, 4])


class TestNoiseRobustness(unittest.TestCase):
    """Test suite for VAD robustness against ambient noise, clicks, and speech."""

    def setUp(self):
        self.format = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        self.frames_per_chunk = 160  # 10ms chunks
        # Standard conversational VAD: threshold = 0.02, min duration = 100ms
        self.vad = VoiceActivityDetector(
            energy_threshold=0.02,
            min_speech_duration_ms=100.0,
        )

    def _create_sine_chunk(self, sequence_id: int, amplitude: int, freq: float = 300.0) -> AudioChunk:
        """Create a 10ms chunk containing a pure sine tone."""
        samples = [
            int(amplitude * math.sin(2.0 * math.pi * freq * i / 16000.0))
            for i in range(self.frames_per_chunk)
        ]
        data = struct.pack(f"<{self.frames_per_chunk}h", *samples)
        return AudioChunk(
            sequence_id=sequence_id,
            timestamp=sequence_id * 0.01,
            audio_format=self.format,
            data=data,
        )

    def _create_noise_chunk(self, sequence_id: int, max_amplitude: int) -> AudioChunk:
        """Create a 10ms chunk with simulated pseudo-random noise."""
        # Deterministic pseudo-random pattern (LCG formula)
        samples = []
        seed = sequence_id * 1000 + 7
        for _ in range(self.frames_per_chunk):
            seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
            sample = int(((seed % 2000) / 1000.0 - 1.0) * max_amplitude)
            samples.append(sample)

        data = struct.pack(f"<{self.frames_per_chunk}h", *samples)
        return AudioChunk(
            sequence_id=sequence_id,
            timestamp=sequence_id * 0.01,
            audio_format=self.format,
            data=data,
        )

    def test_ambient_background_noise_ignored(self):
        """Verify low-level continuous room noise is classified as silence."""
        # Ambient noise with max amplitude 350 (~0.006 RMS, well below 0.02 threshold)
        for seq in range(10):  # 100ms of background noise
            chunk = self._create_noise_chunk(seq, max_amplitude=350)
            res = self.vad.process_chunk(chunk)
            self.assertFalse(res.is_speech)

        self.assertEqual(self.vad.total_speech_chunks, 0)
        self.assertEqual(self.vad.total_silence_chunks, 10)

    def test_impulsive_click_noise_rejected(self):
        """Verify sharp, high-amplitude transient (mouse click lasting 20ms) is rejected."""
        # 2 chunks of high-energy click noise (20ms total)
        click1 = self._create_noise_chunk(0, max_amplitude=16000)
        click2 = self._create_noise_chunk(1, max_amplitude=16000)
        silence = self._create_noise_chunk(2, max_amplitude=0)

        res1 = self.vad.process_chunk(click1)
        res2 = self.vad.process_chunk(click2)
        res3 = self.vad.process_chunk(silence)

        self.assertFalse(res1.is_speech)
        self.assertFalse(res2.is_speech)
        self.assertFalse(res3.is_speech)  # Returns to silence
        self.assertEqual(self.vad.total_speech_chunks, 0)

    def test_speech_in_presence_of_noise_detected(self):
        """Verify sustained voice audio correctly triggers speech classification."""
        # 12 chunks of 10ms = 120ms of speech (amplitude 14000 ~ 0.30 RMS)
        speech_results = []
        for seq in range(12):
            chunk = self._create_sine_chunk(seq, amplitude=14000, freq=250.0)
            speech_results.append(self.vad.process_chunk(chunk))

        # Initially accumulating (duration < 100ms)
        self.assertFalse(speech_results[0].is_speech)
        self.assertFalse(speech_results[8].is_speech)

        # At 100ms (chunk index 9), speech triggers!
        self.assertTrue(speech_results[9].is_speech)
        self.assertTrue(speech_results[10].is_speech)
        self.assertTrue(speech_results[11].is_speech)
        self.assertGreater(self.vad.total_speech_chunks, 0)


class TestEndToEndPipelineIntegration(unittest.TestCase):
    """Test suite for full pipeline integration across all Week 2 deliverables."""

    def test_full_pipeline_capture_vad_buffer_and_diagnostics(self):
        """Verify end-to-end integration: Adapter -> Lifecycle -> VAD -> Buffer -> Diagnostics."""
        # 1. Adapter & Permissions
        adapter = MockAudioDeviceAdapter(initial_permission=PermissionState.GRANTED)

        # 2. Lifecycle Controller
        controller = AudioLifecycleController(adapter)
        controller.start()
        self.assertEqual(controller.state, LifecycleState.RECORDING)

        # 3. VAD & Bounded Buffer
        vad = VoiceActivityDetector(energy_threshold=0.02, min_speech_duration_ms=50.0)
        buffer = BoundedAudioBuffer(max_chunks=10, drop_strategy=DropStrategy.DROP_OLDEST)

        # 4. Stream 5 chunks through the pipeline
        for chunk in controller.capture_stream(chunk_count=5, frames_per_chunk=160):
            vad_res = vad.process_chunk(chunk)
            buffer.push(chunk)

        # Verify chunks buffered and controller metrics
        self.assertEqual(controller.chunks_emitted, 5)
        self.assertEqual(buffer.current_occupancy, 5)

        # 5. Pause lifecycle
        controller.pause()
        self.assertEqual(controller.state, LifecycleState.PAUSED)

        # 6. Stop and release
        controller.stop()
        self.assertEqual(controller.state, LifecycleState.STOPPED)

        # 7. Collect and verify diagnostics
        diag = collect_diagnostics(controller, buffer, vad)
        self.assertIsInstance(diag, PipelineDiagnostics)
        self.assertEqual(diag.permission_state, "GRANTED")
        self.assertEqual(diag.lifecycle_state, "STOPPED")
        self.assertEqual(diag.chunks_emitted, 5)
        self.assertEqual(diag.buffer_occupancy, 5)
        self.assertEqual(diag.dropped_chunk_counter, 0)
        self.assertTrue(diag.is_healthy)


if __name__ == "__main__":
    unittest.main()

