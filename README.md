# SDE-2 Voicebot - Audio, VAD & STT Engine (Weeks 1, 2 & 3)

**Academia - AI Voice Co-Pilot**  
**Track:** SDE-2 Voicebot (`projects/sde-2-voicebot/`)  
**Phase:** Week 1 Foundation, Week 2 Audio Lifecycle & VAD, Week 3 Workflow & Integration  
**Workstream:** W1: Audio and Voice Activity  
**Owner:** Siri G R  

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

## Running the Demonstrations

From the repository root:

### Week 1 Baseline Demo (Days 5 & 6):
```powershell
python projects/sde-2-voicebot/src/voicebot/cli.py
```

### Week 2 Pipeline & VAD Live Demo (Day 14):
```powershell
python projects/sde-2-voicebot/src/voicebot/cli.py --pipeline --frames-per-chunk 1600 --chunk-count 10 --demo-pause --realtime
```

### Week 3 Integrated Voice & STT Demo (Day 21):
```powershell
python projects/sde-2-voicebot/src/voicebot/cli.py --integration
```

---

## Running Tests

From the repository root:

### Run the Complete Test Suite (Weeks 1, 2, and 3):
```powershell
python -m pytest projects/sde-2-voicebot -v
```

### Run Specific Test Modules:
```powershell
# Week 3 Transcription Integration Tests (Days 19-20)
python -m pytest projects/sde-2-voicebot/tests/test_transcription_integration.py -v

# Week 3 Device Recovery & Cancellation Tests (Days 17-18)
python -m pytest projects/sde-2-voicebot/tests/test_device_recovery.py -v

# Week 3 Normalizer & Speech Event Tests (Days 15-16)
python -m pytest projects/sde-2-voicebot/tests/test_normalizer.py projects/sde-2-voicebot/tests/test_events.py -v
```

---

## Comprehensive Test Suite Summary (203 / 203 Tests Passing - 100% Success)

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

**Grand Total:** **203 / 203 PASSED (188 subtests passed, 0 failures, 0 errors in ~0.71s)**
