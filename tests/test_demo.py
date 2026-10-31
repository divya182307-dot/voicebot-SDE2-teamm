"""Automated test suite for Day 7 Chunk-to-Transcript Demo Script.

Verifies end-to-end streaming audio chunk ingestion, lifecycle event progression,
ordered segment accumulator integration, and CLI execution.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from demo import main as root_main
from scripts.chunk_to_transcript_demo import (
    generate_synthetic_pcm_chunk,
    main as demo_main,
    run_chunk_to_transcript_demo,
    run_error_injection_demo,
    run_jitter_and_deduplication_demo,
    run_multi_turn_conversation,
    run_single_turn_streaming,
)
from scripts.demo_chunk_to_transcript import main as alias_main
from src.voice.accumulator import AccumulatedTranscript
from src.voice.schemas import TranscriptEventType


class TestSyntheticAudioChunkGeneration:
    """Validate acoustic PCM chunk synthesis."""

    def test_chunk_duration_and_byte_size(self):
        """100ms at 16kHz 16-bit mono must yield exactly 3200 bytes."""
        chunk = generate_synthetic_pcm_chunk(chunk_index=0, sample_rate=16000, duration_ms=100)
        assert isinstance(chunk, bytes)
        assert len(chunk) == 3200

    def test_consecutive_chunks_vary(self):
        """Consecutive chunks must synthesize dynamic waveforms."""
        c0 = generate_synthetic_pcm_chunk(0)
        c1 = generate_synthetic_pcm_chunk(1)
        assert len(c0) == len(c1) == 3200
        assert c0 != c1


class TestStreamingScenarios:
    """Validate programmatic execution of each demo scenario."""

    def test_single_turn_streaming(self):
        """Test real-time single turn chunk-to-transcript flow."""

        async def _run():
            script_text = "What is the time complexity of quicksort in the worst case?"
            res = await run_single_turn_streaming(
                script=script_text,
                session_id="test-single",
                chunk_ms=100,
                pace_seconds=0.0,
                verbose=False,
            )

            acc = res["accumulator"]
            assert acc.session_id == "test-single"
            assert acc.get_final_text() == script_text
            assert acc.word_count == 11
            assert acc.average_confidence >= 0.9
            assert len(acc.final_segments) == 1
            assert len(acc.all_words) == 11

            # Check emitted event lifecycle
            event_types = [e.event_type for e in res["events"]]
            assert TranscriptEventType.SPEECH_STARTED in event_types
            assert TranscriptEventType.INTERIM_TRANSCRIPT in event_types
            assert TranscriptEventType.FINAL_TRANSCRIPT in event_types
            assert TranscriptEventType.SPEECH_ENDED in event_types

            # Verify snapshot model validity
            snapshot = res["snapshot"]
            assert isinstance(snapshot, AccumulatedTranscript)
            assert snapshot.final_text == script_text
            assert not snapshot.speech_active

        asyncio.run(_run())

    def test_multi_turn_streaming(self):
        """Test continuous stream across multiple conversational turns."""

        async def _run():
            turns = [
                "Can you explain the difference between processes and threads?",
                "How does Dijkstra's shortest path algorithm work?",
            ]
            res = await run_multi_turn_conversation(turns=turns, session_id="test-multi", pace_seconds=0.0)

            acc = res["accumulator"]
            assert len(acc.final_segments) == 2
            assert acc.final_segments[0].text == turns[0]
            assert acc.final_segments[1].text == turns[1]
            assert acc.get_final_text() == f"{turns[0]} {turns[1]}"
            assert acc.word_count > 10

        asyncio.run(_run())

    def test_jitter_and_deduplication_resilience(self):
        """Test bisection reordering and idempotent deduplication."""

        async def _run():
            res = await run_jitter_and_deduplication_demo(session_id="test-jitter")
            acc = res["accumulator"]
            dup_acc = res["dup_accumulator"]

            # Jitter: Segments ordered chronologically
            assert len(acc.final_segments) == 2
            assert acc.final_segments[0].start_time_ms < acc.final_segments[1].start_time_ms
            assert "Introduction to data structures." in acc.final_segments[0].text

            # Deduplication: Duplicate segment discarded
            assert len(dup_acc.final_segments) == 1

        asyncio.run(_run())

    def test_error_injection_resilience(self):
        """Test that transcriber errors are captured in accumulator diagnostic history."""

        async def _run():
            res = await run_error_injection_demo(session_id="test-error")
            acc = res["accumulator"]
            assert len(acc.errors) == 1
            assert acc.errors[0].code == "NETWORK_SOCKET_TIMEOUT"

        asyncio.run(_run())

    def test_master_runner_all_modes(self, tmp_path: Path):
        """Test run_chunk_to_transcript_demo master runner with export."""

        async def _run():
            export_file = tmp_path / "snapshot.json"
            res = await run_chunk_to_transcript_demo(
                mode="all",
                pace_seconds=0.0,
                export_json_path=str(export_file),
                verbose=False,
            )

            assert "single_turn" in res
            assert "multi_turn" in res
            assert "jitter" in res
            assert "error" in res
            assert export_file.exists()

            with open(export_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            snapshot = AccumulatedTranscript.model_validate(data)
            assert snapshot.word_count > 0

        asyncio.run(_run())


class TestCliExecution:
    """Validate CLI execution and aliases via main entry points."""

    def test_run_primary_script_cli(self):
        """demo_main() with single turn must exit with code 0."""
        rc = demo_main(["--fast", "--no-color", "--mode", "single"])
        assert rc == 0

    def test_run_demo_alias_script_cli(self):
        """alias_main() with jitter scenario must exit with code 0."""
        rc = alias_main(["--fast", "--no-color", "--mode", "jitter"])
        assert rc == 0

    def test_run_root_demo_script_cli(self):
        """root_main() with error scenario must exit with code 0."""
        rc = root_main(["--fast", "--no-color", "--mode", "error"])
        assert rc == 0
