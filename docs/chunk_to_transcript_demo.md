# Day 7 Demo: Chunk-to-Transcript Streaming STT Pipeline

This document details the architecture, execution lifecycle, CLI options, and integration verification of the **Runnable Chunk-to-Transcript Demo Script** built for **Academia – AI Voice Co-Pilot**.

---

## 1. Architectural Overview

The Day 7 milestone demonstrates the complete, end-to-end integration of the Voice & Speech-to-Text (STT) stack developed across Week 1:
- **Day 1–2**: Strongly typed data contracts (`TranscriptSegment`, `TranscriptEvent`, `WordTiming`, `TranscriptError`).
- **Day 3–4**: Provider-neutral STT adapter contract (`BaseTranscriber`, `AudioConfig`, `TranscriberConfig`) and deterministic simulation engine (`FakeTranscriber`).
- **Day 5–6**: Ordered segment accumulator (`SegmentAccumulator`, `AccumulatedTranscript`) managing chronological bisection reordering, speculative interim hypotheses, and idempotent deduplication.
- **Day 7**: End-to-end interactive streaming pipeline converting raw acoustic chunks directly into synchronized, ordered transcripts and agent prompt contexts.

```
+──────────────────────────────────────────────────────────────────────────+
|                        CHUNKING & STREAMING FLOW                         |
+──────────────────────────────────────────────────────────────────────────+
                                                                            
   [Audio Source] Raw 16kHz PCM (100ms frames = 3,200 bytes)               
          │                                                                 
          ▼                                                                 
   ┌──────────────────────────────────────────────────────────────┐        
   │  BaseTranscriber / FakeTranscriber                           │        
   │  - Audio ingestion: push_audio(chunk)                        │        
   │  - VAD onset detection                                       │        
   │  - Speculative progressive hypothesis generation             │        
   │  - Utterance locking & WordTiming calculation                │        
   └──────────────────────────────┬───────────────────────────────┘        
                                  │ Streaming TranscriptEvents             
                                  ▼                                         
   ┌──────────────────────────────────────────────────────────────┐        
   │  SegmentAccumulator                                          │        
   │  - In-place active_interim updates                           │        
   │  - Binary search (bisect_left) chronological re-ordering     │        
   │  - Idempotent deduplication by segment.id                    │        
   │  - Speech activity boundary tracking                         │        
   └──────────────┬───────────────────────────────┬───────────────┘        
                  │                               │                         
                  ▼                               ▼                         
     Real-Time UI Projections            Downstream Agent Context          
     • get_interim_text() (Live preview) • get_final_text() (Prompt)       
     • get_full_text() (Captions)        • get_snapshot() (Turn snapshot)  
```

---

## 2. Event Lifecycle Sequence

During a speech turn, audio frames are ingested sequentially, driving the following event sequence:

| Step | Audio Offset | Transmitted Event | Payload Type | Accumulator Action |
| :--- | :--- | :--- | :--- | :--- |
| **1** | `0 ms` | `SPEECH_STARTED` | VAD Onset | Sets `speech_active = True`. |
| **2** | `100 – 900 ms` | `INTERIM_TRANSCRIPT` | `is_final=False` | Updates `active_interim` in place; updates `get_full_text()`. |
| **3** | `1000 ms` | `FINAL_TRANSCRIPT` | `is_final=True` | Commits segment to `final_segments` via bisection; clears `active_interim`. |
| **4** | `1000 ms` | `SPEECH_ENDED` | Turn Boundary | Sets `speech_active = False`. |

---

## 3. Demonstration Scenarios

The demo script (`scripts/chunk_to_transcript_demo.py` / `demo.py`) includes 4 scenarios:

### Scenario 1: Live Chunk-to-Transcript Streaming
- Streams 100ms raw PCM chunks (`3,200 bytes/chunk`) into the transcriber.
- Shows progressive interim hypotheses updating live in the UI projection box.
- Locks in the final transcript and prints a word-level timing and alignment breakdown table.
- Prints a turn analytics card with total audio duration, word count, and duration-weighted average confidence.

### Scenario 2: Multi-Turn Continuous Conversation
- Streams multiple consecutive questions across conversational turns (e.g., student asking two related academic questions).
- Verifies that `SegmentAccumulator` retains prior committed segments, computes cumulative analytics, and cleanly manages interims across turns.

### Scenario 3: Network Jitter & Deduplication Resilience
- **Out-of-Order Delivery**: Feeds segment 2 ($\text{start}=2000\text{ms}$) before segment 1 ($\text{start}=0\text{ms}$). Confirms `auto_sort` bisection ordering restores chronological sequence.
- **Duplicate Delivery**: Re-sends identical segments to simulate network reconnection retries. Confirms idempotent deduplication discards redundant packets.

### Scenario 4: Chaos Engineering (Error Injection)
- Injects a deterministic failure (`error_after_chunks=3`, `TranscriptError`) into `FakeTranscriber`.
- Confirms the error is recorded in the accumulator diagnostic history without crashing the application.

---

## 4. Running the Demo

### Quick Start (All Scenarios)
```bash
# Run via root alias
python demo.py

# Or run via scripts path
python scripts/chunk_to_transcript_demo.py
```

### Command-Line Options
| Flag | Description | Default |
| :--- | :--- | :--- |
| `--mode {all,single,multi,jitter,error}` | Select specific scenario to run | `all` |
| `--script TEXT [TEXT ...]` | Custom utterance text to transcribe | Quicksort prompt |
| `--pace SECONDS` | Artificial delay between chunks (visual animation) | `0.02s` |
| `--fast` | Zero delay (instantaneous execution for benchmarks) | `False` |
| `--realtime` | 1.0x natural speech pacing (100ms per 100ms chunk) | `False` |
| `--chunk-ms MS` | Duration of each audio chunk in ms | `100` |
| `--export-json PATH` | Export `AccumulatedTranscript` snapshot to JSON | `None` |
| `--no-color` | Disable ANSI color codes (for clean log pipes) | `False` |

### Examples
```bash
# Instant single-turn run with custom text
python demo.py --mode single --fast --script "How does Dijkstra's algorithm work?"

# Run with natural speech pacing (real-time playback cadence)
python demo.py --mode single --realtime

# Export final transcript snapshot to JSON
python demo.py --mode all --fast --export-json transcript_snapshot.json
```
