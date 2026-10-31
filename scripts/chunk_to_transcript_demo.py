#!/usr/bin/env python3
"""Academia AI Voice Co-Pilot - Chunk-to-Transcript Streaming Demo (Day 7 Milestone).

This runnable demonstration script illustrates the complete end-to-end Voice & STT pipeline:
  1. Audio Ingestion: Simulates streaming 100ms raw PCM audio chunks (16kHz, 16-bit mono).
  2. STT Adapter Streaming: Pushes chunks into `FakeTranscriber` to emit lifecycle events:
     - SPEECH_STARTED: VAD speech onset detection
     - INTERIM_TRANSCRIPT: Real-time speculative hypotheses updating in place
     - FINAL_TRANSCRIPT: Committed speech segment locked with WordTimings and confidence
     - SPEECH_ENDED: Speech boundary turn finalization
  3. Ordered Segment Accumulator: Consumes stream, maintains strict chronological ordering,
     manages speculative interim vs. locked final text, and exposes downstream projections
     for LLM agents and UI caption bubbles.
  4. Resilience & Analytics: Demonstrates out-of-order bisection sorting, idempotent
     deduplication, chaos/error injection, and exports an AccumulatedTranscript snapshot.

Usage:
  python scripts/chunk_to_transcript_demo.py
  python scripts/chunk_to_transcript_demo.py --mode single --pace 0.03
  python scripts/chunk_to_transcript_demo.py --mode multi
  python scripts/chunk_to_transcript_demo.py --mode jitter
  python scripts/chunk_to_transcript_demo.py --mode error
  python scripts/chunk_to_transcript_demo.py --export-json demo_snapshot.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Sequence

# Windows console encoding safeguard
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.voice.accumulator import (
    AccumulatedTranscript,
    AccumulatorConfig,
    SegmentAccumulator,
)
from src.voice.adapter import AudioConfig, AudioEncoding, TranscriberConfig
from src.voice.fake_transcriber import FakeTranscriber, FakeUtterance
from src.voice.fixtures import (
    duplicate_final_events,
    make_segment,
    out_of_order_final_events,
)
from src.voice.schemas import (
    TranscriptError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
    WordTiming,
)

# ------------------------------------------------------------------------------
# ANSI Styling Utilities
# ------------------------------------------------------------------------------


class Style:
    """ANSI color codes for formatted terminal output."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"

    # Bright foregrounds
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"
    BRIGHT_RED = "\033[91m"


# Global flag toggled by --no-color
COLOR_ENABLED = True


def color(text: str, *styles: str) -> str:
    """Wrap text in ANSI escape sequence if colors are enabled."""
    if not COLOR_ENABLED or not styles:
        return text
    prefix = "".join(styles)
    return f"{prefix}{text}{Style.RESET}"


def print_banner(title: str, subtitle: Optional[str] = None) -> None:
    """Print a visually rich section banner."""
    width = 76
    line = "=" * width
    print("\n" + color(line, Style.CYAN, Style.BOLD))
    print(color(f"  {title.upper()}", Style.BRIGHT_CYAN, Style.BOLD))
    if subtitle:
        print(color(f"  {subtitle}", Style.GRAY))
    print(color(line, Style.CYAN, Style.BOLD) + "\n")


def print_subbanner(title: str) -> None:
    """Print a section sub-header."""
    bar = "-" * max(4, 72 - len(title))
    print("\n" + color(f"--- [ {title} ] {bar}", Style.BLUE, Style.BOLD))


# ------------------------------------------------------------------------------
# Audio Chunk Generator
# ------------------------------------------------------------------------------


def generate_synthetic_pcm_chunk(
    chunk_index: int,
    sample_rate: int = 16000,
    duration_ms: int = 100,
    fundamental_hz: float = 220.0,
) -> bytes:
    """Synthesize a single 16-bit mono PCM audio chunk.

    Produces realistic sine-wave acoustic frames adhering to AudioConfig:
      - 16,000 samples / sec
      - 1 channel (mono)
      - 16-bit signed integer little-endian (2 bytes / sample)
      - 100ms duration = 1,600 samples = 3,200 bytes per chunk
    """
    num_samples = (sample_rate * duration_ms) // 1000
    freq = fundamental_hz + ((chunk_index * 13) % 200)
    samples = bytearray()

    for i in range(num_samples):
        t = (chunk_index * num_samples + i) / sample_rate
        # Composite tone with harmonic to simulate voice formant
        val = 0.5 * math.sin(2.0 * math.pi * freq * t) + 0.25 * math.sin(4.0 * math.pi * freq * t)
        int_val = int(val * 16384)
        clamped = max(-32768, min(32767, int_val))
        samples.extend(clamped.to_bytes(2, byteorder="little", signed=True))

    return bytes(samples)


# ------------------------------------------------------------------------------
# UI Projection Display Helpers
# ------------------------------------------------------------------------------


def render_ui_projection_box(
    accumulator: SegmentAccumulator,
    chunk_idx: int,
    elapsed_ms: int,
) -> None:
    """Render a visual card showing current projections for UI & LLM agents."""
    final_text = accumulator.get_final_text()
    interim_text = accumulator.get_interim_text()
    full_text = accumulator.get_full_text()

    display_final = f'"{final_text}"' if final_text else color("[No locked text yet]", Style.DIM)
    display_interim = color(f'"{interim_text}"', Style.BRIGHT_YELLOW, Style.BOLD) if interim_text else color("[None]", Style.DIM)
    display_full = f'"{full_text}"' if full_text else color("[Empty]", Style.DIM)

    top_header = f"+-- Live Projections (Chunk #{chunk_idx} | Timeline: {elapsed_ms}ms) "
    top_bar = top_header + "-" * max(2, 74 - len(top_header)) + "+"

    print(color(f"  {top_bar}", Style.GRAY))
    print(color("  |", Style.GRAY) + f"  {color('Committed Final (LLM Prompt):', Style.GREEN, Style.BOLD):<42} {display_final}")
    print(color("  |", Style.GRAY) + f"  {color('Active Interim  (UI Preview):', Style.YELLOW, Style.BOLD):<42} {display_interim}")
    print(color("  |", Style.GRAY) + f"  {color('Combined Stream (Live Caption):', Style.CYAN, Style.BOLD):<42} {display_full}")
    print(color("  +" + "-" * 73 + "+", Style.GRAY))


def render_word_timing_table(words: List[WordTiming], total_duration_ms: int) -> None:
    """Render a formatted table showing word timings and alignment."""
    if not words:
        return

    print("\n" + color("  +-- Word-Level Timing & Alignment Breakdown " + "-" * 31 + "+", Style.BRIGHT_BLUE))
    print(color("  |  #   Word               Start      End      Duration   Conf    Timeline  |", Style.BOLD))
    print(color("  +-------------------------------------------------------------------------+", Style.GRAY))

    timeline_bar_width = 16
    for idx, w in enumerate(words, start=1):
        dur = max(0, w.end_time_ms - w.start_time_ms)
        conf_pct = f"{w.confidence * 100:.1f}%"

        # Compute graphical position in timeline bar
        if total_duration_ms > 0:
            bar_start = min(int((w.start_time_ms / total_duration_ms) * timeline_bar_width), timeline_bar_width - 1)
            bar_len = max(1, min(int((dur / total_duration_ms) * timeline_bar_width), timeline_bar_width - bar_start))
        else:
            bar_start, bar_len = 0, 1

        bar = ["."] * timeline_bar_width
        for b in range(bar_start, min(bar_start + bar_len, timeline_bar_width)):
            bar[b] = "#"
        bar_str = "".join(bar)

        print(
            f"  {color('|', Style.GRAY)}  {idx:<3} "
            f"{color(w.word, Style.BRIGHT_WHITE):<18} "
            f"{w.start_time_ms:>5}ms   "
            f"{w.end_time_ms:>5}ms   "
            f"{dur:>5}ms   "
            f"{color(conf_pct, Style.GREEN):<7} "
            f"[{color(bar_str, Style.CYAN)}] {color('|', Style.GRAY)}"
        )
    print(color("  +-------------------------------------------------------------------------+", Style.GRAY))


def render_session_analytics_card(
    accumulator: SegmentAccumulator,
    total_chunks: int,
    elapsed_audio_ms: int,
) -> None:
    """Render a comprehensive analytics card summarizing the session."""
    snapshot = accumulator.get_snapshot()

    print("\n" + color("  +-- Turn Analytics & Accumulator Snapshot " + "-" * 33 + "+", Style.BRIGHT_GREEN))
    print(f"  {color('|', Style.GRAY)}  {color('Session Identifier:', Style.BOLD):<30} {snapshot.session_id or 'N/A'}")
    print(f"  {color('|', Style.GRAY)}  {color('Audio Chunks Ingested:', Style.BOLD):<30} {total_chunks} chunks ({elapsed_audio_ms} ms)")
    print(f"  {color('|', Style.GRAY)}  {color('Total Spanned Duration:', Style.BOLD):<30} {snapshot.total_duration_ms} ms")
    print(f"  {color('|', Style.GRAY)}  {color('Locked Final Segments:', Style.BOLD):<30} {len(snapshot.final_segments)}")
    print(f"  {color('|', Style.GRAY)}  {color('Total Word Count:', Style.BOLD):<30} {snapshot.word_count} words")
    print(f"  {color('|', Style.GRAY)}  {color('Mean Confidence (weighted):', Style.BOLD):<30} {color(f'{snapshot.average_confidence * 100:.2f}%', Style.BRIGHT_GREEN, Style.BOLD)}")
    print(f"  {color('|', Style.GRAY)}  {color('Active Speech State:', Style.BOLD):<30} {color(str(snapshot.speech_active), Style.YELLOW if snapshot.speech_active else Style.GRAY)}")
    print(f"  {color('|', Style.GRAY)}  {color('Encountered Errors:', Style.BOLD):<30} {len(snapshot.errors)}")
    print(f"  {color('|', Style.GRAY)}  {color('Final Committed Transcript:', Style.BOLD):<30}")
    print(f"  {color('|', Style.GRAY)}    {color(repr(snapshot.final_text), Style.BRIGHT_WHITE, Style.BOLD)}")
    print(color("  +-------------------------------------------------------------------------+", Style.GRAY))


# ------------------------------------------------------------------------------
# Demonstration Scenarios
# ------------------------------------------------------------------------------


async def run_single_turn_streaming(
    script: str = "What is the time complexity of quicksort in the worst case?",
    session_id: str = "demo-single-turn",
    chunk_ms: int = 100,
    pace_seconds: float = 0.02,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Demonstrate real-time chunk-by-chunk streaming for a single utterance."""
    print_subbanner(f"Scenario 1: Live Chunk-to-Transcript Streaming ({session_id})")
    print(color(f"  Utterance Script: \"{script}\"", Style.ITALIC, Style.BRIGHT_WHITE))
    print(color(f"  Audio Format:     16kHz Mono PCM_S16LE, {chunk_ms}ms chunks (3,200 bytes/chunk)", Style.DIM))
    print(color(f"  Streaming Pacing: {pace_seconds}s per chunk simulated delay\n", Style.DIM))

    audio_cfg = AudioConfig(chunk_duration_ms=chunk_ms)
    transcriber_cfg = TranscriberConfig(audio_config=audio_cfg, interim_results=True, word_timings=True)

    transcriber = FakeTranscriber(
        session_id=session_id,
        config=transcriber_cfg,
        script=[script],
        simulate_realtime=False,
    )
    accumulator = SegmentAccumulator(
        session_id=session_id,
        config=AccumulatorConfig(auto_sort=True, deduplicate_by_id=True),
    )

    emitted_events: List[TranscriptEvent] = []

    def on_event(event: TranscriptEvent) -> None:
        emitted_events.append(event)
        accumulator.add_event(event)

        # Print formatted event notice with ASCII-safe indicators
        if event.event_type == TranscriptEventType.SPEECH_STARTED:
            print(f"    {color('[EVENT]', Style.GRAY)} {color('[SPEECH_STARTED]', Style.BRIGHT_CYAN, Style.BOLD)}  (Voice Activity Onset Detected)")
        elif event.event_type == TranscriptEventType.INTERIM_TRANSCRIPT:
            text = event.segment.text if event.segment else ""
            conf = f"{event.segment.confidence * 100:.0f}%" if event.segment else ""
            print(f"    {color('[EVENT]', Style.GRAY)} {color('[INTERIM_HYPOTHESIS]', Style.BRIGHT_YELLOW)}: \"{color(text, Style.YELLOW)}\" (conf: {conf})")
        elif event.event_type == TranscriptEventType.FINAL_TRANSCRIPT:
            text = event.segment.text if event.segment else ""
            conf = f"{event.segment.confidence * 100:.1f}%" if event.segment else ""
            print(f"    {color('[EVENT]', Style.GRAY)} {color('[FINAL_TRANSCRIPT]', Style.BRIGHT_GREEN, Style.BOLD)}: \"{color(text, Style.BRIGHT_WHITE, Style.BOLD)}\" (conf: {conf})")
        elif event.event_type == TranscriptEventType.SPEECH_ENDED:
            print(f"    {color('[EVENT]', Style.GRAY)} {color('[SPEECH_ENDED]', Style.BRIGHT_MAGENTA, Style.BOLD)}    (Turn Completed)")

    transcriber.add_event_listener(on_event)

    # Estimate required audio duration based on word count
    word_count = len(script.split())
    nominal_duration_ms = max(1000, word_count * 250)
    total_chunks = (nominal_duration_ms // chunk_ms) + 2

    async with transcriber:
        for chunk_idx in range(1, total_chunks + 1):
            chunk = generate_synthetic_pcm_chunk(chunk_idx, duration_ms=chunk_ms)
            elapsed_ms = chunk_idx * chunk_ms

            if verbose:
                print(
                    color(f"  [Chunk {chunk_idx:02d} | +{chunk_ms}ms ({elapsed_ms:4d}ms) | {len(chunk)}B PCM]", Style.DIM)
                )

            await transcriber.push_audio(chunk)

            # Show live UI projections after certain chunk intervals
            if verbose and (chunk_idx % 5 == 0 or chunk_idx == total_chunks):
                render_ui_projection_box(accumulator, chunk_idx, elapsed_ms)

            if pace_seconds > 0:
                await asyncio.sleep(pace_seconds)

        await transcriber.finish_audio()

    # Render word timing breakdown table
    render_word_timing_table(accumulator.all_words, accumulator.total_duration_ms)

    # Render summary analytics card
    render_session_analytics_card(accumulator, total_chunks, total_chunks * chunk_ms)

    return {
        "session_id": session_id,
        "accumulator": accumulator,
        "transcriber": transcriber,
        "events": emitted_events,
        "snapshot": accumulator.get_snapshot(),
        "total_chunks": total_chunks,
    }


async def run_multi_turn_conversation(
    turns: Optional[List[str]] = None,
    session_id: str = "demo-multi-turn",
    pace_seconds: float = 0.01,
) -> Dict[str, Any]:
    """Demonstrate continuous streaming across multiple conversational turns."""
    if turns is None:
        turns = [
            "Can you explain the difference between processes and threads?",
            "How does Dijkstra's shortest path algorithm work?",
        ]

    print_subbanner(f"Scenario 2: Multi-Turn Continuous Conversation ({session_id})")
    print(color(f"  Simulating {len(turns)} consecutive turns in a shared session stream.\n", Style.ITALIC))

    audio_cfg = AudioConfig(chunk_duration_ms=100)
    transcriber_cfg = TranscriberConfig(audio_config=audio_cfg, interim_results=True, word_timings=True)

    transcriber = FakeTranscriber(
        session_id=session_id,
        config=transcriber_cfg,
        script=turns,
        simulate_realtime=False,
    )
    accumulator = SegmentAccumulator(
        session_id=session_id,
        config=AccumulatorConfig(auto_sort=True, deduplicate_by_id=True),
    )

    turn_counter = 0

    def on_event(event: TranscriptEvent) -> None:
        nonlocal turn_counter
        accumulator.add_event(event)
        if event.event_type == TranscriptEventType.SPEECH_STARTED:
            turn_counter += 1
            print(color(f"\n  >>> Turn {turn_counter} Started [SPEECH_STARTED]", Style.BRIGHT_CYAN, Style.BOLD))
        elif event.event_type == TranscriptEventType.FINAL_TRANSCRIPT:
            text = event.segment.text if event.segment else ""
            print(f"  {color('[OK] Turn Committed:', Style.BRIGHT_GREEN, Style.BOLD)} \"{text}\"")
        elif event.event_type == TranscriptEventType.SPEECH_ENDED:
            print(color(f"  <<< Turn {turn_counter} Concluded [SPEECH_ENDED]", Style.GRAY))

    transcriber.add_event_listener(on_event)

    total_chunks = 0
    async with transcriber:
        for turn_idx, turn_text in enumerate(turns, start=1):
            nominal_ms = max(1000, len(turn_text.split()) * 250)
            chunks_for_turn = (nominal_ms // 100) + 1

            for c in range(chunks_for_turn):
                total_chunks += 1
                chunk = generate_synthetic_pcm_chunk(total_chunks, duration_ms=100)
                await transcriber.push_audio(chunk)
                if pace_seconds > 0:
                    await asyncio.sleep(pace_seconds)

        await transcriber.finish_audio()

    print("\n" + color("  Multi-Turn Accumulation Result:", Style.BOLD))
    for idx, seg in enumerate(accumulator.final_segments, start=1):
        print(f"    Segment {idx} [{seg.start_time_ms:>4}ms - {seg.end_time_ms:>4}ms]: {color(seg.text, Style.BRIGHT_WHITE)}")

    print(f"\n  {color('Total Combined Final Text:', Style.BOLD)} \"{accumulator.get_final_text()}\"")
    print(f"  {color('Total Spanned Duration:', Style.BOLD)}   {accumulator.total_duration_ms} ms")
    print(f"  {color('Total Words Accumulated:', Style.BOLD)} {accumulator.word_count} words")

    return {
        "session_id": session_id,
        "accumulator": accumulator,
        "turns": turns,
        "snapshot": accumulator.get_snapshot(),
    }


async def run_jitter_and_deduplication_demo(
    session_id: str = "demo-jitter-resilience",
) -> Dict[str, Any]:
    """Demonstrate SegmentAccumulator bisection reordering and deduplication."""
    print_subbanner(f"Scenario 3: Network Jitter & Deduplication Resilience ({session_id})")
    print(color("  Simulating out-of-order network arrival and duplicate delivery.\n", Style.ITALIC))

    accumulator = SegmentAccumulator(
        session_id=session_id,
        config=AccumulatorConfig(auto_sort=True, deduplicate_by_id=True),
    )

    # 1. Out-of-Order arrival: Deliver Part 2 before Part 1
    events_ooo = out_of_order_final_events(session_id=session_id)
    print(color("  [Step 1] Ingesting Out-of-Order Events:", Style.BOLD))
    for evt in events_ooo:
        text = evt.segment.text if evt.segment else ""
        start = evt.segment.start_time_ms if evt.segment else 0
        print(f"    Arrived segment @ {start:>4}ms: \"{text}\"")
        accumulator.add_event(evt)

    print(color("  -> Accumulator Chronological Final Text:", Style.GREEN))
    print(f"     \"{accumulator.get_final_text()}\"")

    # Verify order
    assert accumulator.final_segments[0].start_time_ms <= accumulator.final_segments[1].start_time_ms
    print(color("  -> Verified: Strictly ordered by start_time_ms via bisection sort! [PASSED]", Style.BRIGHT_GREEN))

    # 2. Duplicate Delivery: Re-send identical segments
    print(color("\n  [Step 2] Ingesting Duplicate Final Segments (Reconnection Simulation):", Style.BOLD))
    dup_acc = SegmentAccumulator(
        session_id=f"{session_id}-dup",
        config=AccumulatorConfig(deduplicate_by_id=True),
    )
    dup_events = duplicate_final_events(session_id=f"{session_id}-dup")
    for evt in dup_events:
        dup_acc.add_event(evt)

    print(f"    Pushed {len(dup_events)} events containing identical segment ID ('{dup_events[0].segment.id}').")
    print(f"    Final Segments Count in Accumulator: {len(dup_acc.final_segments)} (Expected: 1, duplicate filtered)")
    assert len(dup_acc.final_segments) == 1
    print(color("  -> Verified: Idempotent deduplication preserved stream integrity! [PASSED]", Style.BRIGHT_GREEN))

    return {
        "session_id": session_id,
        "accumulator": accumulator,
        "dup_accumulator": dup_acc,
        "snapshot": accumulator.get_snapshot(),
    }


async def run_error_injection_demo(
    session_id: str = "demo-chaos-injection",
) -> Dict[str, Any]:
    """Demonstrate graceful handling of transcriber error events mid-stream."""
    print_subbanner(f"Scenario 4: Chaos Engineering - Injected STT Failure ({session_id})")
    print(color("  Configuring FakeTranscriber with error_after_chunks=3.\n", Style.ITALIC))

    custom_error = TranscriptError(
        code="NETWORK_SOCKET_TIMEOUT",
        message="Simulated WebSocket heartbeat failure after audio chunk #3.",
        details={"injected_by": "Day7DemoScript", "retryable": True},
    )

    transcriber = FakeTranscriber(
        session_id=session_id,
        script="This utterance will fail mid-stream.",
        error_after_chunks=3,
        simulated_error=custom_error,
    )
    accumulator = SegmentAccumulator(session_id=session_id)

    transcriber.add_event_listener(accumulator.add_event)

    async with transcriber:
        for c in range(1, 6):
            chunk = generate_synthetic_pcm_chunk(c)
            await transcriber.push_audio(chunk)
            print(f"    Pushed chunk #{c} -> Transcriber state: {color(transcriber.state.value, Style.YELLOW)}")
            if transcriber.state.value == "error":
                print(color(f"    [!] Caught Transcriber ERROR after chunk #{c}!", Style.BRIGHT_RED, Style.BOLD))
                break

    print(f"\n  Accumulator Recorded Errors: {len(accumulator.errors)}")
    for err in accumulator.errors:
        print(f"    {color('Code:', Style.RED, Style.BOLD)}    {err.code}")
        print(f"    {color('Message:', Style.RED)} {err.message}")
        print(f"    {color('Details:', Style.GRAY)} {err.details}")

    assert len(accumulator.errors) == 1
    print(color("  -> Verified: Error event recorded cleanly in diagnostic history! [PASSED]", Style.BRIGHT_GREEN))

    return {
        "session_id": session_id,
        "accumulator": accumulator,
        "errors": accumulator.errors,
    }


# ------------------------------------------------------------------------------
# Master Demo Runner
# ------------------------------------------------------------------------------


async def run_chunk_to_transcript_demo(
    mode: str = "all",
    script: Optional[Sequence[str]] = None,
    pace_seconds: float = 0.02,
    chunk_ms: int = 100,
    export_json_path: Optional[str] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Execute the Chunk-to-Transcript demonstration suite."""
    print_banner(
        "Academia AI Voice Co-Pilot - Chunk-to-Transcript Streaming Demo",
        "Speech-to-Text Module -- Week 1 Day 7 Integration Milestone",
    )

    results: Dict[str, Any] = {}

    default_script = (
        "What is the time complexity of quicksort in the worst case?"
        if not script
        else " ".join(script)
    )

    if mode in ("single", "all"):
        single_result = await run_single_turn_streaming(
            script=default_script,
            chunk_ms=chunk_ms,
            pace_seconds=pace_seconds,
            verbose=verbose,
        )
        results["single_turn"] = single_result

    if mode in ("multi", "all"):
        multi_script = list(script) if script and len(script) > 1 else None
        multi_result = await run_multi_turn_conversation(
            turns=multi_script,
            pace_seconds=pace_seconds if pace_seconds < 0.05 else 0.02,
        )
        results["multi_turn"] = multi_result

    if mode in ("jitter", "all"):
        jitter_result = await run_jitter_and_deduplication_demo()
        results["jitter"] = jitter_result

    if mode in ("error", "all"):
        error_result = await run_error_injection_demo()
        results["error"] = error_result

    # Export snapshot to JSON if requested
    if export_json_path:
        primary_acc: SegmentAccumulator = (
            results.get("single_turn", {}).get("accumulator")
            or results.get("multi_turn", {}).get("accumulator")
            or SegmentAccumulator()
        )
        snapshot_dict = primary_acc.get_snapshot().model_dump(mode="json")
        out_path = Path(export_json_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(snapshot_dict, f, indent=2)
        print(f"\n{color('[OK] Exported AccumulatedTranscript snapshot to:', Style.BRIGHT_GREEN)} {out_path.resolve()}")

    width = 76
    line = "=" * width
    print("\n" + color(line, Style.CYAN, Style.BOLD))
    print(color("  DAY 7 DEMO EXECUTION COMPLETE: ALL SCENARIOS PASSED SUCCESSFULLY", Style.BRIGHT_GREEN, Style.BOLD))
    print(color(line, Style.CYAN, Style.BOLD) + "\n")

    return results


# ------------------------------------------------------------------------------
# CLI Parser
# ------------------------------------------------------------------------------


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse command line arguments for the demo runner."""
    parser = argparse.ArgumentParser(
        description="Academia AI Voice Co-Pilot: Chunk-to-Transcript Streaming STT Demo (Day 7 Milestone)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--mode",
        choices=["all", "single", "multi", "jitter", "error"],
        default="all",
        help="Demonstration scenario to execute",
    )
    parser.add_argument(
        "--script",
        nargs="+",
        default=None,
        help="Custom utterance script text to transcribe",
    )
    parser.add_argument(
        "--pace",
        type=float,
        default=0.02,
        help="Simulated delay per audio chunk in seconds (for visual effect)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Run without any pacing delay (instantaneous execution)",
    )
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="Enforce 1.0x real-time pacing (100ms delay per 100ms chunk)",
    )
    parser.add_argument(
        "--chunk-ms",
        type=int,
        default=100,
        help="Duration of each simulated audio chunk in milliseconds",
    )
    parser.add_argument(
        "--export-json",
        type=str,
        default=None,
        help="File path to export the AccumulatedTranscript JSON snapshot",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI styling colors in output",
    )

    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for CLI execution."""
    global COLOR_ENABLED

    args = parse_args(argv)

    if args.no_color or os.getenv("NO_COLOR"):
        COLOR_ENABLED = False

    # Determine pacing delay
    if args.fast:
        pace = 0.0
    elif args.realtime:
        pace = args.chunk_ms / 1000.0
    else:
        pace = args.pace

    try:
        asyncio.run(
            run_chunk_to_transcript_demo(
                mode=args.mode,
                script=args.script,
                pace_seconds=pace,
                chunk_ms=args.chunk_ms,
                export_json_path=args.export_json,
            )
        )
        return 0
    except KeyboardInterrupt:
        print("\n\n" + color("Demo interrupted by user.", Style.YELLOW))
        return 130
    except Exception as exc:
        print("\n\n" + color(f"Demo failed with error: {exc}", Style.RED, Style.BOLD))
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
