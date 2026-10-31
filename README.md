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
│   └── chunk_to_transcript_demo.md # Day 7 end-to-end streaming demo documentation
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
│   └── export_json_schemas.py      # Utility to generate/refresh JSON schemas
├── src/
│   └── voice/
│       ├── __init__.py             # Public API exports
│       ├── accumulator.py          # Ordered SegmentAccumulator and AccumulatedTranscript
│       ├── adapter.py              # Provider-neutral BaseTranscriber interface & AudioConfig
│       ├── exceptions.py           # Domain exception classes
│       ├── fake_transcriber.py     # Deterministic FakeTranscriber implementation
│       ├── fixtures.py             # Canonical transcript event fixtures and stream generators
│       └── schemas.py              # Pydantic v2 TranscriptSegment & TranscriptEvent data models
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Pytest fixture bindings
│   ├── test_accumulator.py         # 25 unit tests for ordering, interims, deduplication, and fixtures
│   ├── test_adapter.py             # 16 unit tests for adapter contract and audio specs
│   ├── test_demo.py                # 10 integration and unit tests for Day 7 streaming demo
│   ├── test_fake_transcriber.py    # 17 unit tests verifying 100% deterministic reproducibility
│   └── test_schemas.py             # 26 unit tests covering schema constraints and edge cases
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
   - **Complete Test Suite**: **94 passing unit tests** across 5 test modules.

---

## 🎬 Running the Day 7 Demo

Run the end-to-end streaming demo via any of the convenient launchers:

```bash
# Top-level quick launcher (all scenarios)
python demo.py

# Or via scripts path
python scripts/chunk_to_transcript_demo.py

# Run single turn with custom text and visual pacing
python demo.py --mode single --script "What is quicksort?" --pace 0.03

# Run with natural 1.0x real-time speech pacing
python demo.py --mode single --realtime

# Instant execution (benchmarking)
python demo.py --fast

# Export final transcript snapshot to JSON
python demo.py --export-json snapshot.json
```

---

## 🧪 Running the Tests

To run the complete automated test suite (94 tests):
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
