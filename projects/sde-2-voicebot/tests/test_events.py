"""Unit test suite for Speech Events and SpeechEventProcessor.

Week 3 (Days 15-16) validation for SDE Team 2.
"""

from dataclasses import FrozenInstanceError
import math
import struct
import unittest
import uuid

from voicebot.device import MockAudioDeviceAdapter
from voicebot.events import (
    AudioEvent,
    AudioFrameEvent,
    EventStatistics,
    EventType,
    SpeechEndedEvent,
    SpeechEventProcessor,
    SpeechStartedEvent,
)
from voicebot.lifecycle import AudioLifecycleController
from voicebot.normalizer import AudioNormalizer
from voicebot.schemas import AudioChunk, AudioError, AudioFormat
from voicebot.vad import VoiceActivityDetector


class TestSpeechEvents(unittest.TestCase):
    """Test cases for speech events and the event processing pipeline."""

    def setUp(self) -> None:
        self.format_16k_mono = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        # 16000 Hz, 320 frames = 20ms per chunk
        self.frames_per_chunk = 320
        self.chunk_duration = 0.020  # 20ms
        self.vad = VoiceActivityDetector(energy_threshold=0.02, min_speech_duration_ms=100.0)
        self.normalizer = AudioNormalizer(target_peak=0.95)
        self.processor = SpeechEventProcessor(
            vad=self.vad,
            normalizer=self.normalizer,
            session_id="test-session-123",
            pre_roll_chunks=8,
        )

    def _make_silence_chunk(self, seq_id: int, timestamp: float) -> AudioChunk:
        """Create a 20ms pure silence chunk."""
        return AudioChunk(
            sequence_id=seq_id,
            timestamp=timestamp,
            audio_format=self.format_16k_mono,
            data=b"\x00" * (self.frames_per_chunk * 2),
        )

    def _make_speech_chunk(self, seq_id: int, timestamp: float, amp: int = 15000) -> AudioChunk:
        """Create a 20ms synthetic speech sine wave chunk."""
        samples = []
        for i in range(self.frames_per_chunk):
            val = int(amp * math.sin(2.0 * math.pi * 440.0 * (i / 16000.0)))
            samples.append(val)
        data = struct.pack(f"<{len(samples)}h", *samples)
        return AudioChunk(
            sequence_id=seq_id,
            timestamp=timestamp,
            audio_format=self.format_16k_mono,
            data=data,
        )

    def test_event_schemas_immutability_and_validation(self) -> None:
        """Verify AudioEvent and subclasses enforce frozen immutability and validate fields."""
        ev = SpeechStartedEvent(
            event_id="ev-1",
            event_type=EventType.SPEECH_STARTED,
            session_id="sess-1",
            correlation_id="corr-1",
            timestamp=0.0,
            sequence_number=0,
            onset_timestamp=0.0,
            initial_sequence_id=0,
        )

        # Immutability
        with self.assertRaises(FrozenInstanceError):
            ev.timestamp = 1.0  # type: ignore

        # Field validation
        with self.assertRaises(AudioError):
            SpeechStartedEvent(
                event_id="",  # Empty event_id
                event_type=EventType.SPEECH_STARTED,
                session_id="sess-1",
                correlation_id="corr-1",
                timestamp=0.0,
                sequence_number=0,
            )

        with self.assertRaises(AudioError):
            SpeechStartedEvent(
                event_id="ev-2",
                event_type=EventType.SPEECH_STARTED,
                session_id="",  # Empty session_id
                correlation_id="corr-1",
                timestamp=0.0,
                sequence_number=0,
            )

        with self.assertRaises(AudioError):
            SpeechStartedEvent(
                event_id="ev-3",
                event_type=EventType.SPEECH_STARTED,
                session_id="sess-1",
                correlation_id="",  # Empty correlation_id
                timestamp=0.0,
                sequence_number=0,
            )

    def test_silence_produces_no_speech_events(self) -> None:
        """Verify continuous silence emits zero speech events."""
        events = []
        for i in range(10):
            chunk = self._make_silence_chunk(i, i * self.chunk_duration)
            events.extend(self.processor.process_chunk(chunk))

        self.assertEqual(len(events), 0)
        self.assertEqual(self.processor.statistics.total_events_emitted, 0)
        self.assertFalse(self.processor.is_in_speech)
        self.assertIsNone(self.processor.active_correlation_id)

    def test_transient_noise_rejection(self) -> None:
        """Verify brief noise burst (< 100ms VAD threshold) does not emit speech events."""
        events = []
        # 1 silence chunk
        events.extend(self.processor.process_chunk(self._make_silence_chunk(0, 0.00)))
        # 2 speech chunks = 40ms (< 100ms required)
        events.extend(self.processor.process_chunk(self._make_speech_chunk(1, 0.02)))
        events.extend(self.processor.process_chunk(self._make_speech_chunk(2, 0.04)))
        # Silence resumes
        events.extend(self.processor.process_chunk(self._make_silence_chunk(3, 0.06)))
        events.extend(self.processor.process_chunk(self._make_silence_chunk(4, 0.08)))

        self.assertEqual(len(events), 0)
        self.assertFalse(self.processor.is_in_speech)
        self.assertIsNone(self.processor.active_correlation_id)

    def test_speech_onset_and_pre_roll_preservation(self) -> None:
        """Verify speech onset is confirmed and pre-roll frames are losslessly forwarded."""
        events: list[AudioEvent] = []

        # Stream 5 consecutive speech chunks (5 * 20ms = 100ms)
        # Chunks 0-3 accumulate duration (20ms, 40ms, 60ms, 80ms) -> stored in pre-roll
        # Chunk 4 hits 100ms -> triggers speech onset!
        for i in range(5):
            chunk = self._make_speech_chunk(i, i * self.chunk_duration)
            emitted = self.processor.process_chunk(chunk)
            events.extend(emitted)

        # Once confirmed, should emit: 1 SpeechStartedEvent + 5 AudioFrameEvents
        self.assertTrue(self.processor.is_in_speech)
        self.assertIsNotNone(self.processor.active_correlation_id)
        self.assertEqual(len(events), 6)

        # 1. First event must be SpeechStartedEvent
        self.assertIsInstance(events[0], SpeechStartedEvent)
        start_ev: SpeechStartedEvent = events[0]  # type: ignore
        self.assertEqual(start_ev.onset_timestamp, 0.0)
        self.assertEqual(start_ev.initial_sequence_id, 0)
        self.assertEqual(start_ev.session_id, "test-session-123")
        corr_id = start_ev.correlation_id

        # 2. Next 5 events must be AudioFrameEvents in exact order with consistent normalized RMS
        first_rms = events[1].rms_energy  # type: ignore
        for idx, ev in enumerate(events[1:], start=0):
            self.assertIsInstance(ev, AudioFrameEvent)
            frame_ev: AudioFrameEvent = ev  # type: ignore
            self.assertEqual(frame_ev.correlation_id, corr_id)
            self.assertEqual(frame_ev.session_id, "test-session-123")
            self.assertEqual(frame_ev.chunk_sequence_id, idx)
            self.assertEqual(frame_ev.sequence_number, idx + 1)
            self.assertTrue(frame_ev.is_speech)
            self.assertGreater(frame_ev.rms_energy, 0.0)
            self.assertAlmostEqual(frame_ev.rms_energy, first_rms, places=4)

    def test_speech_ended_on_silence_transition(self) -> None:
        """Verify speech ends cleanly with SpeechEndedEvent when energy ceases."""
        events = []
        # 5 speech chunks to trigger speech onset
        for i in range(5):
            events.extend(self.processor.process_chunk(self._make_speech_chunk(i, i * self.chunk_duration)))

        self.assertTrue(self.processor.is_in_speech)
        corr_id = self.processor.active_correlation_id

        # Feed silence chunk
        silence_chunk = self._make_silence_chunk(5, 5 * self.chunk_duration)
        end_events = self.processor.process_chunk(silence_chunk)

        self.assertEqual(len(end_events), 1)
        self.assertIsInstance(end_events[0], SpeechEndedEvent)
        end_ev: SpeechEndedEvent = end_events[0]  # type: ignore
        self.assertEqual(end_ev.correlation_id, corr_id)
        self.assertEqual(end_ev.session_id, "test-session-123")
        self.assertEqual(end_ev.total_frames, 5)
        self.assertAlmostEqual(end_ev.total_speech_duration_ms, 100.0, places=1)

        # Processor reset to idle
        self.assertFalse(self.processor.is_in_speech)
        self.assertIsNone(self.processor.active_correlation_id)

    def test_multiple_turns_generate_unique_correlation_ids(self) -> None:
        """Verify sequential utterances generate distinct correlation IDs."""
        # Turn 1
        turn1_events = []
        for i in range(5):
            turn1_events.extend(self.processor.process_chunk(self._make_speech_chunk(i, i * self.chunk_duration)))
        turn1_events.extend(self.processor.process_chunk(self._make_silence_chunk(5, 0.10)))

        corr_id_1 = turn1_events[0].correlation_id

        # Turn 2 (offset at sequence 10, timestamp 0.20)
        turn2_events = []
        for i in range(5):
            turn2_events.extend(
                self.processor.process_chunk(self._make_speech_chunk(10 + i, 0.20 + (i * self.chunk_duration)))
            )
        turn2_events.extend(self.processor.process_chunk(self._make_silence_chunk(15, 0.30)))

        corr_id_2 = turn2_events[0].correlation_id

        self.assertNotEqual(corr_id_1, corr_id_2)
        self.assertEqual(turn1_events[0].session_id, turn2_events[0].session_id)
        self.assertEqual(self.processor.statistics.total_speech_turns, 2)

    def test_flush_handles_active_speech_safely(self) -> None:
        """Verify flush() emits SpeechEndedEvent if stream terminates mid-speech."""
        # Start speech but do not send silence
        for i in range(5):
            self.processor.process_chunk(self._make_speech_chunk(i, i * self.chunk_duration))

        self.assertTrue(self.processor.is_in_speech)
        corr_id = self.processor.active_correlation_id

        # Stream abruptly stops
        flushed_events = self.processor.flush()

        self.assertEqual(len(flushed_events), 1)
        self.assertIsInstance(flushed_events[0], SpeechEndedEvent)
        self.assertEqual(flushed_events[0].correlation_id, corr_id)
        self.assertFalse(self.processor.is_in_speech)
        self.assertIsNone(self.processor.active_correlation_id)
        # Verify VAD debouncing state is reset so debouncer is active for subsequent stream
        self.assertEqual(self.vad.continuous_speech_duration_ms, 0.0)

    def test_integration_with_lifecycle_controller_session_id(self) -> None:
        """Verify processor integrates with AudioLifecycleController.session_id."""
        adapter = MockAudioDeviceAdapter()
        adapter.request_permission()
        controller = AudioLifecycleController(adapter)
        controller.start()

        self.assertIsNotNone(controller.session_id)
        proc = SpeechEventProcessor(vad=self.vad, session_id=controller.session_id)

        events = []
        for i in range(5):
            events.extend(proc.process_chunk(self._make_speech_chunk(i, i * self.chunk_duration)))

        self.assertGreater(len(events), 0)
        for ev in events:
            self.assertEqual(ev.session_id, controller.session_id)

        controller.stop()

    def test_process_stream_generator(self) -> None:
        """Verify process_stream yields all events in monotonic sequence."""
        chunks = [
            self._make_silence_chunk(0, 0.0),
            self._make_speech_chunk(1, 0.02),
            self._make_speech_chunk(2, 0.04),
            self._make_speech_chunk(3, 0.06),
            self._make_speech_chunk(4, 0.08),
            self._make_speech_chunk(5, 0.10),
            self._make_silence_chunk(6, 0.12),
        ]

        events = list(self.processor.process_stream(chunks))
        # 1 start + 5 frames + 1 end = 7 events
        self.assertEqual(len(events), 7)
        seq_nums = [e.sequence_number for e in events]
        self.assertEqual(seq_nums, list(range(len(events))))


if __name__ == "__main__":
    unittest.main()

