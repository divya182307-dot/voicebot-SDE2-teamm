"""CLI demonstration for SDE Team 2 mock audio streaming (Week 1, Day 5-6).

Demonstrates streaming from MockMicrophone and prints chunk metadata
(sequence ID, timestamp, audio format, and size) in real-time or offline mode.
"""

import argparse
from pathlib import Path
import sys
import time

# Ensure src directory is in sys.path for direct script execution
_SRC_DIR = str(Path(__file__).resolve().parent.parent)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from voicebot.mock_microphone import MockMicrophone
from voicebot.schemas import AudioChunk, AudioFormat


def parse_args(args=None) -> argparse.Namespace:
    """Parse command line arguments for the audio stream demo."""
    parser = argparse.ArgumentParser(
        description="SDE Team 2 — AI Voice Co-Pilot: Mock Audio Stream Demo",
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
    return parser.parse_args(args)


def run_demo(args: argparse.Namespace | None = None) -> int:
    """Run the mock audio stream demonstration.

    Args:
        args: Parsed command line arguments (uses defaults if None).

    Returns:
        int: Exit status code (0 for success).
    """
    if args is None:
        args = parse_args([])

    print("=" * 70)
    print("  SDE Team 2 - AI Voice Co-Pilot: Audio Streaming Demo (Week 1)")
    print("=" * 70)
    print(f"Configuration:")
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
