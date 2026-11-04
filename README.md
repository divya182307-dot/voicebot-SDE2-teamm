# SDE-2 Voicebot - Week 1 Deliverables (Audio & VAD)

**Academia - AI Voice Co-Pilot**  
**Track:** SDE-2 Voicebot (`projects/sde-2-voicebot/`)  
**Phase:** Week 1 — Foundation (Workstream W1: Audio and Voice Activity)  
**Owner:** Siri G R  

---

## Deliverables Summary

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

## Running the CLI Demonstration

From the repository root:

```powershell
python projects/sde-2-voicebot/src/voicebot/cli.py
```

### With Custom Audio Parameters (e.g. 20ms Speech Chunks at 16kHz):

```powershell
python projects/sde-2-voicebot/src/voicebot/cli.py --sample-rate 16000 --channels 1 --chunk-count 5 --frames-per-chunk 320
```

---

## Running Tests

From the repository root:

```powershell
$env:PYTHONPATH="projects/sde-2-voicebot/src"; python -m unittest discover -s projects/sde-2-voicebot/tests -v
```

Or using `pytest`:

```powershell
$env:PYTHONPATH="projects/sde-2-voicebot/src"; python -m pytest projects/sde-2-voicebot/tests -v
```

---

## Test Suite Summary (66 / 66 Tests Passing - 100% Success)

- **`test_schemas.py` (24 tests):** Format initialization, boundary values, channel/sample-rate validation, immutability, and docstring checks.
- **`test_mock_microphone.py` (14 tests):** Chunk count, monotonic sequencing, drift-free timestamps, determinism, and backward-compatible positional constructor.
- **`test_chunker.py` (12 tests):** Buffer and stream chunking, partial tail chunks, timing validation on empty streams, and convenience functions.
- **`test_chunk_validation.py` (16 tests):** Valid happy paths across 8kHz to 48kHz, empty buffer rejection, invalid types, corrupt/misaligned frame detection, and CLI demo execution.
- **Total:** **66 / 66 PASSED (114 subtests passed, 0 failures, 0 errors)**
