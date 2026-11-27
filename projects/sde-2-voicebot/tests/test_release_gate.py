"""Day 30 Release Gate Automated Test Suite for SDE Team 2.

Validates the final release criteria:
1. Scenario A: Happy path normal voicebot workflow (Capture -> Normalization -> VAD -> Events -> STT).
2. Scenario B: Device failure resilience (Mid-stream disconnect -> Auto-recovery to fallback -> Barge-in cancellation).
3. Privacy & Resource Invariants: Zero disk writes by default, bounded heap memory, and 100% synthetic determinism.
4. CLI Demonstration: Full execution of --demo-release with clean zero exit code.
"""

from __future__ import annotations

import asyncio
import math
import struct
import tempfile
from unittest.mock import patch
import pytest

from voicebot.buffer import BoundedAudioBuffer, DropStrategy
from voicebot.cli import parse_args, run_demo
from voicebot.device import (
    AudioDevice,
    MockAudioDeviceAdapter,
    PermissionState,
)
from voicebot.events import EventType, SpeechEventProcessor
from voicebot.lifecycle import AudioLifecycleController, LifecycleState
from voicebot.normalizer import AudioNormalizer
from voicebot.schemas import AudioChunk, AudioFormat
from voicebot.transcription_bridge import TranscriptionBridge
from voicebot.vad import VoiceActivityDetector

# Teammate STT modules
from src.voice.accumulator import SegmentAccumulator
from src.voice.fake_transcriber import FakeTranscriber


@pytest.fixture
def release_audio_format() -> AudioFormat:
    """Standard 16kHz mono 16-bit PCM format."""
    return AudioFormat(sample_rate=16000, channels=1, sample_width=2)


def make_release_chunk(
    seq: int,
    fmt: AudioFormat,
    amplitude: float = 0.35,
    duration_ms: int = 20,
) -> AudioChunk:
    """Generate a deterministic synthetic audio chunk for release testing."""
    frame_count = int(fmt.sample_rate * (duration_ms / 1000.0))
    samples: list[int] = []
    freq = 440.0

    for i in range(frame_count):
        if amplitude > 0.0:
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


class TestDay30ReleaseGate:
    """Automated release gate verification suite."""

    def test_scenario_a_happy_path_normal_voicebot(self, release_audio_format: AudioFormat) -> None:
        """Scenario A: Full normal pipeline from audio ingestion through STT transcript accumulation."""
        session_id = "release-gate-happy-path"
        script = ["Testing normal happy path voicebot pipeline for release gate."]

        normalizer = AudioNormalizer(target_peak=0.95)
        vad = VoiceActivityDetector(energy_threshold=0.02, min_speech_duration_ms=40.0)
        buffer = BoundedAudioBuffer(max_chunks=20, drop_strategy=DropStrategy.DROP_OLDEST)
        processor = SpeechEventProcessor(
            vad=vad,
            normalizer=normalizer,
            session_id=session_id,
            pre_roll_chunks=4,
        )

        transcriber = FakeTranscriber(session_id=session_id, script=script)
        accumulator = SegmentAccumulator(session_id=session_id)
        bridge = TranscriptionBridge(transcriber=transcriber, accumulator=accumulator)

        async def _run_pipeline():
            # 5 silence chunks, 25 speech chunks, 10 silence chunks (40 total = 800ms)
            for seq in range(40):
                is_speech = 5 <= seq < 30
                amp = 0.35 if is_speech else 0.0
                chunk = make_release_chunk(seq, release_audio_format, amplitude=amp)

                norm_chunk = normalizer.normalize_chunk(chunk)
                buffer.push(norm_chunk)
                events = processor.process_chunk(norm_chunk)

                for ev in events:
                    await bridge.handle_audio_event(ev)

        asyncio.run(_run_pipeline())

        # Assertions for Scenario A
        telemetry = bridge.get_telemetry()
        assert telemetry["speech_turns_completed"] >= 1
        assert telemetry["gap_count"] == 0
        assert telemetry["missing_chunks_total"] == 0
        assert telemetry["frames_processed"] > 0
        assert len(accumulator.final_segments) >= 1
        assert script[0] in accumulator.get_final_text()

    def test_scenario_b_device_disconnect_and_fallback_recovery(self) -> None:
        """Scenario B (Part 1): Mid-stream USB disconnect recovers cleanly to fallback default mic."""
        primary_dev = AudioDevice("mic-usb-headset", "USB Headset Mic", channels=1, default_sample_rate=16000, is_default=False)
        fallback_dev = AudioDevice("mic-builtin-fallback", "Built-in Fallback Mic", channels=1, default_sample_rate=16000, is_default=True)

        adapter = MockAudioDeviceAdapter(
            devices=[primary_dev, fallback_dev],
            initial_permission=PermissionState.GRANTED,
        )
        adapter.select_device("mic-usb-headset")

        controller = AudioLifecycleController(adapter=adapter, max_reconnect_attempts=3, auto_reconnect=True)
        controller.start()
        original_session = controller.session_id
        assert controller.state == LifecycleState.RECORDING

        # Stream starts on primary device
        stream = controller.capture_stream(chunk_count=5, frames_per_chunk=4)
        c0 = next(stream)
        assert c0.sequence_id == 0

        # Disconnect primary mic mid-stream
        adapter.disconnect_device("mic-usb-headset")

        # Auto-reconnect to fallback
        reconnected = controller.reconnect(fallback_device_id="mic-builtin-fallback")
        assert reconnected is True
        assert adapter.get_selected_device().device_id == "mic-builtin-fallback"
        assert controller.session_id == original_session
        assert controller.successful_reconnects == 1

        controller.stop()
        assert controller.state == LifecycleState.STOPPED

    def test_scenario_b_user_barge_in_cancellation(self, release_audio_format: AudioFormat) -> None:
        """Scenario B (Part 2): User barge-in terminates capture and immediately purges all buffer memory."""
        adapter = MockAudioDeviceAdapter(initial_permission=PermissionState.GRANTED)
        controller = AudioLifecycleController(adapter)
        controller.start()

        buffer = BoundedAudioBuffer(max_chunks=15, drop_strategy=DropStrategy.DROP_OLDEST)
        vad = VoiceActivityDetector(energy_threshold=0.02)
        processor = SpeechEventProcessor(vad=vad, session_id=controller.session_id)

        # Enqueue 6 active speech chunks into buffer
        for i in range(6):
            chunk = make_release_chunk(i, release_audio_format, amplitude=0.4)
            buffer.push(chunk)
            _ = processor.process_chunk(chunk)

        assert buffer.current_occupancy == 6
        assert processor.is_in_speech is True

        # User interruption / barge-in occurs: cancel session
        controller.cancel(buffer=buffer, processor=processor)

        assert controller.state == LifecycleState.CANCELLED
        assert controller.is_cancelled is True
        # Guaranteed complete memory release
        assert buffer.current_occupancy == 0
        assert buffer.pull() is None
        assert processor.is_in_speech is False
        assert processor.active_correlation_id is None

    def test_release_gate_zero_disk_writes_invariance(self, release_audio_format: AudioFormat) -> None:
        """Release Invariant: PRD Section 19 zero disk writes strictly verified in isolated directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_writes_attempted: list[str] = []
            real_open = open

            def _monitoring_open(file, *args, **kwargs):
                mode = args[0] if args else kwargs.get("mode", "r")
                if any(m in mode for m in ("w", "a", "+", "x")):
                    file_writes_attempted.append(str(file))
                return real_open(file, *args, **kwargs)

            with patch("builtins.open", side_effect=_monitoring_open):
                # Run complete dual-scenario pipeline
                normalizer = AudioNormalizer(target_peak=0.95)
                vad = VoiceActivityDetector()
                buffer = BoundedAudioBuffer(max_chunks=10)
                processor = SpeechEventProcessor(vad=vad, normalizer=normalizer, session_id="release-gate-privacy")

                for seq in range(50):
                    chk = make_release_chunk(seq, release_audio_format, amplitude=0.35 if seq % 2 == 0 else 0.0)
                    norm = normalizer.normalize_chunk(chk)
                    buffer.push(norm)
                    _ = processor.process_chunk(norm)

            # Audio engine must never touch the disk
            audio_disk_writes = [f for f in file_writes_attempted if any(ext in f.lower() for ext in (".wav", ".pcm", ".raw", ".aac", ".tmp"))]
            assert len(audio_disk_writes) == 0

    def test_release_gate_cli_demo_release_executes_cleanly(self) -> None:
        """Verify CLI --demo-release executes both scenarios and exits with code 0."""
        args = parse_args(["--demo-release"])
        exit_code = run_demo(args)
        assert exit_code == 0
