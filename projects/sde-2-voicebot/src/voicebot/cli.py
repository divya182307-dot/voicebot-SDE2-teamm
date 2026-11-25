"""CLI demonstration for SDE Team 2 (Week 1 and Week 2).

Provides two demonstration modes:
- Standard Stream Demo: Slices and streams chunks from MockMicrophone (Week 1).
- Pipeline & VAD Demo: End-to-end device adapter, lifecycle controller, VAD,
  bounded stream buffer, and diagnostics telemetry (Week 2, Day 14).
"""

import argparse
from pathlib import Path
import sys
import time

# Ensure src directory is in sys.path for direct script execution
_SRC_DIR = str(Path(__file__).resolve().parent.parent)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from voicebot.buffer import BoundedAudioBuffer, DropStrategy
from voicebot.device import MockAudioDeviceAdapter, PermissionState
from voicebot.diagnostics import collect_diagnostics
from voicebot.lifecycle import AudioLifecycleController
from voicebot.mock_microphone import MockMicrophone
from voicebot.schemas import AudioChunk, AudioFormat
from voicebot.vad import VoiceActivityDetector


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


def run_demo(args: argparse.Namespace | None = None) -> int:
    """Run the audio demonstration (Week 1 standard or Week 2 pipeline).

    Args:
        args: Parsed command line arguments.

    Returns:
        int: Exit status code (0 for success).
    """
    if args is None:
        args = parse_args([])

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
