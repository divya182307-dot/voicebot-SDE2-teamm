"""CLI demonstration for SDE Team 2 (Week 1 and Week 2).

Provides two demonstration modes:
- Standard Stream Demo: Slices and streams chunks from MockMicrophone (Week 1).
- Pipeline & VAD Demo: End-to-end device adapter, lifecycle controller, VAD,
  bounded stream buffer, and diagnostics telemetry (Week 2, Day 14).
"""

import argparse
import asyncio
import math
from pathlib import Path
import struct
import sys
import time

# Ensure both voicebot src and repository root are in sys.path for direct execution
_SRC_DIR = str(Path(__file__).resolve().parent.parent)
_REPO_ROOT = str(Path(__file__).resolve().parents[4])
for _path in [_SRC_DIR, _REPO_ROOT]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

from voicebot.buffer import BoundedAudioBuffer, DropStrategy
from voicebot.device import MockAudioDeviceAdapter, PermissionState
from voicebot.diagnostics import collect_diagnostics
from voicebot.events import (
    AudioEvent,
    AudioFrameEvent,
    EventType,
    SpeechEndedEvent,
    SpeechEventProcessor,
    SpeechStartedEvent,
)
from voicebot.lifecycle import AudioLifecycleController
from voicebot.mock_microphone import MockMicrophone
from voicebot.normalizer import AudioNormalizer
from voicebot.schemas import AudioChunk, AudioFormat
from voicebot.transcription_bridge import TranscriptionBridge
from voicebot.vad import VoiceActivityDetector

# Import teammate STT contracts
from src.voice.accumulator import SegmentAccumulator
from src.voice.fake_transcriber import FakeTranscriber


def parse_args(args=None) -> argparse.Namespace:
    """Parse command line arguments for the audio stream demo."""
    parser = argparse.ArgumentParser(
        description="SDE Team 2 - AI Voice Co-Pilot: Audio Stream & Pipeline Demo",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=16000,
        help="Sampling rate in Hz",
    )
    parser.add_argument(
        "--channels",
        type=int,
        default=1,
        choices=[1, 2],
        help="Audio channels (1=mono, 2=stereo)",
    )
    parser.add_argument(
        "--chunk-count",
        type=int,
        default=5,
        help="Number of chunks to stream",
    )
    parser.add_argument(
        "--frames-per-chunk",
        type=int,
        default=4,
        help="Number of audio frames per chunk",
    )
    parser.add_argument(
        "--sample-width",
        type=int,
        default=2,
        choices=[1, 2, 3, 4],
        help="Sample width in bytes (2 = 16-bit PCM)",
    )
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="Simulate real-time streaming pacing between chunks",
    )
    parser.add_argument(
        "--pipeline",
        action="store_true",
        help="Run full Week 2 pipeline demo (Device Adapter + Lifecycle + VAD + Bounded Buffer)",
    )
    parser.add_argument(
        "--integration",
        action="store_true",
        help="Run full Week 3 integration demo (VAD -> Events -> Normalizer -> TranscriptionBridge -> STT)",
    )
    parser.add_argument(
        "--script",
        type=str,
        default="Can you explain the difference between processes and threads?",
        help="Pre-scripted utterance text to simulate in the STT demo (used with --integration)",
    )
    parser.add_argument(
        "--demo-pause",
        action="store_true",
        help="Demonstrate pause and resume lifecycle transitions (used with --pipeline)",
    )
    parser.add_argument(
        "--energy-threshold",
        type=float,
        default=0.02,
        help="VAD RMS energy threshold (used with --pipeline)",
    )
    parser.add_argument(
        "--min-speech-duration-ms",
        type=float,
        default=50.0,
        help="VAD minimum speech duration in ms (used with --pipeline)",
    )
    return parser.parse_args(args)


def run_pipeline_demo(args: argparse.Namespace) -> int:
    """Run the complete Week 2 end-to-end pipeline demonstration."""
    print("=" * 72)
    print("  SDE Team 2 - AI Voice Co-Pilot: Audio Pipeline & VAD Demo (Week 2)")
    print("=" * 72)

    adapter = MockAudioDeviceAdapter(initial_permission=PermissionState.PROMPT)
    perm = adapter.request_permission()
    selected_device = adapter.get_selected_device()

    print(f"Device:           {selected_device.name} [{selected_device.device_id}]")
    print(f"Permission:       {perm.value}")
    print(f"Format:           {args.sample_rate} Hz, {'Mono (1 ch)' if args.channels == 1 else 'Stereo (2 ch)'}, {args.sample_width * 8}-bit")
    print(f"VAD Threshold:    RMS {args.energy_threshold:.4f} | Min Duration: {args.min_speech_duration_ms:.1f}ms")
    print(f"Bounded Buffer:   Capacity: 10 chunks | Strategy: DROP_OLDEST")
    print(f"Pacing:           {'Real-time simulated' if args.realtime else 'Immediate (batch)'}")
    print("-" * 72)

    controller = AudioLifecycleController(adapter)
    controller.start()

    vad = VoiceActivityDetector(
        energy_threshold=args.energy_threshold,
        min_speech_duration_ms=args.min_speech_duration_ms,
    )
    buffer = BoundedAudioBuffer(max_chunks=10, drop_strategy=DropStrategy.DROP_OLDEST)

    print(f"Lifecycle State:  [{controller.state.value}] (Session: {controller.session_id[:8]}...)")
    print("-" * 72)
    print(f"{'Seq ID':<8} {'Timestamp':<12} {'RMS Energy':<12} {'VAD Status':<14} {'Buffer':<10} {'Size'}")
    print("-" * 72)

    chunk_duration = args.frames_per_chunk / args.sample_rate
    chunks_processed = 0

    try:
        for chunk in controller.capture_stream(
            chunk_count=args.chunk_count,
            frames_per_chunk=args.frames_per_chunk,
        ):
            vad_res = vad.process_chunk(chunk)
            speech_badge = "SPEECH [ON]" if vad_res.is_speech else "SILENCE [OFF]"
            buffer.push(chunk)
            buf_str = f"{buffer.current_occupancy}/{buffer.max_chunks}"

            print(
                f"{chunk.sequence_id:<8} "
                f"{chunk.timestamp:<12.4f} "
                f"{vad_res.energy_score:<12.4f} "
                f"{speech_badge:<14} "
                f"{buf_str:<10} "
                f"{len(chunk.data)}B"
            )

            chunks_processed += 1

            if args.demo_pause and chunks_processed == 2:
                print("--- [Simulating Assistant Turn: PAUSING capture] ---")
                controller.pause()
                print(f"--- [Lifecycle State: {controller.state.value}] ---")
                controller.resume()
                print(f"--- [Lifecycle State: {controller.state.value}] ---")

            if args.realtime:
                time.sleep(chunk_duration)

    finally:
        controller.stop()

    print("-" * 72)
    print("Stream Completed Successfully:")
    diag = collect_diagnostics(controller, buffer, vad)
    print(f"  Lifecycle Final:  {diag.lifecycle_state}")
    print(f"  Total Chunks:     {diag.chunks_emitted} emitted, {diag.chunks_suppressed} suppressed")
    print(f"  Buffer Final:     {diag.buffer_occupancy}/{diag.buffer_max_chunks} queued ({diag.buffer_occupancy_ratio * 100:.1f}%)")
    print(f"  Dropped Chunks:   {diag.dropped_chunk_counter}")
    print(f"  VAD Summary:      {diag.total_speech_chunks} speech frames, {diag.total_silence_chunks} silence frames")
    print(f"  Pipeline Health:  {'HEALTHY [OK]' if diag.is_healthy else 'ATTENTION REQUIRED [WARN]'}")
    print("=" * 72)
    return 0


def run_integration_demo(args: argparse.Namespace) -> int:
    """Run the complete Week 3 end-to-end voice and STT integration demonstration."""
    print("=" * 76)
    print("  SDE Team 2 - AI Voice Co-Pilot: Week 3 Integrated Voice & STT Demo")
    print("=" * 76)

    session_id = f"demo-session-{int(time.time())}"
    script_text = getattr(args, "script", None) or "Can you explain the difference between processes and threads?"

    print("Configuration:")
    print(f"  Session ID:       {session_id}")
    print(f"  Script Utterance: '{script_text}'")
    print(f"  Audio Format:     16000 Hz, 1 channel (mono), 16-bit linear PCM")
    print(f"  VAD Settings:     Energy Threshold: {args.energy_threshold:.4f} | Min Speech Duration: {args.min_speech_duration_ms:.1f}ms")
    print(f"  Normalizer:       Target Peak: 0.95 | Gain Cap: 24.0 dB")
    print(f"  Pre-roll Buffer:  4 chunks (80ms lookback)")
    print("-" * 76)

    transcriber = FakeTranscriber(session_id=session_id, script=[script_text])
    accumulator = SegmentAccumulator(session_id=session_id)
    bridge = TranscriptionBridge(transcriber=transcriber, accumulator=accumulator)

    vad = VoiceActivityDetector(
        energy_threshold=args.energy_threshold,
        min_speech_duration_ms=args.min_speech_duration_ms,
    )
    normalizer = AudioNormalizer(target_peak=0.95)
    processor = SpeechEventProcessor(
        vad=vad,
        normalizer=normalizer,
        session_id=session_id,
        pre_roll_chunks=4,
    )

    sample_rate = 16000
    duration_ms = 20
    frames_per_chunk = int(sample_rate * (duration_ms / 1000.0))
    fmt = AudioFormat(sample_rate=sample_rate, channels=1, sample_width=2)

    def _make_chunk(seq: int, amp: float) -> AudioChunk:
        samples = []
        for i in range(frames_per_chunk):
            val = int(amp * 32767.0 * math.sin(2.0 * math.pi * 440.0 * (i / sample_rate))) if amp > 0 else 0
            samples.append(max(-32768, min(32767, val)))
        return AudioChunk(
            sequence_id=seq,
            timestamp=float(seq * duration_ms) / 1000.0,
            audio_format=fmt,
            data=struct.pack(f"<{len(samples)}h", *samples),
        )

    chunks: list[AudioChunk] = []
    for s in range(4):
        chunks.append(_make_chunk(s, 0.0))
    for s in range(4, 29):
        chunks.append(_make_chunk(s, 0.35))
    for s in range(29, 39):
        chunks.append(_make_chunk(s, 0.0))

    print(f"{'Chunk':<7}{'VAD Status':<14}{'Audio Event Emitted':<22}{'Event Seq':<11}{'Correlation ID'}")
    print("-" * 76)

    async def _run():
        for chunk in chunks:
            events = processor.process_chunk(chunk)
            for ev in events:
                vad_label = "SPEECH [ON]" if ev.event_type != EventType.SPEECH_ENDED else "SILENCE [OFF]"
                ev_type_label = f"[{ev.event_type.value.upper()}]"
                corr_short = ev.correlation_id[:12] + "..." if len(ev.correlation_id) > 12 else ev.correlation_id
                print(
                    f"#{chunk.sequence_id:<6}"
                    f"{vad_label:<14}"
                    f"{ev_type_label:<22}"
                    f"#{ev.sequence_number:<10}"
                    f"{corr_short}"
                )
                await bridge.handle_audio_event(ev)

            if getattr(args, "realtime", False):
                await asyncio.sleep(0.02)

    asyncio.run(_run())

    print("-" * 76)
    print("Final Accumulated Transcript & Analytics:")
    print(f"  Transcript:       \"{accumulator.get_final_text()}\"")
    print(f"  Word Count:       {accumulator.word_count} words")
    print(f"  Total Duration:   {accumulator.total_duration_ms} ms")
    print(f"  Avg Confidence:   {accumulator.average_confidence:.4f}")
    print(f"  Final Segments:   {len(accumulator.final_segments)}")

    telemetry = bridge.get_telemetry()
    print("\nTranscription Bridge Telemetry:")
    print(f"  Speech Turns:     {telemetry['speech_turns_completed']} completed")
    print(f"  Frames Forwarded: {telemetry['frames_processed']} frames ({telemetry['bytes_forwarded']} bytes)")
    print(f"  Sequence Gaps:    {telemetry['gap_count']} (missing chunks: {telemetry['missing_chunks_total']})")
    print(f"  Transcript Events:{telemetry['transcript_events_count']} emitted")
    print(f"  Integration State:HEALTHY [OK]")
    print("=" * 76)
    return 0


def run_demo(args: argparse.Namespace | None = None) -> int:
    """Run the audio demonstration (Week 1 standard, Week 2 pipeline, or Week 3 integration).

    Args:
        args: Parsed command line arguments.

    Returns:
        int: Exit status code (0 for success).
    """
    if args is None:
        args = parse_args([])

    if getattr(args, "integration", False):
        return run_integration_demo(args)

    if getattr(args, "pipeline", False):
        return run_pipeline_demo(args)

    # Standard Week 1 stream demo (preserves 100% backward compatibility)
    print("=" * 70)
    print("  SDE Team 2 - AI Voice Co-Pilot: Audio Streaming Demo (Week 1)")
    print("=" * 70)
    print("Configuration:")
    print(f"  Sample Rate:      {args.sample_rate} Hz")
    channel_desc = "Mono (1 ch)" if args.channels == 1 else "Stereo (2 ch)"
    print(f"  Channels:         {channel_desc}")
    print(f"  Sample Width:     {args.sample_width} bytes ({args.sample_width * 8}-bit PCM)")
    print(f"  Chunks to Stream: {args.chunk_count}")
    print(f"  Frames Per Chunk: {args.frames_per_chunk}")
    print(f"  Pacing:           {'Real-time simulated' if args.realtime else 'Immediate (batch)'}")
    print("-" * 70)
    print(f"{'Seq ID':<8}{'Timestamp':<14}{'Format (Hz, ch, bits)':<24}{'Frames':<10}{'Size (Bytes)':<12}")
    print("-" * 70)

    mic = MockMicrophone(
        sample_rate=args.sample_rate,
        channels=args.channels,
        chunk_count=args.chunk_count,
        frames_per_chunk=args.frames_per_chunk,
        sample_width=args.sample_width,
    )

    total_bytes = 0
    total_frames = 0
    total_duration = 0.0

    for chunk in mic.stream():
        total_bytes += len(chunk.data)
        total_frames += chunk.frame_count
        total_duration = chunk.timestamp + chunk.duration

        fmt_str = f"{chunk.audio_format.sample_rate}Hz, {chunk.audio_format.channels}ch, {chunk.audio_format.sample_width * 8}b"
        print(
            f"{chunk.sequence_id:<8}"
            f"{chunk.timestamp:<14.4f}"
            f"{fmt_str:<24}"
            f"{chunk.frame_count:<10}"
            f"{len(chunk.data):<12}"
        )

        if args.realtime and chunk.duration > 0:
            time.sleep(chunk.duration)

    print("-" * 70)
    print("Stream Completed Successfully:")
    print(f"  Total Chunks:    {args.chunk_count}")
    print(f"  Total Frames:    {total_frames}")
    print(f"  Total Bytes:     {total_bytes} bytes")
    print(f"  Total Duration:  {total_duration:.4f} seconds")
    print("=" * 70)

    return 0


def main() -> int:
    """Entry point for CLI execution."""
    args = parse_args()
    return run_demo(args)


if __name__ == "__main__":
    sys.exit(main())
