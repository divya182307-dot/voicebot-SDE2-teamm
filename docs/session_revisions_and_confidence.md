# Session Association, Revisions, Finalization & Confidence Thresholds

**Milestone:** Week 3 (Days 15–16)  
**Modules:** `src/voice/reconciliation.py`, `src/voice/accumulator.py`, `src/voice/orchestrator.py`  
**Test Suite:** `tests/test_session_and_revisions.py` (14 tests)

---

## 1. Overview & Architectural Goals

Days 15–16 establish the core session integrity and confidence gating policies for streaming Speech-to-Text:
1. **Strict Session Association**: Every transcript event produced or ingested across `TranscriptionOrchestrator`, `TranscriptReconciler`, and `SegmentAccumulator` must carry a non-empty `session_id`. Any attempt to cross-pollinate events across sessions triggers an explicit `SessionMismatchError`.
2. **Interim Revision Tracking**: Speculative interim hypotheses are treated as sequential revisions. As interim hypotheses evolve within a speech turn, they are indexed with monotonic revision numbers (`revision=1, 2, ...`) and metadata (`is_revision=True`, `revision_type="interim_revision"`).
3. **Finalization Events**: When an utterance concludes and transitions from interim to final, the `FINAL_TRANSCRIPT` event carries finalization metadata (`is_finalization=True`, `total_revisions_for_segment`), and resets in-flight revision counters.
4. **Configurable Confidence Thresholds**: Low-confidence segments (e.g. whispered, noisy, or distorted audio) are handled via a configurable `confidence_threshold` supporting three policies:
   - `"tag"`: Flags the event in metadata (`is_low_confidence=True`, `confidence`, `confidence_threshold`) while preserving text delivery.
   - `"filter"`: Completely suppresses low-confidence segments from entering downstream history.
   - `"ignore"`: Emits segments unchanged.

---

## 2. Configuration Parameters

### `ReconciliationConfig` & `AccumulatorConfig`
| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `confidence_threshold` | `float` | `0.0` | Minimum confidence score in `[0.0, 1.0]`. Segments below this trigger low-confidence handling. |
| `low_confidence_action` | `str` | `"tag"` | Strategy for low-confidence segments: `"tag"`, `"filter"`, or `"ignore"`. |
| `track_revisions` | `bool` | `True` | Whether to track revision sequence numbers and finalization flags on events. |
| `enforce_session_id` | `bool` | `True` | Validate and enforce that all ingested events match the active session. |

### `OrchestratorConfig`
| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `confidence_threshold` | `float` | `0.0` | Propagates default confidence threshold to internal reconciler and accumulator. |
| `low_confidence_action` | `str` | `"tag"` | Propagates default policy (`"tag"`, `"filter"`, or `"ignore"`). |
| `enforce_session_id` | `bool` | `True` | Guard ensuring orchestrator only emits and accepts events matching its `session_id`. |

---

## 3. Telemetry & Metrics

### `ReconciliationMetrics`
- `interim_revisions_count`: Count of interim hypothesis revisions processed.
- `finalizations_count`: Count of finalizations committed.
- `low_confidence_tagged_count`: Count of segments flagged as low confidence.
- `low_confidence_suppressed_count`: Count of low-confidence segments dropped.

### `OrchestratorMetrics`
- `interim_revisions_emitted`: Total interim revisions broadcasted.
- `finalizations_emitted`: Total finalization events broadcasted.
- `low_confidence_segments_detected`: Total low-confidence segments detected.
- `low_confidence_segments_suppressed`: Total low-confidence segments dropped.

---

## 4. Usage Example

```python
from src.voice.orchestrator import TranscriptionOrchestrator, OrchestratorConfig

# Configure orchestrator with 0.80 confidence threshold and tagging
config = OrchestratorConfig(
    confidence_threshold=0.80,
    low_confidence_action="tag",
)

orchestrator = TranscriptionOrchestrator(
    session_id="session-user-123",
    config=config,
)

# Stream events
async for event in orchestrator.stream():
    if event.metadata and event.metadata.get("is_low_confidence"):
        print(f"Warning: Low confidence segment (score: {event.segment.confidence})")
    if event.metadata and event.metadata.get("is_revision"):
        print(f"Interim revision #{event.metadata['revision']}: {event.segment.text}")
    if event.metadata and event.metadata.get("is_finalization"):
        print(f"Finalized segment: {event.segment.text}")
```

