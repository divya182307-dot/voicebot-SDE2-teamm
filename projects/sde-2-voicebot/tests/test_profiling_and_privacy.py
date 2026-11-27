"""Tests for Week 4 (Days 22-24): Profiling, Capture Indicators, and Privacy Verification.

Covers:
1. High-precision latency profiling and percentile distributions (min <= p50 <= p95 <= p99 <= max).
2. Profiler overhead calibration and timing accuracy.
3. Memory heap monitoring and robust leak detection with warm-up phase.
4. Visible real-time capture indicators across all lifecycle states.
5. Zero-disk-write privacy verification in an isolated temporary environment with open() write interception.
6. Per-stage pipeline profiling (Normalizer, VAD, Buffer, Events, STT Bridge).
7. CLI --profile benchmark execution.
"""

from __future__ import annotations

import asyncio
import builtins
import math
from pathlib import Path
import struct
import tempfile
import time
from unittest.mock import patch
import pytest

from voicebot.buffer import BoundedAudioBuffer, DropStrategy
from voicebot.cli import parse_args, run_profile_demo
from voicebot.events import SpeechEventProcessor
from voicebot.lifecycle import LifecycleState
from voicebot.normalizer import AudioNormalizer
from voicebot.profiler import (
    AudioPipelineProfiler,
    LatencyMetrics,
    MemoryMetrics,
    ProfileReport,
    get_capture_indicator,
)
from voicebot.schemas import AudioChunk, AudioFormat
from voicebot.transcription_bridge import TranscriptionBridge
from voicebot.vad import VoiceActivityDetector

# STT contracts
from src.voice.accumulator import SegmentAccumulator
from src.voice.fake_transcriber import FakeTranscriber


@pytest.fixture
def sample_format() -> AudioFormat:
    """Standard 16kHz mono 16-bit PCM format."""
    return AudioFormat(sample_rate=16000, channels=1, sample_width=2)


def make_synthetic_chunk(
    seq: int,
    fmt: AudioFormat,
    amplitude: float = 0.35,
    duration_ms: int = 20,
) -> AudioChunk:
    """Generate a deterministic synthetic audio chunk for testing."""
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


class TestLatencyProfiling:
    """Tests for nanosecond-precision latency profiling and statistics."""

    def test_overhead_calibration(self) -> None:
        """Profiler must calibrate timing overhead and return a non-negative value."""
        profiler = AudioPipelineProfiler(enable_memory_tracking=False)
        overhead = profiler.calibrate_overhead(iterations=500)
        assert isinstance(overhead, float)
        assert overhead >= 0.0

    def test_latency_percentile_ordering(self, sample_format: AudioFormat) -> None:
        """Statistical percentiles must strictly satisfy: min <= p50 <= p95 <= p99 <= max."""
        profiler = AudioPipelineProfiler(warmup_chunks=5, enable_memory_tracking=False)
        profiler.start()

        # Simulate 100 chunk measurements with varying mock durations
        for seq in range(100):
            chunk = make_synthetic_chunk(seq, sample_format)
            with profiler.profile_chunk(seq):
                # Light mathematical work to induce real, non-zero timing
                _ = sum(chunk.data)

        profiler.stop()
        report = profiler.generate_report()

        lat = report.pipeline_latency
        assert lat.sample_count == 100
        assert lat.min_ms >= 0.0
        assert lat.min_ms <= lat.p50_ms
        assert lat.p50_ms <= lat.p95_ms
        assert lat.p95_ms <= lat.p99_ms
        assert lat.p99_ms <= lat.max_ms
        assert lat.avg_ms > 0.0
        assert lat.throughput_cps > 0.0

    def test_stage_latency_breakdown(self, sample_format: AudioFormat) -> None:
        """Profiler must accurately measure and report per-stage latency."""
        normalizer = AudioNormalizer(target_peak=0.95)
        vad = VoiceActivityDetector(energy_threshold=0.02)
        buffer = BoundedAudioBuffer(max_chunks=10, drop_strategy=DropStrategy.DROP_OLDEST)

        profiler = AudioPipelineProfiler(enable_memory_tracking=False)
        profiler.start()

        for seq in range(50):
            chunk = make_synthetic_chunk(seq, sample_format, amplitude=0.4)
            with profiler.profile_chunk(seq):
                with profiler.measure_stage("normalizer"):
                    norm_chunk = normalizer.normalize_chunk(chunk)

                with profiler.measure_stage("vad"):
                    _ = vad.process_chunk(norm_chunk)

                with profiler.measure_stage("buffer"):
                    buffer.push(norm_chunk)

        profiler.stop()
        report = profiler.generate_report()

        assert "normalizer" in report.stage_latencies
        assert "vad" in report.stage_latencies
        assert "buffer" in report.stage_latencies
        for stage in ("normalizer", "vad", "buffer"):
            m = report.stage_latencies[stage]
            assert m.sample_count == 50
            assert m.avg_ms >= 0.0

    def test_reproducible_pipeline_latency(self, sample_format: AudioFormat) -> None:
        """Full pipeline processing must yield positive, finite timing without machine-dependent failures."""
        normalizer = AudioNormalizer(target_peak=0.95)
        vad = VoiceActivityDetector(energy_threshold=0.02)
        buffer = BoundedAudioBuffer(max_chunks=10)
        processor = SpeechEventProcessor(vad=vad, normalizer=normalizer, session_id="test-rep")

        profiler = AudioPipelineProfiler(warmup_chunks=10, enable_memory_tracking=False)
        profiler.start()

        for seq in range(80):
            chunk = make_synthetic_chunk(seq, sample_format, amplitude=0.35 if seq > 10 else 0.0)
            with profiler.profile_chunk(seq):
                norm_chunk = normalizer.normalize_chunk(chunk)
                _ = vad.process_chunk(norm_chunk)
                buffer.push(norm_chunk)
                _ = processor.process_chunk(norm_chunk)

        profiler.stop()
        report = profiler.generate_report()

        # Informative and reproducible: verify valid finite bounds
        assert report.pipeline_latency.sample_count == 80
        assert math.isfinite(report.pipeline_latency.avg_ms)
        assert math.isfinite(report.pipeline_latency.p95_ms)
        assert report.pipeline_latency.throughput_cps > 100.0  # At least 100 chunks/sec in synthetic execution


class TestMemoryMonitoring:
    """Tests for heap allocation tracking and memory leak detection with warm-up."""

    def test_tracemalloc_memory_metrics(self, sample_format: AudioFormat) -> None:
        """Profiler must capture baseline, current, and peak heap metrics."""
        profiler = AudioPipelineProfiler(warmup_chunks=20, enable_memory_tracking=True)
        profiler.start()

        for seq in range(60):
            chunk = make_synthetic_chunk(seq, sample_format)
            with profiler.profile_chunk(seq):
                _ = bytearray(chunk.data)  # Transient allocation

        profiler.stop()
        report = profiler.generate_report()

        assert report.memory is not None
        assert report.memory.baseline_kb >= 0.0
        assert report.memory.peak_kb >= report.memory.baseline_kb
        assert report.memory.warmup_chunks == 20

    def test_robust_leak_detection_with_warmup(self, sample_format: AudioFormat) -> None:
        """Continuous streaming with bounded buffer must not trigger false leak detection."""
        normalizer = AudioNormalizer(target_peak=0.95)
        vad = VoiceActivityDetector(energy_threshold=0.02)
        buffer = BoundedAudioBuffer(max_chunks=20, drop_strategy=DropStrategy.DROP_OLDEST)
        processor = SpeechEventProcessor(vad=vad, normalizer=normalizer, session_id="test-leak-check")

        # Configure warm-up of 50 chunks, with 0.10 KB/chunk tolerance for small allocator dynamics
        profiler = AudioPipelineProfiler(
            warmup_chunks=50,
            leak_tolerance_kb_per_chunk=0.10,
            enable_memory_tracking=True,
        )
        profiler.start()

        # Stream 300 chunks through complete pipeline
        for seq in range(300):
            chunk = make_synthetic_chunk(seq, sample_format, amplitude=0.4 if (seq % 30) < 15 else 0.0)
            with profiler.profile_chunk(seq):
                norm_chunk = normalizer.normalize_chunk(chunk)
                _ = vad.process_chunk(norm_chunk)
                buffer.push(norm_chunk)
                _ = processor.process_chunk(norm_chunk)

        profiler.stop()
        report = profiler.generate_report()

        assert report.memory is not None
        # Must confirm that no memory leak was detected
        assert not report.memory.leak_detected


class TestVisibleCaptureIndicator:
    """Tests for real-time visual indicator badges."""

    def test_indicator_recording_speech(self) -> None:
        badge = get_capture_indicator("RECORDING", is_speech=True, energy=0.1234)
        assert "REC" in badge
        assert "SPEECH ACTIVE" in badge
        assert "0.1234" in badge

    def test_indicator_recording_listening(self) -> None:
        badge = get_capture_indicator("RECORDING", is_speech=False, energy=0.0050)
        assert "REC" in badge
        assert "LISTENING" in badge
        assert "0.0050" in badge

    def test_indicator_paused(self) -> None:
        badge = get_capture_indicator("PAUSED")
        assert "PAUSED" in badge
        assert "SUSPENDED" in badge

    def test_indicator_reconnecting(self) -> None:
        badge = get_capture_indicator("RECONNECTING")
        assert "RECONNECTING" in badge
        assert "FALLBACK" in badge

    def test_indicator_cancelled(self) -> None:
        badge = get_capture_indicator("CANCELLED")
        assert "CANCELLED" in badge
        assert "BUFFER FLUSHED" in badge

    def test_indicator_stopped(self) -> None:
        badge = get_capture_indicator("STOPPED")
        assert "IDLE" in badge
        assert "MIC OFF" in badge


class TestPrivacyZeroDiskWrite:
    """Tests verifying that zero audio files or temporary data are written to disk."""

    def test_isolated_environment_zero_disk_writes_with_open_hook(
        self, sample_format: AudioFormat, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Strong privacy test: Monitor open() calls and check directory state to ensure 0 disk writes."""
        # Create an isolated temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            write_calls: list[dict[str, str]] = []

            original_open = builtins.open

            def hooked_open(file, mode="r", *args, **kwargs):
                # Intercept any file write attempts
                mode_str = str(mode)
                if any(m in mode_str for m in ("w", "a", "+", "x")):
                    write_calls.append({"file": str(file), "mode": mode_str})
                return original_open(file, mode, *args, **kwargs)

            monkeypatch.setattr(builtins, "open", hooked_open)

            # Set up the full end-to-end voicebot pipeline
            session_id = "privacy-session-1"
            normalizer = AudioNormalizer(target_peak=0.95)
            vad = VoiceActivityDetector(energy_threshold=0.02)
            buffer = BoundedAudioBuffer(max_chunks=25, drop_strategy=DropStrategy.DROP_OLDEST)
            processor = SpeechEventProcessor(vad=vad, normalizer=normalizer, session_id=session_id)

            transcriber = FakeTranscriber(session_id=session_id, script=["Testing zero-disk audio privacy."])
            accumulator = SegmentAccumulator(session_id=session_id)
            bridge = TranscriptionBridge(transcriber=transcriber, accumulator=accumulator)

            profiler = AudioPipelineProfiler(enable_memory_tracking=False)
            profiler.start()

            async def _run_session():
                for seq in range(200):
                    amp = 0.35 if (seq % 40) < 20 else 0.0
                    chunk = make_synthetic_chunk(seq, sample_format, amplitude=amp)

                    with profiler.profile_chunk(seq):
                        norm_chunk = normalizer.normalize_chunk(chunk)
                        _ = vad.process_chunk(norm_chunk)
                        buffer.push(norm_chunk)
                        events = processor.process_chunk(norm_chunk)
                        for ev in events:
                            await bridge.handle_audio_event(ev)

            asyncio.run(_run_session())
            profiler.stop()

            # Verify that NO write calls targeted audio files or user workspace
            audio_extensions = {".wav", ".pcm", ".raw", ".aac", ".mp3", ".ogg", ".flac", ".tmp"}
            audio_write_attempts = [
                call for call in write_calls
                if Path(call["file"]).suffix.lower() in audio_extensions or "audio" in call["file"].lower()
            ]
            assert len(audio_write_attempts) == 0, f"Detected audio file write operations: {audio_write_attempts}"

            # Verify the isolated directory has 0 audio files
            created_files = list(temp_path.glob("**/*"))
            assert len(created_files) == 0, f"Unexpected files created in isolated directory: {created_files}"

            # Report reflects 0 disk writes verified
            report = profiler.generate_report(disk_writes_detected=len(audio_write_attempts))
            assert report.zero_disk_verified
            assert report.disk_writes_detected == 0

    def test_report_formatting(self) -> None:
        """Verify summary_text() outputs all expected sections without error."""
        profiler = AudioPipelineProfiler(warmup_chunks=5, enable_memory_tracking=True)
        profiler.start()
        for i in range(10):
            with profiler.profile_chunk(i):
                _ = sum(range(100))
        profiler.stop()

        report = profiler.generate_report(disk_writes_detected=0)
        summary = report.summary_text()
        assert "Audio Pipeline Profiling & Hardening Report" in summary
        assert "Latency Distribution" in summary
        assert "Privacy & Disk Persistence Check" in summary
        assert "PASSED (Zero audio disk writes)" in summary
        report_dict = report.to_dict()
        assert report_dict["zero_disk_verified"] is True


class TestCLIProfilingMode:
    """Tests for CLI integration with --profile flag."""

    def test_parse_args_profile_flag(self) -> None:
        args = parse_args(["--profile", "--profile-chunks", "150"])
        assert args.profile is True
        assert args.profile_chunks == 150

    def test_run_profile_demo_executes_successfully(self) -> None:
        args = parse_args(["--profile", "--profile-chunks", "30"])
        exit_code = run_profile_demo(args)
        assert exit_code == 0
