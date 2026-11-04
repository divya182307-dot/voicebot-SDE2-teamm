# Ordered Transcript Segment Accumulator & Fixture Engine

This document specifies the design, lifecycle, ordering algorithms, and fixture contracts of the **Ordered Segment Accumulator** for **Academia – AI Voice Co-Pilot**.

---

## 1. Overview & Problem Definition

In streaming voice processing, speech events arrive incrementally over network sockets with variable latency:
* **Speculative Interim Events**: Rapid hypotheses (`is_final=False`) that revise in-flight speech in real time (e.g. `"Why"` $\rightarrow$ `"Why is"` $\rightarrow$ `"Why is this"`).
* **Final Utterances**: Locked-in speech segments (`is_final=True`) with fixed boundaries and word timings.
* **Network Multiplexing Jitter**: Asynchronous events or parallel pipeline stages can cause segments to arrive out-of-order.
* **Duplication**: Reconnections or retry policies may deliver identical final segments more than once.

The **`SegmentAccumulator`** acts as the canonical stateful aggregator that consumes streaming `TranscriptEvent`s and produces ordered, clean, turn-level transcript projections for downstream consumption by LLM Agents, Screen Vision, and the Desktop UI.

```
Incoming Stream (Events & Segments)
                │
                ▼
┌────────────────────────────────────────────────────────┐
│                  SegmentAccumulator                    │
│                                                        │
│  ┌────────────────────────┐  ┌──────────────────────┐  │
│  │ Speculative In-Flight  │  │ Chronological Final  │  │
│  │   active_interim       │  │ final_segments (auto-│  │
│  │  (updates in-place)    │  │   sorted by start_ms)│  │
│  └────────────────────────┘  └──────────────────────┘  │
│                                                        │
│   • Enforces session binding                           │
│   • Idempotent deduplication by segment.id             │
│   • Chronological bisection re-ordering                │
│   • Speech boundary tracking (VAD onset / turn end)    │
└────────────────────────────────────────────────────────┘
                │
                ├────────────────────────┬────────────────────────┐
                ▼                        ▼                        ▼
       Desktop UI Bubble        Multimodal LLM Agent      Session Analytics
    (Real-time live caption)  (Committed Turn Prompt)   (Duration, Word Count)
```

---

## 2. Core Data Models

### 2.1 Configuration (`AccumulatorConfig`)

| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `enforce_session_id` | `bool` | `True` | Rejects events with mismatched `session_id`. |
| `deduplicate_by_id` | `bool` | `True` | Idempotently ignores duplicate final segment IDs without error. |
| `auto_sort` | `bool` | `True` | Maintains final segments strictly ordered by `start_time_ms`. |
| `preserve_interim_on_speech_ended` | `bool` | `False` | Retains active interim hypothesis upon `SPEECH_ENDED`. |

---

### 2.2 Snapshot Representation (`AccumulatedTranscript`)

An immutable, Pydantic-validated representation of the transcript state at any moment:

| Field | Type | Description |
| :--- | :--- | :--- |
| `session_id` | `Optional[str]` | Bound interaction session ID. |
| `final_segments` | `List[TranscriptSegment]` | Chronologically ordered list of committed segments. |
| `active_interim` | `Optional[TranscriptSegment]` | Active speculative hypothesis (or `None`). |
| `final_text` | `str` | Clean joined text of committed final segments. |
| `full_text` | `str` | Combined text (`final_text` + `active_interim.text`). |
| `total_duration_ms` | `int` | Span in ms from earliest start time to latest end time. |
| `average_confidence`| `float` | Duration-weighted average confidence of final segments. |
| `word_count` | `int` | Total count of words across all committed segments. |
| `speech_active` | `bool` | Whether speech activity is ongoing. |
| `errors` | `List[TranscriptError]` | Chronological record of error payloads received. |

---

## 3. Accumulation Semantics

### 3.1 Interim vs. Final Lifecycle

1. **`SPEECH_STARTED`**: Sets `speech_active = True`.
2. **`INTERIM_TRANSCRIPT`**:
   - Replaces `active_interim` in-place.
   - Does **not** modify `final_segments`.
   - `get_full_text()` immediately reflects the updated interim text.
3. **`FINAL_TRANSCRIPT`**:
   - Commits the segment into `final_segments` using binary search insertion (`bisect_left`) based on `start_time_ms`.
   - Clears `active_interim` (preventing duplicate or stale rendering).
4. **`SPEECH_ENDED`**:
   - Sets `speech_active = False`.
   - Clears `active_interim` by default (`preserve_interim_on_speech_ended=False`).

---

### 3.2 Chronological Ordering & Network Jitter Resilience

If segment $B$ ($\text{start}=2000\text{ms}$) arrives before segment $A$ ($\text{start}=0\text{ms}$):
```python
acc.add_segment(segment_b)  # final_segments: [segment_b]
acc.add_segment(segment_a)  # final_segments: [segment_a, segment_b]
assert acc.get_final_text() == "Part A text. Part B text."
```
The accumulator guarantees that downstream consumers always receive logically and chronologically sequenced speech.

---

### 3.3 Text Projections for Multi-Team Use

* **`get_final_text() -> str`**:
  * Returns joined text of locked segments: `"Why is this failing?"`
  * **Intended For**: Multimodal AI Agent prompts, reasoning pipelines, and persistent database storage.
* **`get_interim_text() -> str`**:
  * Returns speculative hypothesis: `"Can you explain"`
  * **Intended For**: Italicized/grayed live preview rendering in the Desktop UI.
* **`get_full_text() -> str`**:
  * Returns `"Why is this failing? Can you explain"`
  * **Intended For**: Seamless real-time caption bubbles.

---

## 4. Standardized Test Fixtures (`src/voice/fixtures.py`)

A comprehensive catalog of canonical fixtures is included for automated testing and cross-team mocking:

| Fixture Function | Description | Event Flow |
| :--- | :--- | :--- |
| `single_utterance_events()` | Single conversational turn. | `SPEECH_STARTED` $\rightarrow$ 3x `INTERIM` $\rightarrow$ 1x `FINAL` (with `WordTiming`s) $\rightarrow$ `SPEECH_ENDED`. |
| `multi_utterance_events()` | Multi-clause student question. | Two distinct speech turns with word-level timings. |
| `out_of_order_final_events()`| Simulated network jitter. | Segment 2 delivered before Segment 1 to verify sorting. |
| `duplicate_final_events()` | Idempotency verification. | Multiple transmissions of identical final segment IDs. |
| `error_event_stream()` | Network / socket crash. | `SPEECH_STARTED` followed by `WEBSOCKET_CONNECTION_RESET` error. |

These are also pre-configured as native `pytest` fixtures in `tests/conftest.py`.

---

## 5. Usage Example

```python
from src.voice import SegmentAccumulator, single_utterance_events

# 1. Initialize accumulator
accumulator = SegmentAccumulator(session_id="lecture-01")

# 2. Feed event stream (from WebSocket or Transcriber)
events = single_utterance_events(session_id="lecture-01")
accumulator.add_events(events)

# 3. Access clean outputs
print("Final Text:", accumulator.get_final_text())
print("Total Words:", accumulator.word_count)
print("Average Confidence:", accumulator.average_confidence)
print("Total Duration (ms):", accumulator.total_duration_ms)

# 4. Generate frozen snapshot
snapshot = accumulator.get_snapshot()
assert snapshot.speech_active is False
```
