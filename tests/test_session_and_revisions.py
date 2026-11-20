"""Tests for Day 15-16: Session association, revision/finalization events, and confidence thresholds.

Verifies:
1. Strict session association across all events and components.
2. Sequential revision tracking on interim hypotheses and finalization events.
3. Configurable confidence thresholds (tag, filter, and ignore policies).
4. Multi-session isolation and telemetry tracking.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import pytest

from src.voice.accumulator import AccumulatorConfig, SegmentAccumulator
from src.voice.adapter import AudioConfig
from src.voice.exceptions import InvalidEventError, SessionMismatchError
from src.voice.fake_transcriber import FakeTranscriber
from src.voice.orchestrator import OrchestratorConfig, TranscriptionOrchestrator
from src.voice.reconciliation import ReconciliationConfig, TranscriptReconciler
from src.voice.schemas import (
    TranscriptError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
    WordTiming,
)


def make_segment(
    seg_id: str = "seg-1",
    text: str = "Hello world",
    start_ms: int = 0,
    end_ms: int = 500,
    confidence: float = 0.95,
    is_final: bool = False,
) -> TranscriptSegment:
    """Helper to construct valid TranscriptSegments."""
    return TranscriptSegment(
        id=seg_id,
        start_time_ms=start_ms,
        end_time_ms=end_ms,
        text=text,
        confidence=confidence,
        is_final=is_final,
    )


def make_event(
    session_id: str,
    event_type: TranscriptEventType,
    segment: TranscriptSegment | None = None,
    seq: int = 1,
    metadata: dict | None = None,
) -> TranscriptEvent:
    """Helper to construct valid TranscriptEvents."""
    return TranscriptEvent(
        session_id=session_id,
        event_type=event_type,
        segment=segment,
        sequence_number=seq,
        metadata=metadata,
    )


# ==============================================================================
# 1. Session Association Tests
# ==============================================================================

class TestSessionAssociation:
    """Verify strict session association enforcement across all pipeline layers."""

    def test_reconciler_enforces_session_matching(self):
        reconciler = TranscriptReconciler(session_id="session-100")
        seg = make_segment(is_final=False)
        valid_evt = make_event(session_id="session-100", event_type=TranscriptEventType.INTERIM_TRANSCRIPT, segment=seg)

        res = reconciler.reconcile_event(valid_evt)
        assert res is not None
        assert res.session_id == "session-100"

        # Foreign session event must raise SessionMismatchError
        foreign_evt = make_event(session_id="session-FOREIGN", event_type=TranscriptEventType.INTERIM_TRANSCRIPT, segment=seg)
        with pytest.raises(SessionMismatchError, match="does not match reconciler session"):
            reconciler.reconcile_event(foreign_evt)

    def test_accumulator_enforces_session_matching(self):
        accumulator = SegmentAccumulator(session_id="session-200")
        seg = make_segment(is_final=False)
        valid_evt = make_event(session_id="session-200", event_type=TranscriptEventType.INTERIM_TRANSCRIPT, segment=seg)
        accumulator.add_event(valid_evt)

        foreign_evt = make_event(session_id="session-UNKNOWN", event_type=TranscriptEventType.INTERIM_TRANSCRIPT, segment=seg)
        with pytest.raises(SessionMismatchError, match="does not match accumulator session"):
            accumulator.add_event(foreign_evt)

    def test_orchestrator_enforces_session_id_on_incoming_events(self):
        orch = TranscriptionOrchestrator(session_id="session-300")
        seg = make_segment(is_final=False)
        foreign_evt = make_event(session_id="session-ROGUE", event_type=TranscriptEventType.INTERIM_TRANSCRIPT, segment=seg)

        with pytest.raises(SessionMismatchError, match="does not match orchestrator session"):
            orch._on_transcriber_event(foreign_evt)

    def test_multi_session_isolation(self):
        reconciler_a = TranscriptReconciler(session_id="session-A")
        reconciler_b = TranscriptReconciler(session_id="session-B")

        seg_a = make_segment(seg_id="seg-a", text="Speech from session A", is_final=True)
        seg_b = make_segment(seg_id="seg-b", text="Speech from session B", is_final=True)

        evt_a = make_event("session-A", TranscriptEventType.FINAL_TRANSCRIPT, seg_a)
        evt_b = make_event("session-B", TranscriptEventType.FINAL_TRANSCRIPT, seg_b)

        res_a = reconciler_a.reconcile_event(evt_a)
        res_b = reconciler_b.reconcile_event(evt_b)

        assert res_a is not None and res_a.session_id == "session-A"
        assert res_b is not None and res_b.session_id == "session-B"
        assert len(reconciler_a.final_segments) == 1
        assert len(reconciler_b.final_segments) == 1
        assert reconciler_a.final_segments[0].text == "Speech from session A"
        assert reconciler_b.final_segments[0].text == "Speech from session B"


# ==============================================================================
# 2. Revision & Finalization Events Tests
# ==============================================================================

class TestRevisionAndFinalizationEvents:
    """Verify hypothesis revision counts, finalization metadata, and lifecycles."""

    def test_interim_hypothesis_sequential_revisions(self):
        reconciler = TranscriptReconciler(session_id="session-rev-1")

        # Emitting 3 progressively updated interim hypotheses
        h1 = make_segment(seg_id="seg-1", text="The", is_final=False)
        h2 = make_segment(seg_id="seg-1", text="The quick", is_final=False)
        h3 = make_segment(seg_id="seg-1", text="The quick brown fox", is_final=False)

        e1 = reconciler.reconcile_event(make_event("session-rev-1", TranscriptEventType.INTERIM_TRANSCRIPT, h1, seq=1))
        e2 = reconciler.reconcile_event(make_event("session-rev-1", TranscriptEventType.INTERIM_TRANSCRIPT, h2, seq=2))
        e3 = reconciler.reconcile_event(make_event("session-rev-1", TranscriptEventType.INTERIM_TRANSCRIPT, h3, seq=3))

        assert e1 is not None and e1.metadata["revision"] == 1
        assert e1.metadata["is_revision"] is True
        assert e1.metadata["revision_type"] == "interim_revision"

        assert e2 is not None and e2.metadata["revision"] == 2
        assert e3 is not None and e3.metadata["revision"] == 3
        assert reconciler.current_interim_revision == 3
        assert reconciler.metrics.interim_revisions_count == 3

    def test_finalization_event_transitions_and_metadata(self):
        reconciler = TranscriptReconciler(session_id="session-rev-2")

        # Two interims followed by a finalization
        h1 = make_segment(seg_id="seg-1", text="Speech", is_final=False)
        h2 = make_segment(seg_id="seg-1", text="Speech recognition", is_final=False)
        final_seg = make_segment(seg_id="seg-1", text="Speech recognition is awesome.", is_final=True)

        reconciler.reconcile_event(make_event("session-rev-2", TranscriptEventType.INTERIM_TRANSCRIPT, h1))
        reconciler.reconcile_event(make_event("session-rev-2", TranscriptEventType.INTERIM_TRANSCRIPT, h2))

        final_evt = reconciler.reconcile_event(make_event("session-rev-2", TranscriptEventType.FINAL_TRANSCRIPT, final_seg))

        assert final_evt is not None
        assert final_evt.metadata["is_finalization"] is True
        assert final_evt.metadata["total_revisions_for_segment"] == 2
        assert reconciler.current_interim_revision == 0
        assert reconciler.metrics.finalizations_count == 1
        assert reconciler.metrics.finals_committed == 1

    def test_speech_ended_resets_revision_counter(self):
        reconciler = TranscriptReconciler(session_id="session-rev-3")
        h1 = make_segment(seg_id="seg-1", text="Testing revision reset", is_final=False)
        reconciler.reconcile_event(make_event("session-rev-3", TranscriptEventType.INTERIM_TRANSCRIPT, h1))
        assert reconciler.current_interim_revision == 1

        end_evt = make_event("session-rev-3", TranscriptEventType.SPEECH_ENDED)
        reconciler.reconcile_event(end_evt)
        assert reconciler.current_interim_revision == 0

    def test_accumulator_tracks_revisions_and_snapshot(self):
        acc = SegmentAccumulator(session_id="session-acc-rev")
        h1 = make_segment(seg_id="seg-1", text="Machine", is_final=False)
        h2 = make_segment(seg_id="seg-1", text="Machine learning", is_final=False)

        acc.add_event(make_event("session-acc-rev", TranscriptEventType.INTERIM_TRANSCRIPT, h1))
        assert acc.current_interim_revision == 1
        assert acc.total_revisions == 1

        acc.add_event(make_event("session-acc-rev", TranscriptEventType.INTERIM_TRANSCRIPT, h2))
        assert acc.current_interim_revision == 2
        assert acc.total_revisions == 2

        final_seg = make_segment(seg_id="seg-1", text="Machine learning works.", is_final=True)
        acc.add_event(make_event("session-acc-rev", TranscriptEventType.FINAL_TRANSCRIPT, final_seg))
        assert acc.current_interim_revision == 0
        assert acc.total_revisions == 2

        snap = acc.get_snapshot()
        assert snap.revisions_count == 2
        assert snap.final_text == "Machine learning works."


# ==============================================================================
# 3. Confidence Thresholds Tests
# ==============================================================================

class TestConfidenceThresholds:
    """Verify confidence gating (tag, filter, and ignore policies)."""

    def test_tag_policy_marks_low_confidence_segments(self):
        cfg = ReconciliationConfig(confidence_threshold=0.80, low_confidence_action="tag")
        reconciler = TranscriptReconciler(session_id="session-conf-1", config=cfg)

        # Low confidence segment (0.65 < 0.80)
        low_seg = make_segment(seg_id="seg-low", text="muffled words", confidence=0.65, is_final=True)
        e_low = reconciler.reconcile_event(make_event("session-conf-1", TranscriptEventType.FINAL_TRANSCRIPT, low_seg))

        assert e_low is not None
        assert e_low.metadata["is_low_confidence"] is True
        assert e_low.metadata["confidence"] == 0.65
        assert e_low.metadata["confidence_threshold"] == 0.80
        assert reconciler.metrics.low_confidence_tagged_count == 1
        assert reconciler.metrics.low_confidence_suppressed_count == 0

        # High confidence segment (0.92 >= 0.80)
        high_seg = make_segment(seg_id="seg-high", text="clear speech", confidence=0.92, is_final=True)
        e_high = reconciler.reconcile_event(make_event("session-conf-1", TranscriptEventType.FINAL_TRANSCRIPT, high_seg))

        assert e_high is not None
        assert e_high.metadata["is_low_confidence"] is False

    def test_filter_policy_drops_low_confidence_segments(self):
        cfg = ReconciliationConfig(confidence_threshold=0.85, low_confidence_action="filter")
        reconciler = TranscriptReconciler(session_id="session-conf-2", config=cfg)

        # Segment below 0.85 should be completely suppressed
        low_seg = make_segment(seg_id="seg-low", text="whispering", confidence=0.70, is_final=True)
        e_low = reconciler.reconcile_event(make_event("session-conf-2", TranscriptEventType.FINAL_TRANSCRIPT, low_seg))

        assert e_low is None
        assert reconciler.metrics.low_confidence_suppressed_count == 1
        assert len(reconciler.final_segments) == 0

        # Segment above threshold is admitted
        high_seg = make_segment(seg_id="seg-high", text="loud speech", confidence=0.95, is_final=True)
        e_high = reconciler.reconcile_event(make_event("session-conf-2", TranscriptEventType.FINAL_TRANSCRIPT, high_seg))

        assert e_high is not None
        assert len(reconciler.final_segments) == 1

    def test_accumulator_records_low_confidence_segments(self):
        cfg = AccumulatorConfig(confidence_threshold=0.75, filter_low_confidence=True)
        acc = SegmentAccumulator(session_id="session-conf-3", config=cfg)

        seg_low = make_segment(seg_id="seg-1", text="poor audio", confidence=0.50, is_final=True)
        acc.add_event(make_event("session-conf-3", TranscriptEventType.FINAL_TRANSCRIPT, seg_low))

        assert len(acc.low_confidence_segments) == 1
        assert acc.low_confidence_segments[0].id == "seg-1"
        # Since filter_low_confidence is True, final_text should remain empty
        assert acc.get_final_text() == ""
        assert acc.get_snapshot().low_confidence_count == 1

        # Clear segment above threshold
        seg_ok = make_segment(seg_id="seg-2", text="clean audio", confidence=0.90, is_final=True)
        acc.add_event(make_event("session-conf-3", TranscriptEventType.FINAL_TRANSCRIPT, seg_ok))
        assert acc.get_final_text() == "clean audio"


# ==============================================================================
# 4. Orchestrator Integration Tests for D15-16
# ==============================================================================

class TestOrchestratorSessionAndRevisions:
    """Verify TranscriptionOrchestrator end-to-end integration of D15-16 features."""

    def test_orchestrator_initialization_with_confidence_threshold(self):
        cfg = OrchestratorConfig(
            confidence_threshold=0.85,
            low_confidence_action="tag",
        )
        orch = TranscriptionOrchestrator(session_id="orch-conf-session", config=cfg)

        assert orch.config.confidence_threshold == 0.85
        assert orch.reconciler.config.confidence_threshold == 0.85
        assert orch.accumulator.config.confidence_threshold == 0.85

    def test_orchestrator_processes_audio_with_revisions_and_finalization(self):
        async def _run():
            cfg = OrchestratorConfig(confidence_threshold=0.50)
            orch = TranscriptionOrchestrator(
                session_id="orch-e2e-session",
                script="Python is great.",
                config=cfg,
            )

            chunk = b"\x00" * 3200
            for _ in range(6):
                await orch.push_audio(chunk)
            await orch.finish_audio()
            await orch.stop()

            events = orch.events_history
            assert len(events) >= 3

            # Every event must carry orchestrator session_id
            for e in events:
                assert e.session_id == "orch-e2e-session"

            # Check that interims carry revision metadata
            interim_evts = [e for e in events if e.event_type == TranscriptEventType.INTERIM_TRANSCRIPT]
            if interim_evts:
                for idx, ievt in enumerate(interim_evts):
                    assert ievt.metadata["is_revision"] is True
                    assert ievt.metadata["revision"] == idx + 1

            # Check that final transcript carries finalization metadata
            final_evts = [e for e in events if e.event_type == TranscriptEventType.FINAL_TRANSCRIPT]
            assert len(final_evts) >= 1
            for fevt in final_evts:
                assert fevt.metadata["is_finalization"] is True

            # Verify orchestrator metrics
            metrics = orch.metrics
            assert metrics.events_emitted == len(events)
            assert metrics.finalizations_emitted >= 1

        asyncio.run(_run())

    def test_orchestrator_filters_low_confidence_when_configured(self):
        async def _run():
            # Set high threshold (0.999) with filter action
            cfg = OrchestratorConfig(
                confidence_threshold=0.999,
                low_confidence_action="filter",
            )
            orch = TranscriptionOrchestrator(
                session_id="orch-filter-session",
                script="Testing confidence filter.",
                config=cfg,
            )

            chunk = b"\x00" * 3200
            for _ in range(6):
                await orch.push_audio(chunk)
            await orch.finish_audio()
            await orch.stop()

            # Because threshold is 0.999, segments with normal confidence (~0.95-0.98) will be filtered
            metrics = orch.metrics
            assert metrics.low_confidence_segments_suppressed > 0

        asyncio.run(_run())

