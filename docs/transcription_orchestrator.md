# Transcription Orchestrator (Days 8–9 Milestone)

The **Transcription Orchestrator** is the central coordinating engine of the **Voice & Speech-to-Text (STT)** pipeline for Week 2. It connects continuous raw audio chunk ingestion to STT provider adapters, coordinates asynchronous event dispatching, and aggregates transcripts in real time.

---

## 1. Architecture & Core Responsibilities

```
                   [ Incoming Audio Chunks ]
                               │
                               ▼ (push_audio)
              ┌─────────────────────────────────┐
              │    TranscriptionOrchestrator    │
              │                                 │
              │   ┌──────────────────────────┐  │
              │   │   Async Audio Queue      │  │
              │   │   (Buffer & Backpressure)│  │
              │   └────────────┬─────────────┘  │
              │                │                │
              │                ▼                │
              │   ┌──────────────────────────┐  │
              │   │   Provider Adapter       │  │
              │   │   (e.g. FakeTranscriber) │  │
              │   └────────────┬─────────────┘  │
              │                │                │
              │                ▼ (Event Feed)   │
              │   ┌──────────────────────────┐  │
              │   │   Segment Accumulator    │  │
              │   │   - Ordering & Interims  │  │
              │   │   - Projections & State  │  │
              │   └────────────┬─────────────┘  │
              └────────────────┼────────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
 [ Async Iterator stream() ]          [ Callback Listeners ]
 (For UI / Streaming Clients)         (For Downstream LLM Agents)
```

### Key Capabilities
1. **Streaming Audio Ingestion**: Safely validates, timestamps, and queues incoming audio frames (`16kHz`, `mono`, `16-bit PCM`).
2. **Provider Lifecycle Coordination**: Automatically initializes, transitions, and shuts down STT provider adapters without leaking resources.
3. **Deterministic Mock Mode**: Pairs natively with `FakeTranscriber` by default—requiring zero external network requests or vendor API credentials.
4. **Zero-Latency Event Dispatch**: Broadcasters push events immediately to both asynchronous streams (`async for event in orchestrator.stream()`) and registered callbacks (`add_event_listener`).
5. **Real-Time Transcript Projections**: Exposes locked final text (`get_final_text()`), speculative hypotheses (`get_interim_text()`), and immutable snapshots (`get_snapshot()`).
6. **Telemetry & Metrics**: Tracks cumulative bytes, audio duration, chunks ingested, turns detected, and event counters (`OrchestratorMetrics`).

---

## 2. Lifecycle State Machine

The orchestrator enforces strict state transitions (`OrchestratorState`):

```
 [IDLE] ───► [STARTING] ───► [RUNNING] ───► [STOPPING] ───► [STOPPED]
   │                             │
   └───────────────┬─────────────┘
                   ▼
                [ERROR]
```

- **`IDLE`**: Initial state after instantiation.
- **`STARTING`**: Adapter is being initialized and background workers are launched.
- **`RUNNING`**: Ready to receive audio via `push_audio()` and emit events.
- **`STOPPING`**: Ingestion halted, remaining frames flushed, and provider concluding.
- **`STOPPED`**: Terminal healthy state; all queues closed with `None` sentinels.
- **`ERROR`**: Error state reached if startup or worker tasks fail.

---

## 3. Quick Start Example

```python
import asyncio
from src.voice import OrchestratorConfig, TranscriptionOrchestrator

async def main():
    script = "What is the worst case time complexity of quicksort?"
    
    # Instantiate orchestrator in mock mode
    async with TranscriptionOrchestrator(
        session_id="lecture-01",
        script=script,
    ) as orch:
        # Simulate pushing 10 audio chunks (100ms each = 3,200 bytes)
        chunk = b"\x00" * 3200
        for _ in range(10):
            await orch.push_audio(chunk)
            
        # Signal audio stream conclusion
        await orch.finish_audio()
        
        # Access downstream projections
        print("Committed Text:", orch.get_final_text())
        print("Interim Text:  ", orch.get_interim_text())
        print("Telemetry:     ", orch.metrics.model_dump())

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 4. Streaming Subscription Example

```python
async def stream_live_events(orch: TranscriptionOrchestrator):
    async for event in orch.stream():
        if event.event_type == "interim_transcript":
            print(f"Speculative UI: {event.segment.text}")
        elif event.event_type == "final_transcript":
            print(f"Locked LLM: {event.segment.text}")
```

---

## 5. Verification & Tests

The Days 8–9 milestone is validated by 16 tests in `tests/test_orchestrator.py`:
- `TestOrchestratorInitialization`: Validates session ID constraints and adapter binding.
- `TestOrchestratorLifecycle`: Verifies state transitions and context manager entry/exit.
- `TestAudioIngestionValidation`: Verifies chunk types, lengths, auto-start, and stopped states.
- `TestEndToEndMockFlow`: Verifies full end-to-end chunk ingestion to transcript event stream.
- `TestProjectionsAndBatchProcessing`: Tests live snapshot projections and batch processing helper.

Run tests:
```bash
python -m pytest tests/test_orchestrator.py -v
```

