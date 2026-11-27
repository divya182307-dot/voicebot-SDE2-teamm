# SDE-2 Voicebot - Audio, VAD & STT Engine (Weeks 1, 2, 3 & 4)

**Academia - AI Voice Co-Pilot**  
**Track:** SDE-2 Voicebot (`projects/sde-2-voicebot/`)  
**Phase:** Week 1 Foundation, Week 2 Audio Lifecycle & VAD, Week 3 Workflow & Integration, Week 4 Hardening & Release Gate  
**Workstream:** W1: Audio and Voice Activity  
**Owner:** Siri G R  

---

## Clean-Clone Setup & Quick Start

To verify this repository from a fresh clone:

```powershell
# 1. Clone the repository
git clone <repo-url>
cd acd_voicebot

# 2. (Optional) Create and activate a Python virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Install test dependencies
pip install pytest pytest-asyncio

# 4. Set PYTHONPATH to include the project package source and repository root
$env:PYTHONPATH = "projects/sde-2-voicebot/src;."

# 5. Run the complete test suite (246 tests, 100% passing)
python -m pytest projects/sde-2-voicebot/tests/ -v
```

All audio streaming, VAD, normalization, and STT bridge components run **100% deterministically in-memory** with synthetic waveforms (PRD Section 19 compliance). No physical microphones, sound cards, or paid external APIs are required.

---

## Week 1 Deliverables (Days 1–7: Foundation & Audio Streaming)

### 1. Audio Schemas & Validation Suite (Days 1 & 2)
- **Module:** `voicebot.schemas`
- **Classes:** `AudioFormat`, `AudioChunk`, `AudioError`
- **Specification Enforcement:**
  - **`AudioFormat`:** Immutable (`frozen=True`) configuration holding `sample_rate` (Hz, $> 0$), `channels` (1=mono, 2=stereo), and `sample_width` (1, 2, 3, or 4 bytes). Computed properties include `bytes_per_frame` and `bytes_per_second`.
  - **`AudioChunk`:** Immutable dataclass encapsulating streaming audio chunks with monotonic `sequence_id`, non-negative and finite `timestamp` (seconds), `audio_format`, and raw PCM `data` bytes.
  - **Frame Alignment Guarantee:** Enforces that audio chunk byte length is an exact multiple of the frame size (`len(data) % bytes_per_frame == 0`).
  - **`AudioError`:** Custom domain exception subclassing `ValueError` providing descriptive, actionable validation messages.
- **Documentation:** Full field documentation specifying types, units, and constraints for all schema attributes.

---

### 2. Deterministic Mock Audio Source (Days 3 & 4)
- **Module:** `voicebot.mock_microphone`
- **Class:** `MockMicrophone`
- **Consistency Guarantee:** Generates 100% reproducible, deterministic `AudioChunk` streams without requiring physical hardware or paid cloud APIs (Mock mode by default).
- **Interface Support:**
  - Standard speech sampling configuration (default: 16,000 Hz, 1 channel mono, 16-bit PCM).
  - Backward-compatible positional constructor: `MockMicrophone(16000, 1, 5, 4)`.
  - Pre-recorded PCM streaming capability via optional `raw_data` parameter.

---

### 3. Deterministic Audio Chunker (Days 3 & 4)
- **Module:** `voicebot.chunker`
- **Classes / Functions:** `AudioChunker`, `chunk_audio`
- **Features:**
  - **Deterministic Slicing:** Same raw audio input + format $\rightarrow$ identical sequence of `AudioChunk` objects on every execution.
  - **Timestamp Accuracy:** Computes elapsed time as `start_timestamp + (frames_emitted / sample_rate)`, completely avoiding cumulative floating-point rounding drift.
  - **Monotonic Sequence IDs:** Emits contiguous sequence numbers (`0, 1, 2, ...`).
  - **Dual Mode:** Slices fixed byte buffers (`chunk_bytes`) or arbitrary incoming byte streams (`chunk_stream`).
  - **Partial Tail Handling:** Gracefully emits or buffers trailing complete frames when the stream ends.
  - **Upfront Validation:** Parameter validation runs immediately, preventing empty streams from bypassing checks.

---

### 4. CLI Audio Streaming Demonstration (Days 5 & 6)
- **Module:** `voicebot.cli`
- **Features:**
  - Streams audio chunks in real-time or batch mode.
  - Formats and displays metadata per chunk: Sequence ID, Timestamp, Format (Hz, ch, bit depth), Frame count, and Byte size.
  - Displays a summary footer with total chunks, frames, bytes, and duration.
  - Fully configurable via command-line flags (`--sample-rate`, `--channels`, `--chunk-count`, `--frames-per-chunk`, `--realtime`).

---

## Week 2 Deliverables (Days 8–14: Lifecycle, VAD & Bounded Buffer)

### 5. Audio Device Adapter & Permissions (Days 8 & 9)
- **Module:** `voicebot.device`
- **Classes / Enums:** `PermissionState`, `AudioDevice`, `AudioDeviceAdapter`, `MockAudioDeviceAdapter`
- **Features:**
  - Standardized device permissions: `PROMPT`, `GRANTED`, `DENIED`, and `UNAVAILABLE`.
  - Immediate stream rejection on `DENIED` or `PROMPT` devices with descriptive `AudioError`.
  - Mid-stream permission revocation and device disconnect handling: gracefully halts active streams and transitions controller to `ERROR` state.
  - Frozen, immutable `AudioDevice` metadata with device formatting capabilities.

---

### 6. Audio Capture Lifecycle Controller (Days 10 & 11)
- **Module:** `voicebot.lifecycle`
- **Classes / Enums:** `LifecycleState`, `AudioLifecycleController`
- **State Machine Transitions:**
  - Enforces strict transition rules: `INITIALIZED` -> `RECORDING` <-> `PAUSED` -> `STOPPED` / `ERROR`.
  - Blocks illegal transitions (e.g. `PAUSED` -> `RECORDING` without `resume()`) with actionable error messages.
  - **Pause Frame Suppression:** Incoming audio frames during `PAUSED` state are safely suppressed without corrupting sequence offsets.
  - **Thread-Safe State Locking:** Synchronized state transitions preventing race conditions in asynchronous ingestion loops.
  - **Resource Teardown:** Clean adapter release on `stop()` with idempotent guarantees.

---

### 7. Deterministic Voice Activity Detector (Days 10 & 11)
- **Module:** `voicebot.vad`
- **Classes:** `VoiceActivityDetector`, `VADResult`
- **Features:**
  - **Energy Detection:** Computes normalized Root Mean Square (RMS) energy in `[0.0, 1.0]` with zero-division guard.
  - **Configurable Energy Threshold:** Classifies speech vs. silence based on tunable `energy_threshold` (default: 0.02).
  - **Minimum Speech Duration Debouncing:** Suppresses short clicks, mic pops, or keyboard taps (`min_speech_duration_ms=100.0ms`) until sustained speech is verified.
  - **Speech Hangover Debouncing:** Prevents inter-word syllable clipping during natural pauses.
  - **100% Deterministic Testing:** Built-in synthetic waveform generators for reproducible offline verification.

---

### 8. Bounded Audio Stream Buffer & Backpressure (Days 12 & 13)
- **Module:** `voicebot.buffer`
- **Classes / Enums:** `BoundedAudioBuffer`, `DropStrategy`, `BufferStatistics`
- **Features:**
  - **Capacity-Bounded Ring Buffer:** Strict chunk limit (`max_chunks`) preventing unbounded memory growth.
  - **3 Configurable Drop Strategies:** `DROP_OLDEST` (evicts oldest chunk), `DROP_NEWEST` (drops incoming chunk), and `REJECT_NEW` (raises buffer full error).
  - **High-Water Mark Backpressure Signaling:** `is_backpressure_active` flag triggers when buffer reaches 80% occupancy to alert upstream producers before dropping.
  - **Sequence Integrity & Anomaly Tracking:** Detects and counts sequence gaps (`gaps_detected`) and late/out-of-order chunks (`late_chunks_detected`).
  - **Packet Loss Telemetry:** Tracks cumulative dropped chunks (`dropped_chunk_counter`).

---

### 9. Robustness Suite & Diagnostics Telemetry (Day 14)
- **Modules:** `voicebot.diagnostics`, `tests/test_audio_pipeline.py`
- **Features:**
  - `collect_diagnostics()` snapshots lifecycle state, buffer statistics, and VAD metrics into an exportable `PipelineDiagnostics` dataclass.
  - Comprehensive robustness tests verifying sequence gap detection, out-of-order chunk recovery, and noise discrimination (ambient noise vs. transient clicks vs. sustained speech).

---

### 10. Live Audio Pipeline & VAD Dashboard Demo (Day 14)
- **Module:** `voicebot.cli`
- **Features:**
  - Extended with `--pipeline` flag for a live visual ASCII terminal dashboard.
  - Displays real-time RMS energy meters, VAD speech/silence badges (`SPEECH [ON]` / `SILENCE [OFF]`), and buffer telemetry.
  - Simulated assistant pauses via `--demo-pause` and realistic pacing via `--realtime`.

---

## Week 3 Deliverables (Days 15–21: Workflow & Integration)

### 11. Safe PCM Audio Normalization (Days 15 & 16)
- **Module:** `voicebot.normalizer`
- **Classes:** `AudioNormalizer`, `AudioQualityMetrics`
- **Features:**
  - **Dynamic Peak Scaling:** Scales audio chunks to target peak amplitude (default: 0.95) with configurable gain limits (default: 24.0 dB boost cap).
  - **Comprehensive Multi-Format Support:** Accurately normalizes 8-bit unsigned PCM, 16-bit signed integer PCM, 24-bit packed PCM, and 32-bit floating-point PCM in both mono and stereo.
  - **Acoustic Metrics:** Computes RMS energy, peak amplitude, DC offset, dynamic range, and clipping counters per audio chunk.
  - **Zero-Division & Silence Guard:** Safely handles pure digital silence and DC offset signals without floating-point overflow or NaN generation.
  - **Preservation of Byte Alignment:** Output buffers strictly preserve exact byte lengths and frame boundaries (`len(data) % bytes_per_frame == 0`).

---

### 12. Typed Speech Events & Pre-Roll Processor (Days 15 & 16)
- **Module:** `voicebot.events`
- **Classes / Enums:** `EventType`, `AudioEvent`, `SpeechStartedEvent`, `AudioFrameEvent`, `SpeechEndedEvent`, `EventStatistics`, `SpeechEventProcessor`
- **Features:**
  - **Lossless Pre-Roll Lookback Buffer:** Maintains a bounded lookback FIFO ring buffer (default: 8 chunks / 160ms) of leading frames during VAD duration debouncing. Flushes retained frames upon confirmed onset to prevent syllable clipping.
  - **End-to-End Tracing:** Propagates top-level `session_id` and mints unique UUID `correlation_id` per speech turn across all onset, audio frame, and offset events.
  - **Strict Monotonic Ordering:** Dispatches events with strictly increasing monotonic sequence numbers (`SpeechStartedEvent` $\to$ `AudioFrameEvent`s $\to$ `SpeechEndedEvent`).
  - **Safe Flush:** Terminal teardown method `flush()` terminates any active speech turn cleanly and resets debouncing state upon stream shutdown or cancellation.

---

### 13. Mid-Stream Device-Loss Recovery & Explicit Cancellation (Days 17 & 18)
- **Modules:** `voicebot.lifecycle`, `voicebot.device`
- **Classes / Enums:** `LifecycleState.RECONNECTING`, `LifecycleState.CANCELLED`, `AudioLifecycleController`
- **Features:**
  - **Mid-Stream Device Recovery:** Detects unexpected device disconnection during streaming. Rather than crashing, the lifecycle controller transitions to `RECONNECTING`, automatically searches for a valid fallback device (e.g. system default mic), re-requests permissions if needed, and resumes streaming seamlessly while preserving the session ID.
  - **Explicit Cancellation (`cancel`):** Enables prompt cancellation of an in-progress capture turn (e.g., user barge-in or interruption). Halts audio capture, purges queued chunks from `BoundedAudioBuffer` to immediately release memory, flushes the event processor, and transitions state to `CANCELLED`.
  - **Mock Device Simulation:** Enhanced `MockAudioDeviceAdapter` supporting deterministic disconnection and simulated auto-reconnect via `disconnect_device()`, `reconnect_device()`, and `simulate_disconnect_after()`.

---

### 14. Speech-to-Text Transcription Bridge & Telemetry (Days 19 & 20)
- **Module:** `voicebot.transcription_bridge`
- **Classes:** `TranscriptionBridge`
- **Features:**
  - **Teammate Module Integration:** Connects the Audio & VAD pipeline (`SpeechEventProcessor`) directly to the team's `src.voice.adapter.BaseTranscriber` (and deterministic `FakeTranscriber`) and feeds `src.voice.accumulator.SegmentAccumulator`.
  - **Safe Metadata Correlation:** Subscribes via transcriber event listeners to safely enrich emitted `TranscriptEvent` instances with `metadata["correlation_id"]`, preserving turn correlation end-to-end without violating Pydantic schema validation or mutating frozen audio events.
  - **Sequence Gap Detection & Telemetry:** Monitors chunk sequence continuity and detects missing chunks. Accurately records gap counts and missing frame telemetry in `get_telemetry()`, pushing only genuine received audio bytes without synthesizing fake audio padding.
  - **Silence Suppression & False Trigger Rejection:** Sustained silence frames and transient click noises (< 100ms) are suppressed before transcription, ensuring zero spurious transcript events are emitted.
  - **Turn Finalization:** Receives `SpeechEndedEvent` and triggers `transcriber.finish_audio()`, guaranteeing that `FINAL_TRANSCRIPT` and STT `SPEECH_ENDED` are emitted before utterance conclusion.

---

### 15. Integrated CLI Speech & STT Demonstration (Day 21)
- **Module:** `voicebot.cli`
- **Features:**
  - Extended with `--integration` flag demonstrating the full Week 3 end-to-end voicebot workflow.
  - Shows real-time audio chunk capture, VAD state, typed event dispatch (`SPEECH_STARTED`, `AUDIO_FRAME`, `SPEECH_ENDED`), sequence numbering, correlation ID tracing, transcription bridge telemetry, and final locked transcript text with word analytics.

---

---

## Week 4 Deliverables (Days 22–30: Hardening & Production Release)

### 16. Audio Pipeline Latency & Memory Profiling (Days 22–24)
- **Module:** `voicebot.profiler`
- **Classes:** `AudioPipelineProfiler`, `LatencyMetrics`, `MemoryMetrics`, `ProfileReport`
- **Features:**
  - **High-Precision Latency Tracking:** Uses `time.perf_counter_ns()` to compute nanosecond-resolution timing across all pipeline stages (`normalizer`, `vad`, `buffer`, `event_processor`, `stt_bridge`).
  - **Statistical Percentiles:** Evaluates sample count, average, minimum, maximum, p50 (median), p95, and p99 latencies, along with end-to-end throughput (chunks/second).
  - **Overhead Calibration:** Calibrates baseline profiler invocation overhead (`calibrate_overhead()`) so measurement operations do not contaminate pipeline benchmarks.
  - **Heap Memory Monitoring & Leak Detection:** Uses standard library `tracemalloc` with warm-up phase (30–50 chunks) to record baseline, current, and peak memory, asserting memory stabilization and detecting memory leaks.

### 17. Real-Time Visible Capture Indicators (Days 22–24)
- **Module:** `voicebot.profiler`, `voicebot.cli`
- **Function:** `get_capture_indicator(state, is_speech, energy)`
- **Visual Badges:**
  - `[● REC | SPEECH ACTIVE (RMS: ...)]` / `[● REC | LISTENING (RMS: ...)]`: Displayed when active audio streaming is in progress.
  - `[⏸ PAUSED | CAPTURE SUSPENDED]`: Displayed during assistant speech or user pause.
  - `[⚠️ RECONNECTING | FALLBACK ACTIVE]`: Displayed during mid-stream device loss and fallback recovery.
  - `[✕ CANCELLED | BUFFER FLUSHED]`: Displayed upon cancellation.
  - `[⚪ IDLE | MIC OFF]`: Displayed when capture is inactive or stopped.

### 18. Zero-Disk-Write Privacy Enforcement (Days 22–24)
- **Architecture:** PRD Section 19 strict compliance: 100% transient RAM memory processing.
- **Verification Methodology:**
  - Automated test hooks Python's `builtins.open` to intercept write modes (`w`, `a`, `+`, `x`).
  - Confirms zero write calls target audio files (`.wav`, `.pcm`, `.raw`, `.aac`, `.tmp`, or generic audio buffers).
  - Executes full sessions in an isolated temporary directory and asserts zero disk artifacts are left behind.
- **Privacy Test Limitations & Boundary:**
  - The `builtins.open` hook intercepts all file creation and write attempts originating from Python code.
  - *Known Limitation:* Low-level external C extensions or direct OS kernel system calls that bypass Python's runtime (e.g., raw POSIX/Win32 `CreateFile` / `write()` syscalls) are not captured by Python-level hooks. Within the Python audio engine boundaries, zero audio persistence is strictly guaranteed.

### 19. Measured Profiling Benchmark Results (Actual Machine Metrics)
```text
==========================================================================
  Audio Pipeline Profiling & Hardening Report (Days 22-24)
==========================================================================
  Total Chunks:       200 chunks (4.00s simulated speech)
  Throughput:         416.5 chunks/sec (8.33x faster than real-time: 416.5 ÷ 50 cps)
  Wall Time:          480.15 ms
  Profiler Overhead:  103.7 ns/op
--------------------------------------------------------------------------
  Latency Distribution (Per-Chunk Processing):
    Average:          1.8009 ms
    Median (p50):     2.3048 ms
    95th Percentile:  3.7386 ms
    99th Percentile:  4.7184 ms
    Minimum:          0.2754 ms
    Maximum:          4.9215 ms
--------------------------------------------------------------------------
  Stage Breakdown (Average Latency):
    buffer              : 0.0065 ms (  0.4%) [p95: 0.0138 ms]
    event_processor     : 1.0092 ms ( 56.0%) [p95: 2.3363 ms]
    normalizer          : 0.4636 ms ( 25.7%) [p95: 0.9060 ms]
    stt_bridge          : 0.0333 ms (  1.8%) [p95: 0.0706 ms]
    vad                 : 0.2512 ms ( 13.9%) [p95: 0.4789 ms]
--------------------------------------------------------------------------
  Memory Footprint (Heap Allocations via tracemalloc):
    Baseline Memory:  61.30 KB (after 30 warmup chunks)
    Current Memory:   99.59 KB
    Peak Memory:      145.62 KB
    Net Growth:       +38.29 KB
    Leak Check:       PASSED (No leak detected)
--------------------------------------------------------------------------
  Privacy & Disk Persistence Check:
    Disk Writes:      0 bytes written
    Privacy Status:   PASSED (Zero audio disk writes)
==========================================================================
```

---

### 20. Stress & Endurance Testing Suite (Days 25–27)
- **Module:** `tests/test_stress_and_recovery.py`
- **Features & Measured Resilience:**
  - **Long-Session Endurance:** Sustained streaming across 5,000 synthetic audio chunks (100 seconds of continuous audio at 50 cps) completed in under 10 seconds without pipeline crashes, buffer overflows beyond capacity, or state corruption.
  - **Heap Memory Endurance:** Tracked heap memory via `tracemalloc` across 3,000 continuous chunks; verified that post-warmup memory growth is strictly bounded (< 96 KB growth across 2,800 active chunks).
  - **Latency Stability Under Load:** Processed 2,000 continuous audio chunks and verified zero cumulative latency drift; final-block average latency remained strictly within 3.5x of the initial-block average.
  - **Bounded Buffer Backpressure Stress:**
    - Pushed 1,000 chunks into a buffer of capacity 10 with `DROP_OLDEST`; verified 990 dropped chunks and head retention of chunk sequence 990.
    - Pushed 1,000 chunks into a buffer of capacity 10 with `DROP_NEWEST`; verified 990 dropped chunks and head retention of initial chunk sequence 0.
    - Tested rapid interleaved push/pull operations across 1,000 cycles with zero occupancy violations.
  - **Rapid Silence/Speech Alternating Cycles:** Executed 50 consecutive cycles of rapid voice/silence bursts (1,000 chunks total); verified exact 1:1 pairing between 50 `SpeechStartedEvent` and 50 `SpeechEndedEvent` emissions without orphaned turns.
  - **Repeated Mid-Stream Device Disconnection & Recovery:** Executed 30 consecutive mid-stream device disconnect and fallback reconnect cycles (`primary` $\leftrightarrow$ `fallback`); verified 100% recovery without host crashes or deadlocks.
  - **Rapid Session Cancellation:** Executed 25 consecutive start $\to$ capture $\to$ cancel cycles; verified immediate stream termination and complete memory release of queued chunks (`buffer.clear()`).
  - **Multi-Turn End-to-End Integration Stress:** Streamed 1,000 chunks through `SpeechEventProcessor` and `TranscriptionBridge` across 3 conversational turns; confirmed 0 sequence gaps, 0 missing chunks, and 100% transcript segment accumulation.

---

### 21. Device Troubleshooting & Regression Fixtures (Days 28–29)
- **Documentation:** [`docs/DEVICE_TROUBLESHOOTING.md`](docs/DEVICE_TROUBLESHOOTING.md) — Comprehensive practical operational and developer guide for diagnosing audio hardware, OS permissions, disconnects, buffer backpressure, and clipping.
- **Regression Suite:** `tests/test_troubleshooting_regressions.py` (16 automated regression tests validating all documented failure paths).
- **Core Diagnostics Covered:**
  - **Device Detection & Enumeration:** Validates behavior when 0 devices are available (`AudioError: No audio devices available`), invalid device schema arguments, and missing device ID selection.
  - **Permission Failures & Dynamic Revocation:** Validates immediate refusal under `PermissionState.DENIED`, automatic permission requests under `PROMPT`, and graceful transition to `ERROR` upon mid-stream permission revocation.
  - **Mid-Stream Disconnect & Recovery:** Confirms that unplugging a primary USB mic mid-stream seamlessly triggers auto-reconnect to fallback built-in microphone, preserves `session_id`, and avoids host process crashes.
  - **Buffer Backpressure & Drop Strategy Enforcement:** Tests the 80% watermark backpressure signal, FIFO chunk retention in `DROP_OLDEST` (keeps freshest speech) vs `DROP_NEWEST` (keeps earliest speech), and exception raising in `REJECT_NEW`.
  - **Audio Frame Alignment & Dynamic Normalization Safety:** Asserts rejection of misaligned byte frames (`len % bytes_per_frame != 0`) and guarantees mathematical stability (zero division, NaN, and clipping guard) on digital silence and square waves.
  - **Interruption (Barge-In) Cancellation:** Verifies that invoking `controller.cancel(buffer=..., processor=...)` immediately stops streaming, purges 100% of buffered chunks, and resets speech debouncing state.

---

### 22. Release Gate & Dual-Scenario Demonstration (Day 30)
- **Module:** `voicebot.cli`, `tests/test_release_gate.py`
- **Release Verification Highlights:**
  - **Dual-Scenario End-to-End Demo (`--demo-release`):**
    - **Scenario A (Normal Voicebot Pipeline):** Audio ingestion $\to$ Normalization $\to$ VAD segmentation $\to$ Speech event dispatching $\to$ STT transcription bridge $\to$ Word analytics and segment accumulation. Verified zero sequence gaps, zero dropped frames, and 100% transcript recovery.
    - **Scenario B (Hardware Disconnect, Fallback Auto-Recovery & User Barge-In):** Active streaming on primary USB microphone $\to$ unexpected mid-stream disconnect $\to$ visual alert badge `[⚠️ RECONNECTING | FALLBACK ACTIVE]` $\to$ automatic fallback to system default microphone (`builtin-fallback-mic`) $\to$ seamless streaming resumption with preserved `session_id` $\to$ mid-stream user barge-in triggering explicit session cancellation $\to$ visual badge `[✕ CANCELLED | BUFFER FLUSHED]` $\to$ 100% queue memory released to 0 bytes.
  - **Automated Release Gate Suite (`tests/test_release_gate.py`):** 5 automated release verification tests ensuring full pipeline compliance, resilience, privacy invariance (zero disk writes), and clean CLI execution.

---

## Known Limitations & Operating Boundaries

1. **Synthetic Hardware Abstraction Layer:** The core audio pipeline operates against `AudioDeviceAdapter` and `MockAudioDeviceAdapter`. In offline and CI environments, audio is generated via deterministic synthetic sine waves and PCM buffers (PRD Section 19 compliance). For physical hardware deployment, a platform-specific PyAudio/SoundDevice adapter implementing `AudioDeviceAdapter` can be plugged in without mutating any downstream schemas or controllers.
2. **Privacy Enforcement Boundary:** Automated privacy verification hooks Python's `builtins.open` to monitor write operations (`w`, `a`, `+`, `x`). This guarantees that the Python audio engine never persists audio buffers to disk. Direct OS kernel system calls or third-party compiled C/C++ drivers that bypass Python's runtime environment are outside Python-level interception, but within all application code boundaries, zero-disk persistence is strictly enforced.
3. **Bounded Buffer Capacity Tuning:** Under `DropStrategy.DROP_OLDEST`, buffer overflow will discard stale audio frames to favor conversational freshness. In bandwidth-constrained or exceptionally slow transcription environments, increase `max_chunks` or monitor `is_backpressure_active` (triggers at 80% occupancy) to throttle ingestion producers.

---

## Running the Demonstrations

From the repository root:

### Day 30 Final Release Gate Dual-Scenario Demo:
```powershell
python projects/sde-2-voicebot/src/voicebot/cli.py --demo-release
```

### Week 4 Pipeline Profiling Benchmark Demo (Days 22–24):
```powershell
python projects/sde-2-voicebot/src/voicebot/cli.py --profile --profile-chunks 200
```

### Week 3 Integrated Voice & STT Demo (Day 21):
```powershell
python projects/sde-2-voicebot/src/voicebot/cli.py --integration
```

### Week 2 Pipeline & VAD Live Demo (Day 14):
```powershell
python projects/sde-2-voicebot/src/voicebot/cli.py --pipeline --frames-per-chunk 1600 --chunk-count 10 --demo-pause --realtime
```

### Week 1 Baseline Demo (Days 5 & 6):
```powershell
python projects/sde-2-voicebot/src/voicebot/cli.py
```

---

## Running Tests

From the repository root:

### Run the Complete Test Suite (Weeks 1, 2, 3, and 4):
```powershell
python -m pytest projects/sde-2-voicebot/tests/ -v
```

### Run Specific Test Modules:
```powershell
# Day 30 Release Gate Tests
python -m pytest projects/sde-2-voicebot/tests/test_release_gate.py -v

# Week 4 Device Troubleshooting Regressions (Days 28-29)
python -m pytest projects/sde-2-voicebot/tests/test_troubleshooting_regressions.py -v

# Week 4 Stress & Recovery Tests (Days 25-27)
python -m pytest projects/sde-2-voicebot/tests/test_stress_and_recovery.py -v

# Week 4 Profiling, Capture Indicator & Privacy Tests (Days 22-24)
python -m pytest projects/sde-2-voicebot/tests/test_profiling_and_privacy.py -v

# Week 3 Transcription Integration Tests (Days 19-20)
python -m pytest projects/sde-2-voicebot/tests/test_transcription_integration.py -v

# Week 3 Device Recovery & Cancellation Tests (Days 17-18)
python -m pytest projects/sde-2-voicebot/tests/test_device_recovery.py -v

# Week 3 Normalizer & Speech Event Tests (Days 15-16)
python -m pytest projects/sde-2-voicebot/tests/test_normalizer.py projects/sde-2-voicebot/tests/test_events.py -v
```

---

## Comprehensive Test Suite Summary (251 / 251 Tests Passing - 100% Success)

### Week 1 Tests (66 Tests):
- **`test_schemas.py` (24 tests):** Format initialization, boundary values, channel/sample-rate validation, immutability, and docstring checks.
- **`test_mock_microphone.py` (14 tests):** Chunk count, monotonic sequencing, drift-free timestamps, determinism, and backward-compatible positional constructor.
- **`test_chunker.py` (12 tests):** Buffer and stream chunking, partial tail chunks, timing validation on empty streams, and convenience functions.
- **`test_chunk_validation.py` (16 tests):** Valid happy paths across 8kHz to 48kHz, empty buffer rejection, invalid types, corrupt/misaligned frame detection, and CLI demo execution.

### Week 2 Tests (97 Tests):
- **`test_device.py` (35 tests):** Device selection, permission states (`PROMPT`, `GRANTED`, `DENIED`, `UNAVAILABLE`), immediate rejections, mid-stream revocation.
- **`test_lifecycle.py` (23 tests):** Lifecycle state machine (`start`, `pause`, `resume`, `stop`), transition matrix, pause frame suppression, resource cleanup.
- **`test_vad.py` (15 tests):** RMS energy calculation, silence vs speech, debounce duration, transient click rejection, sustained speech triggers.
- **`test_buffer.py` (16 tests):** Bounded ring buffer, 80% watermark backpressure, 3 drop strategies, dropped chunk counter, sequence gap and late chunk tracking.
- **`test_audio_pipeline.py` (8 tests):** Sequence gap handling, late/out-of-order chunk recovery, noise discrimination, full end-to-end audio pipeline lifecycle.

### Week 3 Tests (40 Tests):
- **`test_normalizer.py` (11 tests):** PCM scaling across 8/16/24/32-bit audio formats, gain limits (24 dB), clipping metrics, zero-division protection, byte length and alignment preservation.
- **`test_events.py` (10 tests):** Typed event contracts (`SpeechStartedEvent`, `AudioFrameEvent`, `SpeechEndedEvent`), immutability, pre-roll lookback FIFO buffer, lossless speech onset, and monotonic sequencing.
- **`test_device_recovery.py` (10 tests):** Mid-stream device-loss detection, auto-reconnection to fallback device, permission handling on recovery, explicit cancellation (`cancel()`) with buffer release.
- **`test_transcription_integration.py` (10 tests):** Full end-to-end mock transcription, strict event ordering (`SPEECH_STARTED` $\to$ `FINAL_TRANSCRIPT` $\to$ `SPEECH_ENDED`), sequence gap detection telemetry, correlation ID preservation, silence suppression, and false click rejection.

### Week 4 Tests (48 Tests - Hardening & Release Gate):
- **`test_profiling_and_privacy.py` (16 tests - Days 22–24):** Nanosecond profiler calibration, percentile distribution ordering (`min <= p50 <= p95 <= p99 <= max`), reproducible throughput, per-stage latency breakdown, heap allocation tracking via `tracemalloc`, memory leak verification with warm-up phase, visible capture indicator badges (`RECORDING`, `PAUSED`, `STOPPED`, `RECONNECTING`, `CANCELLED`), zero-disk-write privacy verification via `open()` write monitoring in isolated temp directories, and `--profile` CLI execution.
- **`test_stress_and_recovery.py` (11 tests - Days 25–27):** 5,000-chunk long session endurance (100s audio), memory endurance (< 96 KB heap growth across 2,800 active chunks), latency stability under continuous streaming (final block average within 3.5x initial block), extreme buffer overflow (1,000 chunks) under `DROP_OLDEST` and `DROP_NEWEST`, rapid silence/speech burst cycles (50 bursts / 1,000 chunks), repeated mid-stream device disconnect/reconnect (30 consecutive cycles), rapid session cancellation stress (25 cycles with clean buffer flush), reconnect failure exhaustion without deadlocks, and end-to-end multi-turn transcription bridge streaming (1,000 chunks, 3 turns, 0 gaps).
- **`test_troubleshooting_regressions.py` (16 tests - Days 28–29):** Regression fixtures validating all documented failure scenarios in `docs/DEVICE_TROUBLESHOOTING.md`: empty device lists, unknown device ID lookup, schema validation bounds, initial `DENIED` refusal, `PROMPT` auto-requesting, mid-stream permission revocation, mid-stream disconnect auto-recovery to fallback with preserved `session_id`, device loss exhaustion, buffer 80% watermark backpressure signaling, `DROP_OLDEST` / `DROP_NEWEST` / `REJECT_NEW` policy enforcement, corrupted frame alignment rejection, digital silence zero-division safety, full-scale clipping safety, and barge-in cancellation memory release.
- **`test_release_gate.py` (5 tests - Day 30):** Automated release gate verification: Scenario A happy path normal voicebot pipeline with transcript verification, Scenario B mid-stream disconnect auto-recovery with fallback default mic, Scenario B barge-in cancellation memory release, privacy zero-disk-write invariance, and `--demo-release` zero exit code execution.

**Grand Total:** **251 / 251 PASSED (188 subtests passed, 0 failures, 0 errors in ~9.57s - 100% Success)**
