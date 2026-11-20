"""Comprehensive test suite for Ordering, Duplicate Suppression, and Interim/Final Reconciliation (Days 10–11 Milestone).

Verifies:
1. Strict chronological ordering of final segments with multi-key tie breaking.
2. Resolution of out-of-order segment arrivals (network jitter simulation).
3. Multi-layer deduplication:
   - Duplicate event IDs.
   - Duplicate segment IDs.
   - Temporal and content duplicates (same start/end time and text).
   - Repeated consecutive interim hypotheses.
4. Interim vs. final reconciliation:
   - Stale interim suppression (interim falling behind committed final boundary).
   - Overlapping interim boundary trimming.
   - Final segment hypothesis commitment and interim clearing.
   - Interim promotion on turn completion (promote_interim_on_speech_ended).
5. Seamless integration with TranscriptionOrchestrator and telemetry metrics.
"""

from __future__ import annotations

import asyncio
from typing import List
import pytest

from src.voice.exceptions import (
    DuplicateSegmentError,
    InvalidEventError,
    SessionMismatchError,
)
from src.voice.fixtures import (
    duplicate_final_events,
    make_event,
    make_segment,
    out_of_order_final_events,
    single_utterance_events,
)
from src.voice.orchestrator import (
    OrchestratorConfig,
    TranscriptionOrchestrator,
)
from src.voice.reconciliation import (
    ReconciliationConfig,
    ReconciliationMetrics,
    TranscriptReconciler,
)
from src.voice.schemas import (
    TranscriptError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


class TestReconcilerOrdering:
    """Validate chronological ordering and out-of-order segment insertion."""

    def test_out_of_order_final_segments_are_reordered(self):
        reconciler = TranscriptReconciler(session_id="order-01")

        # Create later segment [1500ms -> 3000ms]
        seg2 = make_segment("Second clause spoken.", 1500, 3000, is_final=True, segment_id="seg-2")
        # Create earlier segment [0ms -> 1200ms]
        seg1 = make_segment("First clause spoken.", 0, 1200, is_final=True, segment_id="seg-1")

        # Ingest seg2 first
        ev2 = make_event(TranscriptEventType.FINAL_TRANSCRIPT, "order-01", segment=seg2, event_id="ev-2")
        res2 = reconciler.reconcile_event(ev2)
        assert res2 is not None
        assert reconciler.metrics.out_of_order_resolved == 0

        # Ingest seg1 second (out-of-order)
        ev1 = make_event(TranscriptEventType.FINAL_TRANSCRIPT, "order-01", segment=seg1, event_id="ev-1")
        res1 = reconciler.reconcile_event(ev1)
        assert res1 is not None

        # Verify out-of-order metric incremented
        assert reconciler.metrics.out_of_order_resolved == 1

        # Verify strict chronological ordering in final segments
        finals = reconciler.final_segments
        assert len(finals) == 2
        assert finals[0].id == "seg-1"
        assert finals[0].start_time_ms == 0
        assert finals[1].id == "seg-2"
        assert finals[1].start_time_ms == 1500

        # Verify joined speech order
        assert reconciler.get_final_text() == "First clause spoken. Second clause spoken."

    def test_multi_segment_arbitrary_arrival_order(self):
        """Four segments arriving in shuffled order [3, 1, 4, 2]."""
        reconciler = TranscriptReconciler()
        s1 = make_segment("Part 1.", 0, 1000, is_final=True, segment_id="s1")
        s2 = make_segment("Part 2.", 1000, 2000, is_final=True, segment_id="s2")
        s3 = make_segment("Part 3.", 2000, 3000, is_final=True, segment_id="s3")
        s4 = make_segment("Part 4.", 3000, 4000, is_final=True, segment_id="s4")

        # Shuffled arrival
        reconciler.reconcile_final_segment(s3)
        reconciler.reconcile_final_segment(s1)
        reconciler.reconcile_final_segment(s4)
        reconciler.reconcile_final_segment(s2)

        ordered_texts = [s.text for s in reconciler.final_segments]
        assert ordered_texts == ["Part 1.", "Part 2.", "Part 3.", "Part 4."]
        assert reconciler.get_final_text() == "Part 1. Part 2. Part 3. Part 4."

    def test_tie_breaking_same_start_time(self):
        """Tied start_time_ms broken deterministically by end_time_ms and ID."""
        reconciler = TranscriptReconciler()
        sa = make_segment("Longer", 1000, 2500, is_final=True, segment_id="sa")
        sb = make_segment("Shorter", 1000, 1800, is_final=True, segment_id="sb")

        reconciler.reconcile_final_segment(sa)
        reconciler.reconcile_final_segment(sb)

        finals = reconciler.final_segments
        assert finals[0].id == "sb"  # 1800ms end comes before 2500ms
        assert finals[1].id == "sa"


class TestReconcilerDuplicateSuppression:
    """Validate multi-stage deduplication behavior."""

    def test_suppress_duplicate_event_id(self):
        reconciler = TranscriptReconciler(session_id="dup-ev-01")
        seg = make_segment("Speech chunk.", 0, 500, is_final=True, segment_id="seg-dup-1")
        ev = make_event(TranscriptEventType.FINAL_TRANSCRIPT, "dup-ev-01", segment=seg, event_id="same-event-id")

        # First ingestion succeeds
        r1 = reconciler.reconcile_event(ev)
        assert r1 is not None

        # Second ingestion with same event_id is suppressed
        r2 = reconciler.reconcile_event(ev)
        assert r2 is None
        assert reconciler.metrics.duplicates_suppressed == 1
        assert reconciler.metrics.duplicate_events_count == 1
        assert len(reconciler.final_segments) == 1

    def test_suppress_duplicate_segment_id(self):
        reconciler = TranscriptReconciler()
        seg1 = make_segment("Initial delivery.", 0, 500, is_final=True, segment_id="seg-123")
        seg2 = make_segment("Retried delivery.", 0, 500, is_final=True, segment_id="seg-123")

        ev1 = make_event(TranscriptEventType.FINAL_TRANSCRIPT, segment=seg1, event_id="ev-1")
        ev2 = make_event(TranscriptEventType.FINAL_TRANSCRIPT, segment=seg2, event_id="ev-2")

        assert reconciler.reconcile_event(ev1) is not None
        assert reconciler.reconcile_event(ev2) is None  # Suppressed due to duplicate segment_id

        assert reconciler.metrics.duplicates_suppressed == 1
        assert reconciler.metrics.duplicate_segments_count == 1
        assert len(reconciler.final_segments) == 1
        assert reconciler.final_segments[0].text == "Initial delivery."

    def test_suppress_content_and_temporal_duplicate(self):
        """Different segment ID and event ID, but exact same time window and text."""
        reconciler = TranscriptReconciler()
        seg1 = make_segment("What is dynamic programming?", 100, 900, is_final=True, segment_id="id-a")
        seg2 = make_segment("What is dynamic programming?", 100, 900, is_final=True, segment_id="id-b")

        ev1 = make_event(TranscriptEventType.FINAL_TRANSCRIPT, segment=seg1, event_id="ev-a")
        ev2 = make_event(TranscriptEventType.FINAL_TRANSCRIPT, segment=seg2, event_id="ev-b")

        assert reconciler.reconcile_event(ev1) is not None
        assert reconciler.reconcile_event(ev2) is None  # Suppressed content duplicate

        assert reconciler.metrics.duplicates_suppressed == 1
        assert reconciler.metrics.content_duplicates_count == 1
        assert len(reconciler.final_segments) == 1

    def test_deduplicate_disabled_raises_error(self):
        config = ReconciliationConfig(deduplicate_segments_by_id=False)
        reconciler = TranscriptReconciler(config=config)
        seg = make_segment("Strict deduplication.", 0, 500, is_final=True, segment_id="dup-raise")

        reconciler.reconcile_final_segment(seg)
        with pytest.raises(DuplicateSegmentError, match="has already been committed"):
            reconciler.reconcile_final_segment(seg)

    def test_suppress_repeated_interim_text(self):
        reconciler = TranscriptReconciler()
        i1 = make_segment("Thinking", 0, 200, is_final=False, segment_id="i-1")
        i2 = make_segment("Thinking", 0, 300, is_final=False, segment_id="i-1")  # Same text
        i3 = make_segment("Thinking clearly", 0, 500, is_final=False, segment_id="i-1")

        ev1 = make_event(TranscriptEventType.INTERIM_TRANSCRIPT, segment=i1, event_id="e1")
        ev2 = make_event(TranscriptEventType.INTERIM_TRANSCRIPT, segment=i2, event_id="e2")
        ev3 = make_event(TranscriptEventType.INTERIM_TRANSCRIPT, segment=i3, event_id="e3")

        assert reconciler.reconcile_event(ev1) is not None
        assert reconciler.reconcile_event(ev2) is None  # Suppressed as repeated
        assert reconciler.reconcile_event(ev3) is not None

        assert reconciler.metrics.repeated_interims_count == 1
        assert reconciler.metrics.duplicates_suppressed == 1
        assert reconciler.get_interim_text() == "Thinking clearly"


class TestReconcilerInterimFinalReconciliation:
    """Validate interim/final reconciliation lifecycle."""

    def test_stale_interim_suppression(self):
        """Interim arriving after final segment has already committed that audio window is dropped."""
        reconciler = TranscriptReconciler()

        # Final segment committed [0ms -> 2000ms]
        final_seg = make_segment("Committed sentence.", 0, 2000, is_final=True, segment_id="f1")
        reconciler.reconcile_final_segment(final_seg)
        assert reconciler.latest_final_end_time_ms == 2000

        # Delayed stale interim arrives for [500ms -> 1800ms]
        stale_interim = make_segment("Delayed stale word", 500, 1800, is_final=False, segment_id="i-stale")
        ev_stale = make_event(TranscriptEventType.INTERIM_TRANSCRIPT, segment=stale_interim, event_id="ev-stale")

        res = reconciler.reconcile_event(ev_stale)
        assert res is None
        assert reconciler.metrics.stale_interims_count == 1
        assert reconciler.metrics.duplicates_suppressed == 1
        assert reconciler.active_interim is None

    def test_overlapping_interim_start_time_trimmed(self):
        """Interim starting before committed speech ends has its start_time_ms reconciled."""
        reconciler = TranscriptReconciler()

        # Final segment committed [0ms -> 1500ms]
        final_seg = make_segment("First part.", 0, 1500, is_final=True, segment_id="f1")
        reconciler.reconcile_final_segment(final_seg)

        # Interim spans [1000ms -> 2500ms]
        interim = make_segment("Second part developing", 1000, 2500, is_final=False, segment_id="i2")
        ev_interim = make_event(TranscriptEventType.INTERIM_TRANSCRIPT, segment=interim, event_id="ev-i2")

        res = reconciler.reconcile_event(ev_interim)
        assert res is not None
        assert res.segment is not None
        # Start time should be trimmed to latest final end time (1500ms)
        assert res.segment.start_time_ms == 1500
        assert res.segment.end_time_ms == 2500

    def test_final_segment_clears_active_interim(self):
        reconciler = TranscriptReconciler()
        interim = make_segment("What is", 0, 400, is_final=False, segment_id="turn-1")
        reconciler.reconcile_interim_segment(interim)
        assert reconciler.active_interim is not None

        # Final segment arrives
        final = make_segment("What is quicksort?", 0, 1200, is_final=True, segment_id="turn-1")
        reconciler.reconcile_final_segment(final)

        # Interim must be cleared
        assert reconciler.active_interim is None
        assert reconciler.get_final_text() == "What is quicksort?"
        assert reconciler.get_interim_text() == ""
        assert reconciler.get_full_text() == "What is quicksort?"

    def test_promote_interim_on_speech_ended(self):
        """When promote_interim_on_speech_ended=True, unfinalized interim is committed to final."""
        config = ReconciliationConfig(promote_interim_on_speech_ended=True)
        reconciler = TranscriptReconciler(config=config)

        interim = make_segment("Unfinalized last sentence spoken", 0, 1800, is_final=False, segment_id="unfinal-1")
        reconciler.reconcile_interim_segment(interim)
        assert len(reconciler.final_segments) == 0

        # SPEECH_ENDED arrives
        ev_end = make_event(TranscriptEventType.SPEECH_ENDED)
        reconciler.reconcile_event(ev_end)

        # Active interim should now be committed as a final segment
        assert len(reconciler.final_segments) == 1
        assert reconciler.final_segments[0].text == "Unfinalized last sentence spoken"
        assert reconciler.final_segments[0].is_final is True
        assert reconciler.metrics.interims_promoted == 1
        assert reconciler.get_final_text() == "Unfinalized last sentence spoken"


class TestOrchestratorReconciliationIntegration:
    """Validate end-to-end integration of reconciliation inside TranscriptionOrchestrator."""

    def test_orchestrator_suppresses_duplicate_events_in_stream(self):
        async def _run():
            orch = TranscriptionOrchestrator(session_id="orch-rec-01")
            await orch.start()

            # Push duplicate audio/events simulation
            seg = make_segment("Acoustic event", 0, 500, is_final=True, segment_id="dup-seg-orch")
            ev1 = make_event(TranscriptEventType.FINAL_TRANSCRIPT, "orch-rec-01", segment=seg, event_id="ev-orch-1")
            ev2 = make_event(TranscriptEventType.FINAL_TRANSCRIPT, "orch-rec-01", segment=seg, event_id="ev-orch-1")

            # Dispatch through internal event handler
            orch._on_transcriber_event(ev1)
            orch._on_transcriber_event(ev2)  # Duplicate

            await orch.stop()

            # Only 1 event recorded in history and accumulator
            assert len(orch.events_history) == 1
            assert orch.metrics.duplicates_suppressed == 1
            assert len(orch.accumulator.final_segments) == 1

        asyncio.run(_run())

    def test_orchestrator_handles_out_of_order_stream(self):
        async def _run():
            orch = TranscriptionOrchestrator(session_id="orch-rec-02")
            await orch.start()

            s_late = make_segment("Second clause.", 2000, 3500, is_final=True, segment_id="s-late")
            s_early = make_segment("First clause.", 0, 1500, is_final=True, segment_id="s-early")

            ev_late = make_event(TranscriptEventType.FINAL_TRANSCRIPT, "orch-rec-02", segment=s_late, event_id="e-late")
            ev_early = make_event(TranscriptEventType.FINAL_TRANSCRIPT, "orch-rec-02", segment=s_early, event_id="e-early")

            # Ingest late segment first, then early segment
            orch._on_transcriber_event(ev_late)
            orch._on_transcriber_event(ev_early)

            await orch.stop()

            # Verify ordering and metrics
            assert orch.metrics.out_of_order_resolved == 1
            assert orch.get_final_text() == "First clause. Second clause."
            assert orch.accumulator.final_segments[0].id == "s-early"
            assert orch.accumulator.final_segments[1].id == "s-late"

        asyncio.run(_run())

