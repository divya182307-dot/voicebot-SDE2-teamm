"""Day 21: Week 3 End-to-End Integration Tests.

Validates the complete Day 21 Team Gate:
1. Audio events flow through reordering and transcription to the W5 backend stream.
2. Interim hypothesis revisions and finalizations are strictly bound to session.
3. Low-confidence segments respect configurable threshold policies.
4. In-flight cancellation concludes workers and drains queues cleanly.
5. Quota / network failures trigger automatic fallback to FakeTranscriber with zero leaked raw exceptions.
6. The runnable Week 3 integration demo executes all 5 stages and exports structured snapshot evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from scripts.week3_integration_demo import (
    main_async,
    run_stage_1_audio_events_and_reordering,
    run_stage_2_revisions_and_finalization,
    run_stage_3_backend_event_stream,
    run_stage_4_cancellation_barge_in,
    run_stage_5_mock_fallback_on_failure,
)
from src.voice.event_stream import AudioEvent, BackendEventStream
from src.voice.orchestrator import OrchestratorConfig, TranscriptionOrchestrator
from src.voice.schemas import TranscriptEventType


class TestWeek3IntegrationDemoStages:
    """Validate individual stages of the Week 3 integration demo programmatically."""

    @pytest.mark.anyio
    async def test_stage_1_reordering_results(self) -> None:
        res = await run_stage_1_audio_events_and_reordering(fast=True)
        assert res["stage"] == 1
        assert res["chunks_received"] == 4
        assert res["chunks_delivered"] == 5
        assert res["missing_chunks"] == 1
        assert res["out_of_order_resolved"] == 1

    @pytest.mark.anyio
    async def test_stage_2_revisions_results(self) -> None:
        res = await run_stage_2_revisions_and_finalization(fast=True)
        assert res["stage"] == 2
        assert "Quantum" in res["final_text"]
        assert res["revisions"] >= 1
        assert res["finalizations"] == 1
        assert res["confidence"] >= 0.80

    @pytest.mark.anyio
    async def test_stage_3_backend_stream_results(self) -> None:
        res = await run_stage_3_backend_event_stream(fast=True)
        assert res["stage"] == 3
        assert res["events_published"] > 0
        assert res["dialog_events"] == res["events_published"]
        assert res["reasoning_finals"] >= 1
        assert res["ui_events"] == res["events_published"]

    @pytest.mark.anyio
    async def test_stage_4_cancellation_results(self) -> None:
        res = await run_stage_4_cancellation_barge_in(fast=True)
        assert res["stage"] == 4
        assert res["state"] == "cancelled"
        assert res["backend_bus_closed"] is True
        assert res["cancellations_count"] == 1

    @pytest.mark.anyio
    async def test_stage_5_mock_fallback_results(self) -> None:
        res = await run_stage_5_mock_fallback_on_failure(fast=True)
        assert res["stage"] == 5
        assert res["is_fallback_active"] is True
        assert res["fallbacks_triggered"] == 1
        assert res["provider"] == "FakeTranscriber"
        assert res["normalized_errors"] == 1
        assert "recovered" in res["recovered_text"].lower()


class TestWeek3IntegrationDemoExecution:
    """Validate full demo execution and JSON evidence snapshot generation."""

    @pytest.mark.anyio
    async def test_full_demo_run_and_snapshot_export(self, tmp_path: Path) -> None:
        export_file = tmp_path / "week3_test_evidence.json"
        exit_code = await main_async(fast=True, export_path=str(export_file))
        assert exit_code == 0
        assert export_file.exists()

        data = json.loads(export_file.read_text(encoding="utf-8"))
        assert data["milestone"] == "Week 3 (Day 21)"
        assert data["offline_mode"] is True
        assert "stage_1" in data["stages"]
        assert "stage_2" in data["stages"]
        assert "stage_3" in data["stages"]
        assert "stage_4" in data["stages"]
        assert "stage_5" in data["stages"]
        assert data["elapsed_seconds"] < 10.0


class TestDay21TeamGateInvariants:
    """Validate Day 21 acceptance criteria in an end-to-end multi-component pipeline."""

    @pytest.mark.anyio
    async def test_end_to_end_team_gate_flow(self) -> None:
        """Full session flowing through W1 audio, transcription, and W5 backend stream."""
        session_id = "day21-gate-session"
        backend = BackendEventStream(session_id=session_id)

        config = OrchestratorConfig(
            confidence_threshold=0.75,
            low_confidence_action="tag",
            enforce_session_id=True,
            enable_audio_reordering=True,
            audio_reorder_window=3,
        )
        orch = TranscriptionOrchestrator(
            session_id=session_id,
            script="Integration gate verified across audio transcription and backend.",
            config=config,
        )
        orch.connect_backend_stream(backend)

        # 1. Ingest AudioStarted
        await orch.push_audio_event(AudioEvent.started(session_id))
        assert orch.is_running

        # 2. Ingest out-of-order audio packets (0, 2, 1, 3)
        chunk = b"\x05\x00" * 1600
        await orch.push_audio_event(AudioEvent.chunk(session_id, chunk, chunk_index=0))
        await orch.push_audio_event(AudioEvent.chunk(session_id, chunk, chunk_index=2))
        await orch.push_audio_event(AudioEvent.chunk(session_id, chunk, chunk_index=1))
        await orch.push_audio_event(AudioEvent.chunk(session_id, chunk, chunk_index=3))

        # 3. Conclude audio
        await orch.push_audio_event(AudioEvent.ended(session_id))
        await orch.stop()

        # Invariants Check:
        assert orch.metrics.audio_chunks_reordered >= 1
        assert backend.is_closed is True
        assert backend.events_published > 0
        assert all(ev.session_id == session_id for ev in backend.history)

        final_events = [ev for ev in backend.history if ev.event_type == TranscriptEventType.FINAL_TRANSCRIPT]
        assert len(final_events) == 1
        final_seg = final_events[0].segment
        assert final_seg is not None
        assert "Integration gate verified" in final_seg.text
        assert final_seg.confidence >= 0.75
