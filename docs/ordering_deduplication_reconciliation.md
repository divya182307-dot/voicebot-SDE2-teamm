# Ordering, Duplicate Suppression & Interim/Final Reconciliation (Days 10–11 Milestone)

This document describes the stream ordering, multi-layer deduplication, and interim-to-final reconciliation architecture implemented for **Week 2 (Days 10–11)** of the **Academia AI Voice Co-Pilot**.

---

## 1. Overview & Architecture

In real-world speech recognition pipelines, network jitter, out-of-order WebSocket packet arrival, and provider re-transmissions can lead to:
* Out-of-order speech segments.
* Duplicate events and duplicate committed utterances.
* Stale or repeated speculative interim hypotheses.

The `TranscriptReconciler` acts as a stream gatekeeper between provider adapters and downstream consumers (UI captioning and LLM agent prompts).

```
              [ Raw Provider Events ]
                        │
                        ▼
       ┌─────────────────────────────────┐
       │       TranscriptReconciler      │
       │                                 │
       │  1. Duplicate Event ID Check    │ ───► Suppress Duplicates
       │  2. Duplicate Segment ID Check  │ ───► Suppress Duplicates
       │  3. Content/Temporal Overlap    │ ───► Suppress Duplicates
       │  4. Repeated Interim Filter     │ ───► Suppress Consecutive Repeats
       │  5. Stale Interim Check         │ ───► Drop Stale Hypotheses
       │  6. Overlap Boundary Trimming   │ ───► Reconcile Start Time
       │  7. Strict Chronological Sort   │ ───► Reorder Jitter
       └────────────────┬────────────────┘
                        │
                        ▼ [ Reconciled Clean Events ]
       ┌─────────────────────────────────┐
       │      TranscriptionOrchestrator  │
       │    (SegmentAccumulator + Stream)│
       └─────────────────────────────────┘
```

---

## 2. Core Capabilities

### A. Strict Chronological Ordering
* **Multi-Key Sorting**: Primary ordering by `start_time_ms`, secondary by `end_time_ms`, and tertiary by segment `id`.
* **Out-of-Order Jitter Resolution**: When an earlier segment arrives after a later segment (e.g. Turn 2 arrives before Turn 1 due to network rerouting), the reconciler inserts it at its exact chronological position using bisection search.
* **Telemetry**: Tracks `out_of_order_resolved` metrics.

### B. Multi-Layer Duplicate Suppression
1. **Event-Level Deduplication**: If an identical `event_id` is received more than once, it is filtered immediately.
2. **Segment ID Deduplication**: If a segment with an already-committed `id` arrives, it is idempotently ignored (`deduplicate_segments_by_id=True`).
3. **Temporal & Content Deduplication**: Identical speech content covering the exact same time window `[start_time_ms, end_time_ms]` is detected and suppressed.
4. **Repeated Interim Suppression**: Successive 100ms frames that repeat identical interim speculative text are filtered to prevent unnecessary UI renders.

### C. Interim / Final Reconciliation
1. **Stale Interim Dropping**: If a delayed interim event arrives whose `end_time_ms <= committed_final_end_ms`, it refers to an audio window that has already finalized. It is dropped.
2. **Boundary Trimming**: If an interim starts before committed speech ends (`start_time_ms < latest_final_end < end_time_ms`), its `start_time_ms` is adjusted to the boundary of committed speech.
3. **Hypothesis Resolution**: Final segments lock the text and clear active speculative hypotheses.
4. **Interim Promotion (`promote_interim_on_speech_ended`)**: Optionally converts remaining in-flight interims to final transcripts on silence/hangup so words are never lost.

---

## 3. Configuration & Metrics

```python
from src.voice import ReconciliationConfig, TranscriptReconciler

config = ReconciliationConfig(
    deduplicate_events=True,
    deduplicate_segments_by_id=True,
    deduplicate_by_content=True,
    suppress_repeated_interims=True,
    suppress_stale_interims=True,
    reconcile_overlapping_interims=True,
    auto_sort_finals=True,
    promote_interim_on_speech_ended=False,
)

reconciler = TranscriptReconciler(session_id="lecture-01", config=config)
```

### Telemetry Tracked (`ReconciliationMetrics`):
* `total_events_processed`
* `duplicates_suppressed`
* `duplicate_events_count`
* `duplicate_segments_count`
* `content_duplicates_count`
* `repeated_interims_count`
* `stale_interims_count`
* `out_of_order_resolved`
* `finals_committed`
* `interims_promoted`

---

## 4. Test Suite

Validated by **14 tests** in `tests/test_reconciliation.py`:
```bash
python -m pytest tests/test_reconciliation.py -v
```
All **124 tests** pass across the entire Voicebot repository.

