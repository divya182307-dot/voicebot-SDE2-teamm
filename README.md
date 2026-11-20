# voicebot-week1-teamm
AI Voice Co-Pilot - Team Project

---

# Academia – AI Voice Co-Pilot: Voice & Speech-to-Text (STT) Module

This module forms the speech recognition foundation of **Academia – AI Voice Co-Pilot**, responsible for audio stream ingestion, transcription event streaming, segment aggregation, provider-neutral adapter abstractions, and deterministic test double simulation.

---

## 📁 Repository Structure

```
Voicebot/
├── demo.py                         # Top-level quick launcher for Day 7 streaming demo
├── docs/
│   ├── schemas.md                  # Comprehensive field, unit, and validation documentation
│   ├── transcriber_adapter.md      # Adapter contract and deterministic fake transcriber docs
│   ├── segment_accumulator.md      # Ordered segment accumulator and fixture engine docs
│   ├── chunk_to_transcript_demo.md # Day 7 end-to-end streaming demo documentation
│   ├── session_revisions_and_confidence.md # Day 15-16 session isolation, revisions, & confidence
│   ├── cancellation_and_mock_fallback.md   # Day 17-18 in-flight cancellation & mock fallback
│   ├── audio_events_and_backend_stream.md  # Day 19-20 W1 audio events & W5 backend event stream
│   └── week3_integration_evidence.md       # Day 21 integration evidence & team gate verification
├── schemas/                        # Exported JSON Schemas for Frontend & Backend interoperability
│   ├── transcript_segment.json
│   ├── transcript_event.json
│   ├── transcript_error.json
│   ├── word_timing.json
│   ├── audio_config.json
│   ├── transcriber_config.json
│   ├── fake_utterance.json
│   ├── accumulator_config.json
│   └── accumulated_transcript.json
├── scripts/
│   ├── chunk_to_transcript_demo.py # Day 7 runnable chunk-to-transcript streaming demo
│   ├── demo_chunk_to_transcript.py # Convenience alias script
│   ├── export_json_schemas.py      # Utility to generate/refresh JSON schemas
│   ├── week2_synthetic_demo.py     # Week 2 synthetic audio fixture streaming demo
│   └── week3_integration_demo.py   # Week 3 end-to-end integration demo (Day 21)
├── src/
│   └── voice/
│       ├── __init__.py             # Public API exports
│       ├── accumulator.py          # Ordered SegmentAccumulator and AccumulatedTranscript
│       ├── adapter.py              # Provider-neutral BaseTranscriber interface & AudioConfig
│       ├── event_stream.py         # W1 AudioEvents, AudioStreamReorderer & W5 BackendEventStream
│       ├── exceptions.py           # Domain exception classes
│       ├── fake_transcriber.py     # Deterministic FakeTranscriber implementation
│       ├── fixtures.py             # Canonical transcript event fixtures and stream generators
│       ├── orchestrator.py         # TranscriptionOrchestrator pipeline coordinator
│       ├── preprocessing.py        # Audio resampler, stereo-to-mono downmixer, & normalizer
│       ├── reconciliation.py       # TranscriptReconciler ordering, deduplication, & revisions
│       ├── resilience.py           # Bounded retries, timeouts, and ErrorNormalizer
│       └── schemas.py              # Pydantic v2 TranscriptSegment & TranscriptEvent data models
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Pytest fixture bindings
│   ├── test_accumulator.py         # 25 unit tests for ordering, interims, deduplication, and fixtures
│   ├── test_adapter.py             # 16 unit tests for adapter contract and audio specs
│   ├── test_cancellation_and_fallback.py # 11 tests for in-flight cancellation & mock fallback
│   ├── test_contract.py            # 14 tests for provider adapter contract invariants
│   ├── test_demo.py                # 10 integration and unit tests for Day 7 streaming demo
│   ├── test_event_stream_integration.py # 21 tests for audio events, reorderer, & backend stream
│   ├── test_fake_transcriber.py    # 17 unit tests verifying 100% deterministic reproducibility
│   ├── test_orchestrator.py        # 16 unit tests for transcription orchestrator
│   ├── test_preprocessing.py       # 13 tests for audio resampling and normalization
│   ├── test_reconciliation.py      # 14 tests for stream ordering and deduplication
│   ├── test_resilience.py          # 17 tests for retries, timeouts, and error normalization
│   ├── test_schemas.py             # 26 unit tests covering schema constraints and edge cases
│   ├── test_session_and_revisions.py # 14 tests for sessions, revisions, and confidence thresholds
│   └── test_week3_integration.py   # 7 tests for Day 21 integration gate & demo stages
└── pyproject.toml                  # Packaging and pytest configuration
```

---

## 🚀 Deliverables Summary (Week 1 Complete)

### 📅 Day 1–2: Data Contracts & Schemas
1. **Schemas Defined (`src/voice/schemas.py`)**:
   - `TranscriptSegment`: Atomic speech unit with timing (ms), text, confidence, finality, language tag, and word timings.
   - `TranscriptEvent`: Streaming event packet supporting lifecycle phases (`speech_started`, `interim_transcript`, `final_transcript`, `speech_ended`, `error`).
   - `WordTiming`: Word-level breakdown for synchronized UI captioning.
   - `TranscriptError`: Standardized error diagnostic object.
2. **Validation & Invariants Enforced**:
   - `start_time_ms >= 0` and `end_time_ms >= start_time_ms`.
   - `0.0 <= confidence <= 1.0`.
   - BCP-47 / ISO language code validation (`en`, `en-US`, `es-419`, etc.).
   - Rejection of blank/whitespace text.
   - Strict event consistency: `final_transcript` requires `is_final=True`, `interim_transcript` requires `is_final=False`, and `error` requires `error` payload.
   - `extra="forbid"` to prevent unauthorized schema drift across subteams.
3. **Automated Unit Tests**: 26 tests in `tests/test_schemas.py`.

---

### 📅 Day 3–4: Provider-Neutral Adapter & Deterministic Fake Transcriber
1. **Provider-Neutral Adapter Interface (`src/voice/adapter.py`)**:
   - `BaseTranscriber` abstract base class defining vendor-agnostic contracts (for Deepgram, Whisper, Google Cloud Speech, Azure Speech, etc.).
   - `TranscriberState` lifecycle state machine (`IDLE` $\rightarrow$ `STARTING` $\rightarrow$ `LISTENING` $\rightarrow$ `STOPPING` $\rightarrow$ `STOPPED` / `ERROR`).
   - `AudioConfig` and `TranscriberConfig` for sample rates, channels, codecs (`PCM_S16LE`, `PCM_F32LE`, `OPUS`, `MULAW`), and chunk durations.
   - Dual-consumption model: Asynchronous streaming generators (`async for event in transcriber.stream()`) and callback listeners (`add_event_listener`).
   - Batch (`transcribe_audio`) and stream piping (`transcribe_stream`) utilities.
   - Asynchronous context manager support (`async with transcriber:`).

2. **Deterministic Fake Transcriber (`src/voice/fake_transcriber.py`)**:
   - **Deterministic Guarantee**: Same inputs (audio bytes, script, seed) $\rightarrow$ 100% identical output events, sequence numbers, timestamps, segment IDs, and JSON payloads.
   - **Deterministic UUID5 Identifiers**: Reproducible `event_id` and segment `id` derived cryptographically using fixed namespace and event metadata.
   - **Reproducible Timestamps**: Fixed reference epoch (`2026-01-01T12:00:00Z` or user-defined) + elapsed audio offset in milliseconds.
   - **Streaming Lifecycle**: Emits `SPEECH_STARTED` $\rightarrow$ progressive `INTERIM_TRANSCRIPT` $\rightarrow$ `FINAL_TRANSCRIPT` (with `WordTiming`s) $\rightarrow$ `SPEECH_ENDED`.
   - **Audio-Driven Fallback**: Cryptographic SHA-256 fingerprinting selects deterministic utterances from an academic speech corpus when no explicit script is supplied.
   - **Deterministic Error Injection**: Configurable `error_after_chunks` and custom `TranscriptError` simulation for chaos and resilience testing.

---

### 📅 Day 5–6: Ordered Segment Accumulator & Fixture Engine
1. **Ordered Segment Accumulator (`src/voice/accumulator.py`)**:
   - `SegmentAccumulator`: Stateful aggregator managing in-flight speculative interim hypotheses and committed final utterances.
   - **Strict Chronological Ordering**: Auto-sorts segments via bisection search on `start_time_ms`, correctly resolving out-of-order network arrival.
   - **Interim vs. Final Handling**: In-place replacement of interim hypotheses; automatic interim clearing on final utterance arrival or `SPEECH_ENDED`.
   - **Idempotent Deduplication**: Rejects or ignores duplicate segment IDs based on `AccumulatorConfig`.
   - **Projections for Subteams**:
     - `get_final_text()`: Locked text for LLM Agent prompt context.
     - `get_interim_text()`: Active speculative text for UI preview styling.
     - `get_full_text()`: Combined real-time transcript for live captions.
   - **Turn Analytics & Snapshot**: `total_duration_ms`, `average_confidence` (duration-weighted), `word_count`, `all_words`, and frozen `AccumulatedTranscript` snapshot.

2. **Standardized Fixtures (`src/voice/fixtures.py` & `tests/conftest.py`)**:
   - `single_utterance_events`: Canonical single turn with progressive interims and word timings.
   - `multi_utterance_events`: Multi-turn conversational questions with word breakdowns.
   - `out_of_order_final_events`: Inverted segment deliveries to test chronological sorting.
   - `duplicate_final_events`: Identical final segments to verify deduplication idempotency.
   - `error_event_stream`: Failure simulation with structured `TranscriptError`.

3. **Automated Unit Tests**:
   - `tests/test_accumulator.py`: 25 tests covering sorting, interim lifecycle, deduplication, invalid inputs, snapshots, and fixtures.

---

### 📅 Day 7: Runnable Chunk-to-Transcript Demo Script
1. **Interactive Demo Pipeline (`scripts/chunk_to_transcript_demo.py` & `demo.py`)**:
   - **Audio Ingestion**: Streams 100ms raw PCM audio frames (`16kHz`, `mono`, `16-bit`, `3,200 bytes/chunk`) directly into `FakeTranscriber`.
   - **Streaming Event Engine**: Emits `SPEECH_STARTED` $\rightarrow$ progressive speculative `INTERIM_TRANSCRIPT` hypotheses $\rightarrow$ locked `FINAL_TRANSCRIPT` (with `WordTiming`s) $\rightarrow$ `SPEECH_ENDED`.
   - **Live UI Projections**: Continuously renders active interim text for UI live captions and committed final text for downstream LLM prompts.
   - **Multi-Scenario Showcase**:
     - *Scenario 1 (Single Turn Streaming)*: Chunk-by-chunk ingestion with progressive interims and word alignment breakdown table.
     - *Scenario 2 (Multi-Turn Conversation)*: Consecutive turns demonstrating cumulative multi-turn transcript history.
     - *Scenario 3 (Jitter & Deduplication)*: Out-of-order bisection sorting and duplicate delivery filtering.
     - *Scenario 4 (Chaos Injection)*: Graceful capture of injected `TranscriptError` in diagnostic history.
   - **Snapshot Export**: Serializes immutable `AccumulatedTranscript` to JSON (`--export-json`).

2. **Automated Unit & Integration Tests**:
   - `tests/test_demo.py`: 10 tests covering audio synthesis, scenario execution, and CLI invocation.

---

### 📅 Day 8–9: Speech-to-Text Transcription Orchestration (Week 2 Milestone)
1. **Transcription Orchestrator (`src/voice/orchestrator.py`)**:
   - Central coordinator connecting audio chunk streams to provider adapters and transcript event subscribers.
   - **Asynchronous Audio Ingestion**: Manages an async chunk queue with configurable backpressure buffering.
   - **Adapter Lifecycle Coordination**: Manages adapter state transitions (`IDLE` → `STARTING` → `RUNNING` → `STOPPING` → `STOPPED`).
   - **Dual Dispatch Model**: Supports both asynchronous streaming iterators (`async for event in orchestrator.stream()`) and callback listeners (`add_event_listener`).
   - **Segment Accumulator Integration**: Automatically feeds transcript events into `SegmentAccumulator` to provide real-time downstream projections (`get_final_text()`, `get_interim_text()`, `get_snapshot()`).
   - **Session Telemetry**: Tracks chunks ingested, total bytes, audio duration, speech turns detected, and event counters (`OrchestratorMetrics`).
   - **Zero-Configuration Mock Mode**: Pairs natively with `FakeTranscriber` by default—requiring zero API keys or network requests.
2. **Automated Unit & Integration Tests**:
   - `tests/test_orchestrator.py`: 16 comprehensive tests covering initialization, auto-start, validation, streaming, callbacks, and telemetry.

---

### 📅 Day 10–11: Ordering, Duplicate Suppression & Interim/Final Reconciliation (Week 2 Milestone)
1. **Reconciliation Engine (`src/voice/reconciliation.py`)**:
   - **Strict Chronological Ordering**: Multi-key bisection sorting (`start_time_ms`, `end_time_ms`, `id`) ensuring out-of-order segment arrivals are reordered into natural speech order.
   - **Multi-Layer Deduplication**: Filters duplicate `event_id`s, duplicate segment `id`s, temporal/content duplicates, and repeated consecutive interim hypotheses.
   - **Interim/Final Reconciliation**:
     - Drops stale speculative interims that fall behind committed final segment boundaries.
     - Trims overlapping interim boundaries against committed speech.
     - Automatically clears or updates interim hypotheses when final segments lock.
     - Supports optional turn-boundary interim promotion (`promote_interim_on_speech_ended`).
   - **Integrated Orchestration**: Fully wired into `TranscriptionOrchestrator` to guarantee clean, non-duplicate, ordered events across `orchestrator.stream()`.
   - **Telemetry Tracking**: Tracks `duplicates_suppressed`, `out_of_order_resolved`, `stale_interims_count`, and `repeated_interims_count`.
2. **Automated Unit & Integration Tests**:
   - `tests/test_reconciliation.py`: 14 comprehensive unit tests verifying ordering, multi-layer deduplication, interim trimming, and orchestrator stream filtering.

---

### 📅 Day 12–13: Resilience, Bounded Retries, Error Normalization & Audio Preprocessing (Week 2 Milestone)
1. **Audio Preprocessing Pipeline (`src/voice/preprocessing.py`)**:
   - **Pure-Python Resampling (`resample_pcm16`)**: High-precision linear interpolation converting arbitrary sample rates (8kHz, 22.05kHz, 44.1kHz, 48kHz) to standard 16kHz speech recognition rates (PEP 594 compliant, no deprecated `audioop`).
   - **Amplitude Normalization (`normalize_amplitude_pcm16`)**: Peak dBFS scaling (e.g. -1.0 dBFS) and RMS loudness energy normalization with DC offset removal and range clamping.
   - **Channel Downmixing (`convert_stereo_to_mono`)**: Fast downmixing from 2-channel stereo to 1-channel mono via channel sample averaging.
   - **Modular `AudioPreprocessor`**: Processes streaming frames or batch buffers with comprehensive telemetry (`chunks_processed`, `bytes_in`, `bytes_out`, `chunks_resampled`, `chunks_normalized`).
2. **Resilience & Fault Tolerance Layer (`src/voice/resilience.py`)**:
   - **Bounded Exponential Backoff (`RetryPolicy`)**: Bounded retries (default 3) with configurable initial delay, backoff multiplier, and full randomization jitter.
   - **Transient vs Non-Retryable Error Classification**: Retries connection drops, socket resets, 429 rate limits, and 503 service outages, while immediately failing on auth/format errors.
   - **Timeouts (`TimeoutPolicy`)**: Enforces deadlines on connection, chunk pushing, and full operations, converting violations to typed `TranscriberTimeoutError` exceptions.
   - **Strict Error Normalization (`ErrorNormalizer`)**: Maps all raw network, vendor, HTTP, and socket exceptions into typed `TranscriberError` exceptions and canonical `TranscriptEvent(ERROR)` events—guaranteeing that raw vendor exceptions never leak upstream.
   - **`ResilientTranscriberWrapper`**: Adapter decorator wrapping any transcriber with automatic timeout, retry, and error normalization protection.
   - **Seamless Orchestrator Integration**: Preprocesses incoming audio and shields streaming execution in `TranscriptionOrchestrator`.
3. **Automated Unit & Integration Tests**:
   - `tests/test_preprocessing.py`: 13 tests covering resampling, stereo downmixing, peak/RMS normalization, and DC centering.
   - `tests/test_resilience.py`: 17 tests covering bounded retries, timeouts, error normalization, and wrapper integration.

---

### 📅 Day 14: Contract Test Suite & End-to-End Synthetic Fixture Demo
1. **Contract Test Suite (`tests/test_contract.py`)**:
   - Comprehensive provider-adapter contract test suite guaranteeing zero-credential offline operation, state machine invariants, monotonic sequence numbers, non-decreasing timestamps, dual-dispatch parity, and bounded retries.
2. **Synthetic Fixture Demo (`scripts/week2_synthetic_demo.py`)**:
   - Prerecorded synthetic 48kHz stereo fixture downmixed and resampled through the orchestrator to test the complete end-to-end pipeline without real audio hardware or vendor API keys.

---

### 📅 Day 15–16: Session Association, Revisions, Finalization & Confidence Thresholds (Week 3 Milestone)
1. **Session Association (`enforce_session_id`)**:
   - Every transcript event strictly carries and validates `session_id`.
   - Ingestion guards across `TranscriptionOrchestrator`, `TranscriptReconciler`, and `SegmentAccumulator` reject mismatched or empty session IDs with `SessionMismatchError`.
   - Multi-session isolation prevents cross-pollination of state across sessions.
2. **Hypothesis Revisions & Finalization Events**:
   - Speculative interim hypotheses are tracked with sequential revision counters (`revision=1, 2, ...`, `is_revision=True`, `revision_type="interim_revision"`).
   - Finalization events (`FINAL_TRANSCRIPT`) carry finalization metadata (`is_finalization=True`, `total_revisions_for_segment`) and reset revision counters upon utterance conclusion.
   - Speech turn boundary reset clears active interim state cleanly.
3. **Configurable Confidence Thresholds**:
   - `confidence_threshold`: Minimum confidence threshold in `[0.0, 1.0]`.
   - `low_confidence_action`: Configurable policy for low-confidence segments:
     - `"tag"`: Injects metadata (`is_low_confidence=True`, `confidence`, `confidence_threshold`) into the event payload.
     - `"filter"`: Drops low-confidence segments from downstream history and committed transcripts.
     - `"ignore"`: Permits low-confidence segments without metadata modification.
   - `SegmentAccumulator` tracks `low_confidence_segments` and exposes them via snapshots and property queries.
4. **Automated Unit & Integration Tests**:
   - `tests/test_session_and_revisions.py`: 14 comprehensive tests covering session enforcement, revision tracking, finalization metadata, confidence tag/filter policies, and orchestrator end-to-end workflows.

---

### 📅 Day 17–18: In-Flight Cancellation & Automatic Mock Provider Fallback (Week 3 Milestone)
1. **In-Flight Cancellation (`orchestrator.cancel()`)**:
   - Clean lifecycle transition to `CANCELLED` state without deadlocks or unhandled exceptions.
   - Discards pending unread audio chunks from the ingestion queue immediately.
   - Cancels background audio workers and stops provider adapters gracefully.
   - Pushes stream sentinels to consumer queues, allowing `async for event in orch.stream():` loops to conclude cleanly.
   - Safe and idempotent: calling `cancel()` multiple times leaves state intact.
2. **Automatic Mock Provider Fallback (`FakeTranscriber`)**:
   - Seamless dynamic failover when primary STT providers hit quota limits (HTTP 429 / quota exhaustion) or network failures (connection drops, timeouts, socket resets).
   - Normalizes the underlying failure through `ErrorNormalizer` so raw vendor exceptions never leak upstream.
   - Emits a normalized `TranscriptEvent(ERROR)` downstream flagging the fallback event (`fallback_triggered=True`).
   - Automatically switches adapter to `FakeTranscriber` and replays the failed chunk, allowing the session to continue uninterrupted.
   - Telemetry tracks `fallbacks_triggered` and `is_fallback_active`.
   - Also integrated into `ResilientTranscriberWrapper` for component-level protection.
3. **Automated Unit & Chaos Tests**:
   - `tests/test_cancellation_and_fallback.py`: 11 tests covering in-flight cancellation, queue draining, subscriber exit, quota 429 fallback, network drop fallback, timeout fallback, disabled-fallback error escalation, and wrapper fallback.

---

### 📅 Day 19–20: W1 Audio Events & W5 Backend Event Stream Integration (Week 3 Milestone)
1. **W1 Audio Event Models & Lifecycle (`src/voice/event_stream.py`)**:
   - `AudioEvent` canonical data model carrying `session_id`, 0-based `chunk_index`, PCM audio payload, timestamps, sample rates, and terminal chunk indicators.
   - Lifecycle factory constructors (`started()`, `chunk()`, `ended()`) guaranteeing compatibility with upstream Week 1 audio capture.
   - Integrated into `TranscriptionOrchestrator.push_audio_event()` with auto-start and session isolation.
2. **AudioStreamReorderer (Out-of-Order & Missing Chunk Resilience)**:
   - Sliding-window sequencing buffer that re-sequences out-of-order audio packets chronologically before transcription.
   - Detects sequence gaps caused by dropped/delayed packets.
   - Generates zero-padded synthetic silence packets (`synthetic_fill=True`) to maintain STT audio timeline continuity without stalling.
   - Suppresses stale late-arriving packets whose gap has already been advanced.
   - Flushes remaining buffered audio in sequence upon utterance conclusion (`AUDIO_ENDED`).
3. **W5 Backend Event Stream (`BackendEventStream`)**:
   - High-throughput asynchronous pub/sub event distribution bus bridging the orchestrator to downstream W5 consumers (dialog manager, reasoning agent, workflow policy, UI gateways).
   - Asynchronous streaming consumer (`async for event in stream.consume():`) with optional event type filtering and history replay.
   - Synchronous and asynchronous callback listeners (`add_consumer()`).
   - Integrated lifecycle: closing or cancelling the orchestrator automatically and cleanly concludes connected backend streams.
4. **Automated Unit & End-to-End Integration Tests**:
   - `tests/test_event_stream_integration.py`: 21 comprehensive tests covering AudioEvent models, reorderer resolution, missing chunk gap fill, stale suppression, backend pub/sub multiplexing, session enforcement, cancellation propagation, and mock fallback.

---

### 📅 Day 21: Integration Evidence, Pull Request & End-to-End Demo (Week 3 Culmination)
1. **Week 3 End-to-End Integration Demo (`scripts/week3_integration_demo.py`)**:
   - 5-stage interactive demonstration exercising all Week 3 requirements:
     - **Stage 1 (W1 Audio Ingestion & Resilient Reordering)**: Out-of-order chunk sorting and missing packet gap detection with synthetic silence filling.
     - **Stage 2 (Session-Aware Transcription & Hypothesis Revisions)**: Strict session association (`session_id`), progressive interim revisions (`revision=1, 2...`), confidence threshold tagging (`confidence_threshold=0.80`), and finalization.
     - **Stage 3 (W5 Backend Event Stream & Pub/Sub Multiplexing)**: Real-time broadcast to `BackendEventStream` with concurrent downstream consumers (Dialog Manager, Reasoning Agent, UI WebSocket).
     - **Stage 4 (In-Flight Cancellation / Barge-In)**: Clean cancellation on user barge-in without hanging or memory leaks.
     - **Stage 5 (Quota / Network Failure & Automatic Mock Fallback)**: Demonstrates quota exhaustion (HTTP 429) automatically falling back to `FakeTranscriber` with zero leaked raw exceptions.
   - Unified top-level launcher support via `python demo.py [--week3] [--fast]`.
2. **Integration Evidence & Team Gate Documentation (`docs/week3_integration_evidence.md`)**:
   - Comprehensive evidence matrix confirming all Day 21 acceptance criteria and pipeline contracts.
   - Architectural flowcharts, telemetry breakdowns, and PR submission details.
3. **Automated Unit & Integration Tests**:
   - `tests/test_week3_integration.py`: 7 tests covering stage execution, JSON evidence snapshots, and team gate invariants.
   - **Complete Test Suite**: **221 passing unit tests** across 14 test modules (100% offline, 0 external API keys required).

---

## 🎬 Running the Demos

### Week 3 End-to-End Integration Demo (Day 21):
```bash
# Top-level quick launcher (all 5 stages)
python demo.py

# Instant benchmark execution
python demo.py --fast

# Export final snapshot to JSON
python demo.py --fast --export-json week3_snapshot.json
```

### Week 2 Synthetic Fixture Demo (Day 14):
```bash
python demo.py --week2
```

### Week 1 Chunk-to-Transcript Streaming Demo (Day 7):
```bash
python demo.py --week1
python demo.py --week1 --mode single --script "What is quicksort?" --pace 0.03
```

---

## 🧪 Running the Tests

To run the complete automated test suite (221 tests):
```bash
python -m pytest -v
```

To re-export JSON Schemas for team consumption:
```bash
python -m scripts.export_json_schemas
```

---

## 💡 Quick Start Example

```python
import asyncio
from src.voice import FakeTranscriber, SegmentAccumulator

async def main():
    accumulator = SegmentAccumulator(session_id="lecture-01")

    # Connect accumulator to transcriber stream
    async with FakeTranscriber(session_id="lecture-01", script="What is quicksort?") as stt:
        chunk = b"\x00" * 3200
        for _ in range(5):
            await stt.push_audio(chunk)
        await stt.finish_audio()

        for event in stt.events_history:
            accumulator.add_event(event)

    print("Committed Text:", accumulator.get_final_text())
    print("Total Word Count:", accumulator.word_count)
    print("Mean Confidence:", accumulator.average_confidence)
    print("Snapshot:", accumulator.get_snapshot().model_dump_json(indent=2))

if __name__ == "__main__":
    asyncio.run(main())
```
