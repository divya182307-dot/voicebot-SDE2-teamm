# W1 Audio Events & W5 Backend Event Stream Integration

**Milestone:** Week 3 (Days 19–20)  
**Modules:** `src/voice/event_stream.py`, `src/voice/orchestrator.py`, `src/voice/__init__.py`  
**Test Suite:** `tests/test_event_stream_integration.py` (21 tests)  
**Overall Test Suite:** 214 passing tests (100% offline, 0 external API keys required)

---

## 1. Overview & Architectural Goals

Week 3 Days 19–20 bridge the core speech-to-text pipeline to its upstream capture and downstream intelligence layers:
1. **Upstream W1 Audio Events Integration**: Ingestion of structured `AudioEvent` packets emitted by the audio capture pipeline, handling network jitter, out-of-order packet delivery, and missing audio chunks.
2. **AudioStreamReorderer**: A resilient sliding-window sequencing buffer that sorts out-of-order chunks chronologically, detects packet loss gaps, inserts zero-padded synthetic silence to preserve STT timeline alignment, and drops stale late arrivals.
3. **Downstream W5 Backend Event Stream Integration**: An asynchronous pub/sub multiplexing event bus (`BackendEventStream`) delivering finalized and revised `TranscriptEvent` instances in real time to the dialog manager, LLM reasoning agent, workflow policy engine, and UI WebSocket gateways.
4. **Session Integrity & Safe Teardown**: Strict session correlation across audio ingestion and backend distribution, alongside automatic propagation of cancellations and graceful stream conclusion.

---

## 2. W1 Audio Event Architecture

### Schema Definition: `AudioEvent`
Compliant with Week 1 data contracts and Pydantic validation:

| Field | Type | Description |
| :--- | :--- | :--- |
| `session_id` | `str` | Mandatory session identifier correlating upstream audio to downstream session state |
| `event_type` | `AudioEventType` | Classification: `AUDIO_STARTED`, `AUDIO_CHUNK`, or `AUDIO_ENDED` |
| `chunk_index` | `Optional[int]` | Sequential 0-based chunk counter used for ordering and gap detection |
| `data` | `Optional[bytes]` | Raw 16-bit linear PCM audio payload (required for `AUDIO_CHUNK`) |
| `timestamp_ms` | `Optional[int]` | Stream-relative offset in milliseconds |
| `sample_rate` | `int` | Sampling frequency in Hz (8 kHz to 48 kHz, default: 16,000) |
| `channels` | `int` | Channel count (1 for mono, 2 for stereo) |
| `is_last` | `bool` | Flag indicating the terminal audio chunk of speech |
| `metadata` | `Optional[dict]` | Diagnostic attributes and packet telemetry |

### Lifecycle Factory Methods
- `AudioEvent.started(session_id, sample_rate, channels, metadata)`: Signals audio capture onset and resets sequencing buffers.
- `AudioEvent.chunk(session_id, data, chunk_index, timestamp_ms, sample_rate, channels, is_last, metadata)`: Carries raw audio payloads.
- `AudioEvent.ended(session_id, metadata)`: Signals audio capture termination, triggering reorderer flush and audio finalization.

---

## 3. Resilient Audio Stream Reorderer

The `AudioStreamReorderer` buffers early-arriving packets and resolves sequence gaps:

```
[Upstream Audio] ---> [AudioStreamReorderer] ---> [Transcription Pipeline]
   (0, 2, 1, 3)             Window: 5                  (0, 1, 2, 3)
```

### Core Mechanisms
1. **In-Order Immediate Delivery**: Chunks arriving with `chunk_index == expected_index` are emitted immediately, followed by any contiguous buffered chunks.
2. **Out-of-Order Buffering**: Future chunks (`chunk_index > expected_index`) are buffered until missing predecessor chunks arrive.
3. **Missing Chunk Gap Compensation**: If `max(buffered) - expected >= reorder_window`, a network loss is declared:
   - Gap count is calculated and recorded in `metrics.missing_chunks_detected`.
   - If `fill_missing_chunks=True`, synthetic zero-byte silence packets (`metadata={"synthetic_fill": True}`) are generated to maintain audio timeline continuity without stalling.
   - The sequence tracker advances past the gap and delivers buffered contiguous chunks.
4. **Stale Chunk Suppression**: Late chunks with `chunk_index < expected_index` are discarded cleanly (`metrics.stale_chunks_dropped += 1`).
5. **Stream Flush (`flush()`)**: Upon `AUDIO_ENDED`, delivers all remaining buffered chunks in sorted order and fills any remaining gap.

---

## 4. W5 Backend Event Stream Integration

The `BackendEventStream` provides an asynchronous broadcast bus for downstream components:

```
[TranscriptionOrchestrator]
            |
            v
  [BackendEventStream]
    |--> Dialog Manager (async consumer)
    |--> Reasoning Agent (filter: FINAL_TRANSCRIPT)
    |--> UI WebSocket Gateway (multiplexed subscriber)
```

### Key Features
- **Zero-Latency Publish**: Synchronous `publish_nowait()` and async `publish()` broadcast events to subscriber queues and consumer callbacks.
- **Asynchronous Consumption (`consume()`)**: Async generator yielding `TranscriptEvent` items with optional `filter_types` (e.g., only `FINAL_TRANSCRIPT`) and optional `replay_history`.
- **Callback Consumers**: Synchronous or async callbacks registered via `add_consumer()` / `remove_consumer()`.
- **Chronological History Snapshot**: Immutable snapshot copy of all events via `stream.history`.
- **Graceful Termination**: `close_nowait()` and `await close()` deliver terminal sentinels to all consumer queues, ensuring loops terminate cleanly without hanging.

---

## 5. Orchestrator Integration

### Orchestrator Configuration Additions
```python
class OrchestratorConfig(BaseModel):
    # ...
    enable_audio_reordering: bool = True       # Enable packet reordering
    audio_reorder_window: int = 5              # Sliding window buffer size
    fill_missing_audio_gaps: bool = True       # Synthetic silence gap fill
```

### Orchestrator Methods
- `connect_backend_stream(stream: BackendEventStream) -> None`: Connects downstream bus with strict session ID enforcement.
- `async push_audio_event(event: AudioEvent) -> None`: Ingests W1 events, auto-starts on `AUDIO_STARTED`, reorders `AUDIO_CHUNK`, and flushes on `AUDIO_ENDED`.
- Reconciled events emitted by the orchestrator are automatically published to `backend_stream`.
- Calling `stop()` or `cancel()` automatically closes the connected `backend_stream`.

### Metrics & Telemetry
- `audio_events_received`: Total W1 `AudioEvent` packets ingested.
- `audio_chunks_reordered`: Out-of-order chunks successfully sorted.
- `missing_audio_chunks_detected`: Dropped/missing chunk gaps identified and compensated.
- `stale_audio_chunks_dropped`: Late packets dropped after gap advancement.
- `backend_events_published`: Total transcript events forwarded to the backend stream.

---

## 6. Verification & Test Suite

The test suite in `tests/test_event_stream_integration.py` validates all acceptance criteria:

1. `test_audio_event_started_factory`, `test_audio_event_chunk_factory`, `test_audio_event_ended_factory`: Validates models, timestamps, and parameters.
2. `test_extra_attributes_forbidden`: Asserts strict schema enforcement (`extra="forbid"`).
3. `test_in_order_delivery`: Verifies zero delay on sequential packets.
4. `test_out_of_order_resolution_simple` & `test_complex_shuffle_reordering`: Validates sorting of scrambled arrivals.
5. `test_missing_chunk_gap_detection_with_silence_fill`: Validates gap detection and synthetic silence insertion.
6. `test_stale_chunk_dropping`: Validates discarding of late-arriving packets.
7. `test_flush_delivers_remaining_buffer`: Validates terminal buffer flushing.
8. `test_publish_and_consume`: Validates pub/sub broadcast and consumption.
9. `test_consume_with_type_filter`: Validates event type filtering.
10. `test_callback_consumer`: Validates callback invocation.
11. `test_push_audio_event_lifecycle`: End-to-end `AUDIO_STARTED` -> `AUDIO_CHUNK` -> `AUDIO_ENDED`.
12. `test_out_of_order_audio_chunks_in_orchestrator`: End-to-end out-of-order audio reordering before STT.
13. `test_missing_audio_chunks_in_orchestrator`: End-to-end missing audio gap compensation.
14. `test_backend_stream_pubsub_multiplexing`: Concurrent downstream consumers receiving identical event streams.
15. `test_audio_event_session_mismatch` & `test_session_mismatch_rejection`: Strict session ID verification.
16. `test_cancellation_propagates_to_backend_stream`: In-flight cancellation closes downstream stream.
17. `test_mock_fallback_emits_to_backend_stream`: Quota/network errors and fallback transcripts flow into backend stream.
