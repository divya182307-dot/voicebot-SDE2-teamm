"""Stress and endurance testing for SDE Team 2 (Week 4, Days 25-27).

Covers:
1. Long-session endurance (5,000+ chunks, sustained streaming without degradation).
2. Memory stability across prolonged multi-turn sessions (asserting memory flattening).
3. Latency stability under continuous load (no cumulative latency drift).
4. Bounded buffer behavior under extreme backpressure (overflow with thousands of chunks).
5. Rapid silence/speech alternating cycles (50+ burst cycles stressing VAD transitions).
6. Repeated mid-stream device failures and auto-reconnection (30+ failure/reconnect cycles).
7. Rapid session cancellation stress (25+ cancel/flush cycles without resource leaks).
8. End-to-end integration stress with TranscriptionBridge (multi-turn sustained handoff).
"""

from __future__ import annotations

import asyncio
import math
import struct
import time
import tracemalloc
import pytest

from voicebot.buffer import BoundedAudioBuffer, DropStrategy
from voicebot.device import (
    AudioDevice,
    AudioDeviceAdapter,
    MockAudioDeviceAdapter,
    PermissionState,
)
from voicebot.events import EventType, SpeechEventProcessor
from voicebot.lifecycle import AudioLifecycleController, LifecycleState
from voicebot.normalizer import AudioNormalizer
from voicebot.profiler import AudioPipelineProfiler
from voicebot.schemas import AudioChunk, AudioError, AudioFormat
from voicebot.transcription_bridge import TranscriptionBridge
from voicebot.vad import VoiceActivityDetector

# STT contracts
from src.voice.accumulator import SegmentAccumulator
from src.voice.fake_transcriber import FakeTranscriber


@pytest.fixture
def standard_format() -> AudioFormat:
    """Standard 16kHz mono 16-bit PCM format."""
    return AudioFormat(sample_rate=16000, channels=1, sample_width=2)


def make_chunk(
    seq: int,
    fmt: AudioFormat,
    amplitude: float = 0.35,
    duration_ms: int = 20,
) -> AudioChunk:
    """Generate a deterministic synthetic audio chunk for stress testing."""
    frame_count = int(fmt.sample_rate * (duration_ms / 1000.0))
    samples: list[int] = []
    freq = 440.0

    for i in range(frame_count):
        if amplitude > 0:
            val = int(amplitude * 32767.0 * math.sin(2.0 * math.pi * freq * (i / fmt.sample_rate)))
        else:
            val = 0
        samples.append(max(-32768, min(32767, val)))

    raw_data = struct.pack(f"<{len(samples)}h", *samples)
    return AudioChunk(
        sequence_id=seq,
        timestamp=float(seq * duration_ms) / 1000.0,
        audio_format=fmt,
        data=raw_data,
    )


class TestLongSessionStress:
    """Endurance tests for long, sustained audio capture sessions."""

    def test_long_session_5000_chunks_endurance(self, standard_format: AudioFormat) -> None:
        """Sustained streaming of 5,000 chunks (100 seconds of audio) must complete without errors."""
        normalizer = AudioNormalizer(target_peak=0.95)
        vad = VoiceActivityDetector(energy_threshold=0.02, min_speech_duration_ms=50.0)
        buffer = BoundedAudioBuffer(max_chunks=20, drop_strategy=DropStrategy.DROP_OLDEST)
        processor = SpeechEventProcessor(vad=vad, normalizer=normalizer, session_id="stress-long-session")

        total_chunks = 5000
        events_emitted = 0

        t_start = time.perf_counter()
        for seq in range(total_chunks):
            # Alternating pattern: 30 chunks speech, 20 chunks silence
            is_speech = (seq % 50) < 30
            amp = 0.35 if is_speech else 0.0
            chunk = make_chunk(seq, standard_format, amplitude=amp)

            norm_chunk = normalizer.normalize_chunk(chunk)
            _ = vad.process_chunk(norm_chunk)
            buffer.push(norm_chunk)
            events = processor.process_chunk(norm_chunk)
            events_emitted += len(events)

        t_elapsed = time.perf_counter() - t_start

        assert buffer.current_occupancy == 20
        assert buffer.dropped_chunk_counter == (total_chunks - 20)
        assert events_emitted > 0
        # 5,000 chunks processed in synthetic mock mode should take well under 10 seconds
        assert t_elapsed < 10.0
        assert t_elapsed > 0.0

    def test_memory_stability_across_long_session(self, standard_format: AudioFormat) -> None:
        """Memory heap must stabilize after warm-up and not grow continuously over 3,000 chunks."""
        tracemalloc.start()
        tracemalloc.reset_peak()

        try:
            normalizer = AudioNormalizer(target_peak=0.95)
            vad = VoiceActivityDetector(energy_threshold=0.02)
            buffer = BoundedAudioBuffer(max_chunks=15, drop_strategy=DropStrategy.DROP_OLDEST)
            processor = SpeechEventProcessor(vad=vad, normalizer=normalizer, session_id="stress-memory-stability")

            # Warm-up phase: 200 chunks to allow Python object allocation / interning
            for seq in range(200):
                chunk = make_chunk(seq, standard_format, amplitude=0.35 if (seq % 40) < 20 else 0.0)
                norm_chunk = normalizer.normalize_chunk(chunk)
                _ = vad.process_chunk(norm_chunk)
                buffer.push(norm_chunk)
                _ = processor.process_chunk(norm_chunk)

            mem_after_warmup, _ = tracemalloc.get_traced_memory()

            # Main endurance phase: 2,800 additional chunks (3,000 total)
            for seq in range(200, 3000):
                chunk = make_chunk(seq, standard_format, amplitude=0.35 if (seq % 40) < 20 else 0.0)
                norm_chunk = normalizer.normalize_chunk(chunk)
                _ = vad.process_chunk(norm_chunk)
                buffer.push(norm_chunk)
                _ = processor.process_chunk(norm_chunk)

            mem_final, peak_mem = tracemalloc.get_traced_memory()
            growth_bytes = mem_final - mem_after_warmup

            # Over 2,800 active chunks with a bounded buffer of 15, heap growth must be strictly bounded (< 96 KB)
            assert growth_bytes < 96 * 1024, f"Memory growth too high: {growth_bytes / 1024:.2f} KB"
        finally:
            tracemalloc.stop()

    def test_latency_stability_under_load(self, standard_format: AudioFormat) -> None:
        """Per-chunk latency must not exhibit exponential drift across 2,000 chunks."""
        normalizer = AudioNormalizer(target_peak=0.95)
        vad = VoiceActivityDetector(energy_threshold=0.02)
        buffer = BoundedAudioBuffer(max_chunks=10, drop_strategy=DropStrategy.DROP_OLDEST)
        processor = SpeechEventProcessor(vad=vad, normalizer=normalizer, session_id="stress-latency-stability")

        first_block_durations_ns: list[int] = []
        last_block_durations_ns: list[int] = []

        for seq in range(2000):
            chunk = make_chunk(seq, standard_format, amplitude=0.35 if (seq % 40) < 20 else 0.0)

            t0 = time.perf_counter_ns()
            norm_chunk = normalizer.normalize_chunk(chunk)
            _ = vad.process_chunk(norm_chunk)
            buffer.push(norm_chunk)
            _ = processor.process_chunk(norm_chunk)
            duration_ns = time.perf_counter_ns() - t0

            if 100 <= seq < 300:
                first_block_durations_ns.append(duration_ns)
            elif 1800 <= seq < 2000:
                last_block_durations_ns.append(duration_ns)

        avg_first_ms = (sum(first_block_durations_ns) / len(first_block_durations_ns)) / 1_000_000.0
        avg_last_ms = (sum(last_block_durations_ns) / len(last_block_durations_ns)) / 1_000_000.0

        # Assert no severe latency degradation (last block average must be within 3.5x of first block average)
        assert avg_last_ms < max(1.0, avg_first_ms * 3.5)


class TestBoundedBufferPressureStress:
    """Stress tests verifying buffer integrity and drop strategies under extreme overflow."""

    def test_extreme_overflow_drop_oldest_1000_chunks(self, standard_format: AudioFormat) -> None:
        """Pushes 1,000 chunks into a buffer of capacity 10 with DROP_OLDEST."""
        buffer = BoundedAudioBuffer(max_chunks=10, drop_strategy=DropStrategy.DROP_OLDEST)

        for seq in range(1000):
            chunk = make_chunk(seq, standard_format)
            buffer.push(chunk)

        assert buffer.current_occupancy == 10
        assert buffer.dropped_chunk_counter == 990
        # The oldest chunk retained should be chunk sequence 990 (popped via FIFO pull)
        oldest = buffer.pull()
        assert oldest is not None
        assert oldest.sequence_id == 990

    def test_extreme_overflow_drop_newest_1000_chunks(self, standard_format: AudioFormat) -> None:
        """Pushes 1,000 chunks into a buffer of capacity 10 with DROP_NEWEST."""
        buffer = BoundedAudioBuffer(max_chunks=10, drop_strategy=DropStrategy.DROP_NEWEST)

        for seq in range(1000):
            chunk = make_chunk(seq, standard_format)
            buffer.push(chunk)

        assert buffer.current_occupancy == 10
        assert buffer.dropped_chunk_counter == 990
        # The oldest chunk retained should be chunk sequence 0 (the first one pushed)
        oldest = buffer.pull()
        assert oldest is not None
        assert oldest.sequence_id == 0

    def test_rapid_alternating_burst_pop_push(self, standard_format: AudioFormat) -> None:
        """Rapid interleaved push and pull operations across 1,000 cycles."""
        buffer = BoundedAudioBuffer(max_chunks=5, drop_strategy=DropStrategy.DROP_OLDEST)

        pulled_count = 0
        for seq in range(1000):
            buffer.push(make_chunk(seq, standard_format))
            if seq % 2 == 0:
                pulled = buffer.pull()
                if pulled is not None:
                    pulled_count += 1

        assert buffer.current_occupancy <= 5
        assert pulled_count == 500


class TestSilenceSpeechCyclingStress:
    """Stress tests for rapid transitions between voice activity and silence."""

    def test_rapid_speech_silence_50_burst_cycles(self, standard_format: AudioFormat) -> None:
        """50 rapid cycles between silence and speech bursts (1,000 chunks total)."""
        vad = VoiceActivityDetector(energy_threshold=0.02, min_speech_duration_ms=40.0)
        normalizer = AudioNormalizer(target_peak=0.95)
        processor = SpeechEventProcessor(
            vad=vad,
            normalizer=normalizer,
            session_id="stress-rapid-bursts",
            pre_roll_chunks=3,
        )

        total_started = 0
        total_ended = 0
        total_frames = 0

        # 50 bursts: 10 chunks speech, 10 chunks silence per burst (20 chunks * 50 = 1000 chunks)
        for burst in range(50):
            for i in range(10):
                seq = burst * 20 + i
                chunk = make_chunk(seq, standard_format, amplitude=0.4)
                events = processor.process_chunk(chunk)
                for ev in events:
                    if ev.event_type == EventType.SPEECH_STARTED:
                        total_started += 1
                    elif ev.event_type == EventType.AUDIO_FRAME:
                        total_frames += 1

            for i in range(10):
                seq = burst * 20 + 10 + i
                chunk = make_chunk(seq, standard_format, amplitude=0.0)
                events = processor.process_chunk(chunk)
                for ev in events:
                    if ev.event_type == EventType.SPEECH_ENDED:
                        total_ended += 1

        # Every speech started burst must be closed by a speech ended event
        assert total_started == 50
        assert total_ended == 50
        assert total_frames > 0


class TestDeviceFailureAndRecoveryStress:
    """Stress tests for repeated mid-stream device failures, reconnects, and cancellations."""

    def test_repeated_device_disconnect_and_reconnect_30_cycles(self) -> None:
        """30 consecutive mid-stream device disconnect and fallback reconnect cycles."""
        primary_dev = AudioDevice("mic-primary", "Primary USB Mic", channels=1, default_sample_rate=16000, is_default=True)
        fallback_dev = AudioDevice("mic-fallback", "Fallback Analog Mic", channels=1, default_sample_rate=16000, is_default=False)

        adapter = MockAudioDeviceAdapter(
            devices=[primary_dev, fallback_dev],
            initial_permission=PermissionState.GRANTED,
        )
        adapter.select_device("mic-primary")
        controller = AudioLifecycleController(adapter)
        controller.start()
        assert controller.state == LifecycleState.RECORDING

        for cycle in range(30):
            # Mid-stream disconnect of primary device
            adapter.disconnect_device("mic-primary")

            # Fallback reconnect
            reconnect_success = controller.reconnect(fallback_device_id="mic-fallback")
            assert reconnect_success is True
            assert adapter.get_selected_device().device_id == "mic-fallback"
            assert controller.successful_reconnects == cycle * 2 + 1

            # Restore primary device to available list and switch back
            adapter.reconnect_device(primary_dev)
            restore_success = controller.reconnect(fallback_device_id="mic-primary")
            assert restore_success is True
            assert adapter.get_selected_device().device_id == "mic-primary"
            assert controller.successful_reconnects == cycle * 2 + 2

        controller.stop()
        assert controller.state == LifecycleState.STOPPED

    def test_rapid_cancellation_stress_25_cycles(self, standard_format: AudioFormat) -> None:
        """25 consecutive start -> capture -> cancel cycles, verifying clean buffer flush."""
        primary_dev = AudioDevice("mic-primary", "Primary USB Mic", channels=1, default_sample_rate=16000, is_default=True)
        adapter = MockAudioDeviceAdapter(devices=[primary_dev], initial_permission=PermissionState.GRANTED)

        for cycle in range(25):
            controller = AudioLifecycleController(adapter)
            controller.start()
            assert controller.state == LifecycleState.RECORDING

            buffer = BoundedAudioBuffer(max_chunks=10, drop_strategy=DropStrategy.DROP_OLDEST)
            # Push 5 chunks into buffer
            for i in range(5):
                buffer.push(make_chunk(i, standard_format))
            assert buffer.current_occupancy == 5

            # Feed 2 chunks from capture stream
            stream = controller.capture_stream(chunk_count=10, frames_per_chunk=4)
            _ = next(stream)
            _ = next(stream)

            # Rapid cancellation mid-session with buffer
            controller.cancel(buffer=buffer)
            assert controller.state == LifecycleState.CANCELLED
            assert controller.is_cancelled is True

            # Verify buffer is cleared
            assert buffer.current_occupancy == 0
            assert buffer.pull() is None

    def test_reconnect_failure_exhaustion(self) -> None:
        """When fallback device is unavailable, reconnect must return False without deadlock."""
        primary_dev = AudioDevice("mic-solo", "Only Mic Available", channels=1, default_sample_rate=16000, is_default=True)
        adapter = MockAudioDeviceAdapter(
            devices=[primary_dev],
            initial_permission=PermissionState.GRANTED,
        )
        controller = AudioLifecycleController(adapter)
        controller.start()

        # Simulate device loss: remove all devices and mark unavailable
        adapter.disconnect_device("mic-solo")
        adapter.set_devices([])

        # Attempt reconnect with non-existent device
        reconnect_success = controller.reconnect(fallback_device_id="ghost-mic")
        assert reconnect_success is False
        assert controller.successful_reconnects == 0

        # Clean cancellation after failure
        controller.cancel()
        assert controller.state == LifecycleState.CANCELLED


class TestEndToEndStressWithTranscription:
    """Stress tests combining the full audio pipeline with transcription bridge across multi-turn sessions."""

    def test_e2e_stress_multi_turn_1000_chunks(self, standard_format: AudioFormat) -> None:
        """Runs a 1,000-chunk multi-turn session with TranscriptionBridge."""
        session_id = "stress-e2e-session-1"
        normalizer = AudioNormalizer(target_peak=0.95)
        vad = VoiceActivityDetector(energy_threshold=0.02, min_speech_duration_ms=40.0)
        processor = SpeechEventProcessor(
            vad=vad,
            normalizer=normalizer,
            session_id=session_id,
            pre_roll_chunks=4,
        )

        script = [
            "First speech utterance in stress test.",
            "Second follow-up utterance under continuous streaming.",
            "Third distinct question in this conversation.",
        ]
        transcriber = FakeTranscriber(session_id=session_id, script=script)
        accumulator = SegmentAccumulator(session_id=session_id)
        bridge = TranscriptionBridge(transcriber=transcriber, accumulator=accumulator)

        async def _run_stream():
            total_chunks = 1000
            for seq in range(total_chunks):
                # 3 speech segments: chunks [100..200], [400..500], [700..800]
                is_speech = (100 <= seq < 200) or (400 <= seq < 500) or (700 <= seq < 800)
                amp = 0.35 if is_speech else 0.0
                chunk = make_chunk(seq, standard_format, amplitude=amp)

                norm_chunk = normalizer.normalize_chunk(chunk)
                events = processor.process_chunk(norm_chunk)
                for ev in events:
                    await bridge.handle_audio_event(ev)

        asyncio.run(_run_stream())

        telemetry = bridge.get_telemetry()
        assert telemetry["speech_turns_completed"] >= 3
        assert telemetry["gap_count"] == 0
        assert telemetry["missing_chunks_total"] == 0
        assert telemetry["frames_processed"] > 0
        assert len(accumulator.final_segments) >= 3
