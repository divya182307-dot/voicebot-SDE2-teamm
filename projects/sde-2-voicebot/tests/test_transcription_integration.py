"""Integration test suite for Transcription Bridge and STT module integration.

Week 3 (Days 19-20) validation for SDE Team 2.
Tests end-to-end transcription flow, event ordering, sequence gap telemetry,
silence suppression, click noise rejection, and correlation ID preservation.
"""

from __future__ import annotations

import asyncio
import math
import struct
import unittest
import uuid

from voicebot.events import (
    AudioEvent,
    AudioFrameEvent,
    EventType,
    SpeechEndedEvent,
    SpeechEventProcessor,
    SpeechStartedEvent,
)
from voicebot.normalizer import AudioNormalizer
from voicebot.schemas import AudioChunk, AudioError, AudioFormat
from voicebot.transcription_bridge import TranscriptionBridge
from voicebot.vad import VoiceActivityDetector

# Import teammate STT contracts
from src.voice.accumulator import AccumulatorConfig, SegmentAccumulator
from src.voice.adapter import AudioConfig, TranscriberConfig, TranscriberState
from src.voice.fake_transcriber import FakeTranscriber, FakeUtterance
from src.voice.schemas import TranscriptEvent, TranscriptEventType


def create_pcm_chunk(
    sequence_id: int,
    amplitude: float = 0.5,
    sample_rate: int = 16000,
    duration_ms: int = 20,
    frequency: float = 440.0,
) -> AudioChunk:
    """Helper to generate a deterministic synthetic 16kHz 16-bit mono PCM chunk."""
    num_samples = int(sample_rate * (duration_ms / 1000.0))
    samples = []
    for i in range(num_samples):
        if amplitude == 0.0:
            val = 0
        else:
            t = float(i) / sample_rate
            val = int(amplitude * 32767.0 * math.sin(2.0 * math.pi * frequency * t))
        samples.append(max(-32768, min(32767, val)))

    raw_data = struct.pack(f"<{len(samples)}h", *samples)
    fmt = AudioFormat(sample_rate=sample_rate, channels=1, sample_width=2)
    return AudioChunk(
        sequence_id=sequence_id,
        timestamp=float(sequence_id * duration_ms) / 1000.0,
        audio_format=fmt,
        data=raw_data,
    )


class TestTranscriptionBridgeInitialization(unittest.TestCase):
    """Test cases for TranscriptionBridge construction and validation."""

    def test_successful_initialization(self):
        transcriber = FakeTranscriber(session_id="session-init-1")
        acc = SegmentAccumulator(session_id="session-init-1")
        bridge = TranscriptionBridge(transcriber=transcriber, accumulator=acc)

        self.assertEqual(bridge.session_id, "session-init-1")
        self.assertIs(bridge.transcriber, transcriber)
        self.assertIs(bridge.accumulator, acc)
        self.assertFalse(bridge.is_in_speech)
        self.assertIsNone(bridge.active_correlation_id)

    def test_initialization_without_transcriber_raises_error(self):
        with self.assertRaises(AudioError):
            TranscriptionBridge(transcriber=None)  # type: ignore

    def test_custom_session_id_override(self):
        transcriber = FakeTranscriber(session_id="session-default")
        bridge = TranscriptionBridge(transcriber=transcriber, session_id="session-custom")
        self.assertEqual(bridge.session_id, "session-custom")


class TestEndToEndTranscriptionFlow(unittest.TestCase):
    """End-to-end integration tests connecting Audio Pipeline -> VAD -> Bridge -> FakeTranscriber -> Accumulator."""

    def test_end_to_end_mock_transcription(self):
        """Full pipeline test verifying speech recognition and accumulation."""

        async def _run():
            session_id = "test-session-e2e"
            script_text = "What is the difference between processes and threads?"
            transcriber = FakeTranscriber(
                session_id=session_id,
                script=[script_text],
            )
            accumulator = SegmentAccumulator(session_id=session_id)
            bridge = TranscriptionBridge(transcriber=transcriber, accumulator=accumulator)

            vad = VoiceActivityDetector(energy_threshold=0.02, min_speech_duration_ms=100.0)
            normalizer = AudioNormalizer(target_peak=0.95)
            processor = SpeechEventProcessor(vad=vad, normalizer=normalizer, session_id=session_id)

            # 1. Warm-up silence (100ms = 5 chunks)
            for i in range(5):
                chunk = create_pcm_chunk(sequence_id=i, amplitude=0.0)
                events = processor.process_chunk(chunk)
                await bridge.process_event_stream(events)

            # 2. Human speech tone (800ms = 40 chunks)
            for i in range(5, 45):
                chunk = create_pcm_chunk(sequence_id=i, amplitude=0.4, frequency=440.0)
                events = processor.process_chunk(chunk)
                await bridge.process_event_stream(events)

            # 3. Trailing silence to trigger hangover expiration (500ms = 25 chunks)
            for i in range(45, 70):
                chunk = create_pcm_chunk(sequence_id=i, amplitude=0.0)
                events = processor.process_chunk(chunk)
                await bridge.process_event_stream(events)

            # Verify bridge state
            self.assertFalse(bridge.is_in_speech)
            telemetry = bridge.get_telemetry()
            self.assertEqual(telemetry["speech_turns_completed"], 1)
            self.assertGreater(telemetry["frames_processed"], 0)
            self.assertGreater(telemetry["bytes_forwarded"], 0)

            # Verify accumulator gathered locked transcript
            self.assertFalse(accumulator.is_empty)
            self.assertEqual(len(accumulator.final_segments), 1)
            self.assertEqual(accumulator.final_segments[0].text, script_text)
            self.assertEqual(accumulator.get_final_text(), script_text)

        asyncio.run(_run())

    def test_transcript_event_ordering_on_speech_ended(self):
        """Verify strict chronological ordering of transcript events emitted during a turn."""

        async def _run():
            session_id = "test-session-ordering"
            transcriber = FakeTranscriber(session_id=session_id, script=["Ordering verification."])
            bridge = TranscriptionBridge(transcriber=transcriber)

            correlation_id = str(uuid.uuid4())

            # 1. Dispatch SpeechStartedEvent
            started_event = SpeechStartedEvent(
                event_id=str(uuid.uuid4()),
                event_type=EventType.SPEECH_STARTED,
                session_id=session_id,
                correlation_id=correlation_id,
                timestamp=0.0,
                sequence_number=1,
                onset_timestamp=0.0,
                initial_sequence_id=0,
            )
            await bridge.handle_audio_event(started_event)
            self.assertTrue(bridge.is_in_speech)
            self.assertEqual(bridge.active_correlation_id, correlation_id)

            # 2. Dispatch 10 AudioFrameEvents (200ms)
            for i in range(10):
                chunk = create_pcm_chunk(sequence_id=i, amplitude=0.3)
                frame_event = AudioFrameEvent(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.AUDIO_FRAME,
                    session_id=session_id,
                    correlation_id=correlation_id,
                    timestamp=float(i * 0.02),
                    sequence_number=i + 2,
                    chunk=chunk,
                    chunk_sequence_id=i,
                )
                await bridge.handle_audio_event(frame_event)

            # 3. Dispatch SpeechEndedEvent
            ended_event = SpeechEndedEvent(
                event_id=str(uuid.uuid4()),
                event_type=EventType.SPEECH_ENDED,
                session_id=session_id,
                correlation_id=correlation_id,
                timestamp=0.25,
                sequence_number=12,
                offset_timestamp=0.25,
                total_speech_duration_ms=200.0,
                total_frames=10,
            )
            await bridge.handle_audio_event(ended_event)
            self.assertFalse(bridge.is_in_speech)

            # Verify emitted TranscriptEvents ordering
            transcript_events = bridge.get_transcript_events()
            event_types = [e.event_type for e in transcript_events]

            # SPEECH_STARTED must precede FINAL_TRANSCRIPT, which must precede SPEECH_ENDED
            self.assertIn(TranscriptEventType.SPEECH_STARTED, event_types)
            self.assertIn(TranscriptEventType.FINAL_TRANSCRIPT, event_types)
            self.assertIn(TranscriptEventType.SPEECH_ENDED, event_types)

            started_idx = event_types.index(TranscriptEventType.SPEECH_STARTED)
            final_idx = event_types.index(TranscriptEventType.FINAL_TRANSCRIPT)
            ended_idx = event_types.index(TranscriptEventType.SPEECH_ENDED)

            self.assertLess(started_idx, final_idx)
            self.assertLess(final_idx, ended_idx)

        asyncio.run(_run())


class TestSequenceGapsAndSilenceResilience(unittest.TestCase):
    """Tests verifying sequence-gap telemetry, frozen immutability, silence, and click rejection."""

    def test_sequence_gaps_stored_in_telemetry_without_event_mutation(self):
        """Gaps in chunk_sequence_id are recorded in bridge telemetry, leaving frozen events untouched."""

        async def _run():
            session_id = "test-session-gaps"
            transcriber = FakeTranscriber(session_id=session_id, script=["Gap resilience test."])
            bridge = TranscriptionBridge(transcriber=transcriber)
            correlation_id = str(uuid.uuid4())

            await bridge.handle_audio_event(
                SpeechStartedEvent(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.SPEECH_STARTED,
                    session_id=session_id,
                    correlation_id=correlation_id,
                    timestamp=0.0,
                    sequence_number=1,
                    initial_sequence_id=0,
                )
            )

            # Send chunk 0 and 1
            for seq in [0, 1]:
                chunk = create_pcm_chunk(sequence_id=seq, amplitude=0.3)
                event = AudioFrameEvent(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.AUDIO_FRAME,
                    session_id=session_id,
                    correlation_id=correlation_id,
                    timestamp=float(seq * 0.02),
                    sequence_number=seq + 2,
                    chunk=chunk,
                    chunk_sequence_id=seq,
                    metadata={},  # Empty metadata
                )
                await bridge.handle_audio_event(event)

            # Gap! Skip chunks 2 and 3, send chunk 4
            chunk_4 = create_pcm_chunk(sequence_id=4, amplitude=0.3)
            gap_event = AudioFrameEvent(
                event_id=str(uuid.uuid4()),
                event_type=EventType.AUDIO_FRAME,
                session_id=session_id,
                correlation_id=correlation_id,
                timestamp=0.08,
                sequence_number=4,
                chunk=chunk_4,
                chunk_sequence_id=4,
                metadata={},
            )
            await bridge.handle_audio_event(gap_event)

            # Assert frozen event metadata was NOT mutated
            self.assertEqual(gap_event.metadata, {})

            # Assert bridge telemetry correctly captured the gap
            telemetry = bridge.get_telemetry()
            self.assertEqual(telemetry["gap_count"], 1)
            self.assertEqual(telemetry["missing_chunks_total"], 2)
            self.assertEqual(len(telemetry["gaps"]), 1)
            self.assertEqual(telemetry["gaps"][0]["expected_sequence_id"], 2)
            self.assertEqual(telemetry["gaps"][0]["received_sequence_id"], 4)
            self.assertEqual(telemetry["gaps"][0]["missing_chunks"], 2)

            # End utterance cleanly
            await bridge.handle_audio_event(
                SpeechEndedEvent(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.SPEECH_ENDED,
                    session_id=session_id,
                    correlation_id=correlation_id,
                    timestamp=0.1,
                    sequence_number=5,
                )
            )

        asyncio.run(_run())

    def test_correlation_id_attached_to_all_transcript_events(self):
        """Verify correlation_id is present in metadata for every emitted TranscriptEvent."""

        async def _run():
            session_id = "test-session-corr"
            transcriber = FakeTranscriber(session_id=session_id, script=["Correlation ID test."])
            bridge = TranscriptionBridge(transcriber=transcriber)
            expected_correlation_id = "test-corr-uuid-7777"

            await bridge.handle_audio_event(
                SpeechStartedEvent(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.SPEECH_STARTED,
                    session_id=session_id,
                    correlation_id=expected_correlation_id,
                    timestamp=0.0,
                    sequence_number=1,
                )
            )

            chunk = create_pcm_chunk(sequence_id=0, amplitude=0.3)
            await bridge.handle_audio_event(
                AudioFrameEvent(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.AUDIO_FRAME,
                    session_id=session_id,
                    correlation_id=expected_correlation_id,
                    timestamp=0.02,
                    sequence_number=2,
                    chunk=chunk,
                    chunk_sequence_id=0,
                )
            )

            await bridge.handle_audio_event(
                SpeechEndedEvent(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.SPEECH_ENDED,
                    session_id=session_id,
                    correlation_id=expected_correlation_id,
                    timestamp=0.05,
                    sequence_number=3,
                )
            )

            transcript_events = bridge.get_transcript_events()
            self.assertGreater(len(transcript_events), 0)

            for event in transcript_events:
                self.assertIsNotNone(event.metadata)
                self.assertIn("correlation_id", event.metadata)
                self.assertEqual(event.metadata["correlation_id"], expected_correlation_id)

        asyncio.run(_run())

    def test_silence_suppression_produces_zero_transcripts(self):
        """Verify that pure silence chunks produce zero audio frames and zero transcription events."""

        async def _run():
            session_id = "test-silence"
            transcriber = FakeTranscriber(session_id=session_id)
            accumulator = SegmentAccumulator(session_id=session_id)
            bridge = TranscriptionBridge(transcriber=transcriber, accumulator=accumulator)

            vad = VoiceActivityDetector(energy_threshold=0.02, min_speech_duration_ms=100.0)
            processor = SpeechEventProcessor(vad=vad, session_id=session_id)

            # Feed 500ms of pure silence (25 chunks)
            for i in range(25):
                chunk = create_pcm_chunk(sequence_id=i, amplitude=0.0)
                events = processor.process_chunk(chunk)
                await bridge.process_event_stream(events)

            telemetry = bridge.get_telemetry()
            self.assertEqual(telemetry["frames_processed"], 0)
            self.assertEqual(telemetry["bytes_forwarded"], 0)
            self.assertEqual(telemetry["speech_turns_completed"], 0)
            self.assertEqual(len(bridge.get_transcript_events()), 0)
            self.assertTrue(accumulator.is_empty)

        asyncio.run(_run())

    def test_false_trigger_clicks_rejected_by_vad(self):
        """Verify that short click impulses (< 100ms) are suppressed by VAD and never reach transcriber."""

        async def _run():
            session_id = "test-click"
            transcriber = FakeTranscriber(session_id=session_id)
            bridge = TranscriptionBridge(transcriber=transcriber)

            vad = VoiceActivityDetector(energy_threshold=0.02, min_speech_duration_ms=100.0)
            processor = SpeechEventProcessor(vad=vad, session_id=session_id)

            # Chunk 0: Silence
            events_0 = processor.process_chunk(create_pcm_chunk(sequence_id=0, amplitude=0.0))
            await bridge.process_event_stream(events_0)

            # Chunk 1: Sudden 20ms click impulse (high energy, but only 1 chunk < 100ms debouncing window)
            click_chunk = create_pcm_chunk(sequence_id=1, amplitude=0.8)
            events_1 = processor.process_chunk(click_chunk)
            await bridge.process_event_stream(events_1)

            # Chunks 2-10: Immediate silence
            for i in range(2, 11):
                events = processor.process_chunk(create_pcm_chunk(sequence_id=i, amplitude=0.0))
                await bridge.process_event_stream(events)

            telemetry = bridge.get_telemetry()
            self.assertEqual(telemetry["frames_processed"], 0)
            self.assertEqual(telemetry["speech_turns_completed"], 0)
            self.assertEqual(len(bridge.get_transcript_events()), 0)

    def test_multiple_utterances_sequential_accumulation(self):
        """Verify back-to-back speech utterances accumulate cleanly into multiple segments."""

        async def _run():
            session_id = "test-multi-turn"
            script = ["How does Dijkstra algorithm work?", "What is its time complexity?"]
            transcriber = FakeTranscriber(session_id=session_id, script=script)
            accumulator = SegmentAccumulator(session_id=session_id)
            bridge = TranscriptionBridge(transcriber=transcriber, accumulator=accumulator)

            vad = VoiceActivityDetector(energy_threshold=0.02, min_speech_duration_ms=100.0)
            processor = SpeechEventProcessor(vad=vad, session_id=session_id)

            seq = 0

            # Utterance 1
            for _ in range(30):  # 600ms speech
                events = processor.process_chunk(create_pcm_chunk(sequence_id=seq, amplitude=0.4))
                await bridge.process_event_stream(events)
                seq += 1

            for _ in range(25):  # 500ms silence hangover
                events = processor.process_chunk(create_pcm_chunk(sequence_id=seq, amplitude=0.0))
                await bridge.process_event_stream(events)
                seq += 1

            self.assertEqual(bridge.get_telemetry()["speech_turns_completed"], 1)

            # Utterance 2
            for _ in range(30):  # 600ms speech
                events = processor.process_chunk(create_pcm_chunk(sequence_id=seq, amplitude=0.4))
                await bridge.process_event_stream(events)
                seq += 1

            for _ in range(25):  # 500ms silence hangover
                events = processor.process_chunk(create_pcm_chunk(sequence_id=seq, amplitude=0.0))
                await bridge.process_event_stream(events)
                seq += 1

            self.assertEqual(bridge.get_telemetry()["speech_turns_completed"], 2)
            self.assertEqual(len(accumulator.final_segments), 2)
            self.assertEqual(accumulator.final_segments[0].text, script[0])
            self.assertEqual(accumulator.final_segments[1].text, script[1])

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
