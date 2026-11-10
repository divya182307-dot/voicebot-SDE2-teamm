# SDE-2 Voicebot - Audio & VAD Engine (Weeks 1 & 2)

**Academia - AI Voice Co-Pilot**  
**Track:** SDE-2 Voicebot (`projects/sde-2-voicebot/`)  
**Phase:** Week 1 Foundation & Week 2 Audio Lifecycle, VAD & Buffering  
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

---

## Running Tests

From the repository root:

```powershell
python -m pytest projects/sde-2-voicebot -v
```

Or using standard unittest discover:

```powershell
$env:PYTHONPATH="projects/sde-2-voicebot/src"; python -m unittest discover -s projects/sde-2-voicebot/tests -v
```

---

## Comprehensive Test Suite Summary (163 / 163 Tests Passing - 100% Success)

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

**Grand Total:** **163 / 163 PASSED (177 subtests passed, 0 failures, 0 errors in ~0.35s)**
