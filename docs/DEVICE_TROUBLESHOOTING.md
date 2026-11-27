# Audio Capture & Device Troubleshooting Guide

**Academia - AI Voice Co-Pilot (SDE Team 2 — Workstream W1: Audio & VAD)**  
**Target:** Engineering Team, Test Automation & Production Operators  
**Specification:** PRD Section 19 (Zero Hardware, 100% Deterministic Synthetic Audio Mode by Default)

---

## 1. Overview & Architecture

The SDE-2 Voicebot audio engine isolates audio hardware through a layered abstraction model:

```
+-----------------------------------------------------------------+
|                      Client / Voicebot CLI                      |
+-----------------------------------------------------------------+
                                |
                                v
+-----------------------------------------------------------------+
|                   AudioLifecycleController                      |
|       (State machine: INITIALIZED -> RECORDING <-> PAUSED)      |
|             (Handles auto-recovery & explicit cancel)           |
+-----------------------------------------------------------------+
             |                                     |
             v                                     v
+------------------------+             +------------------------+
|   AudioDeviceAdapter   |             |   BoundedAudioBuffer   |
| (MockAudioDeviceAdapter|             | (Backpressure at 80%,  |
|  or hardware wrapper)  |             |  DROP_OLDEST/NEWEST)   |
+------------------------+             +------------------------+
             |
             v
+-----------------------------------------------------------------+
|                     AudioNormalizer & VAD                       |
|           (Gain limit 24dB, energy threshold 0.02)              |
+-----------------------------------------------------------------+
```

### Guarantees:
1. **Zero Hardware Dependency:** By default, all testing and CLI demonstrations operate in deterministic synthetic mock mode (`MockAudioDeviceAdapter`, `MockMicrophone`).
2. **Crash-Free Operation:** Hardware disconnects, permission denials, and buffer overflows never crash the Python host process; all exceptions are typed domain `AudioError` instances.
3. **Zero Disk Writes:** Raw audio is never persisted to disk by default (guaranteed in-memory RAM processing).

---

## 2. Quick-Reference Troubleshooting Matrix

| Error Message / Symptom | Root Cause | Lifecycle State | Remediation Step |
| :--- | :--- | :--- | :--- |
| `No audio devices available.` | No input hardware attached or mock device list is empty. | `ERROR` / `INITIALIZED` | Verify USB mic connection; in mock mode pass `devices=[AudioDevice(...)]`. |
| `device_id must be a non-empty string.` | Blank, whitespace, or invalid device ID passed. | Pre-initialization | Supply valid string ID (e.g. `'mock-default-mic'`). |
| `Microphone permission denied.` | OS or user denied mic access (`PermissionState.DENIED`). | `ERROR` | Enable OS microphone permissions; in mock use `initial_permission=PermissionState.GRANTED`. |
| `Audio device is unavailable.` | Selected hardware physically unplugged before stream start. | `ERROR` | Re-seat USB device or select fallback device via `adapter.select_device()`. |
| Device loss during streaming (USB unplug) | Hardware removed while `RECORDING`. | `RECONNECTING` $\to$ `RECORDING` | Controller automatically recovers to system fallback mic if `auto_reconnect=True`. |
| `Audio capture aborted: device became UNAVAILABLE.` | Device lost and no fallback device available (exhaustion). | `ERROR` | Attach a secondary fallback microphone or increase `max_reconnect_attempts`. |
| `Audio buffer overflow: reached capacity...` | Downstream consumer slower than ingestion rate under `REJECT_NEW`. | `RECORDING` / Aborted | Switch buffer to `DropStrategy.DROP_OLDEST` to maintain real-time speech. |
| `Audio chunk byte length ... not integer multiple...` | Raw byte slice cut across frame boundary. | Pre-capture | Ensure byte buffers are exact multiples of `bytes_per_frame` (e.g. 2 bytes for 16-bit mono). |
| Sudden silence / missing speech turns | VAD threshold too high or debouncing duration too long. | `RECORDING` | Tune `energy_threshold` (default: 0.02) and `min_speech_duration_ms` (default: 100ms). |
| Stale audio heard after interruption (barge-in) | Buffer not flushed when user interrupts. | `CANCELLED` | Call `controller.cancel(buffer=buffer, processor=processor)` to purge queue immediately. |

---

## 3. Deep-Dive Diagnostic & Remediation Procedures

### Scenario 1: Device Detection & Enumeration Failures

#### Problem Description
When initializing the audio pipeline, `adapter.list_devices()` returns an empty list `[]` or `adapter.get_default_device()` raises:
```python
AudioError: No audio devices available.
```

#### Diagnostic Commands
In Python interactive shell or test script:
```python
from voicebot.device import MockAudioDeviceAdapter

adapter = MockAudioDeviceAdapter()
devices = adapter.list_devices()
print(f"Available Devices ({len(devices)}):")
for dev in devices:
    print(f"  - [{dev.device_id}] {dev.name} (default={dev.is_default}, {dev.channels}ch, {dev.default_sample_rate}Hz)")
```

#### Remediation Steps
1. **In Mock Mode (Test/CI):** Ensure at least one `AudioDevice` is supplied to `MockAudioDeviceAdapter`:
   ```python
   from voicebot.device import AudioDevice, MockAudioDeviceAdapter, PermissionState

   primary_mic = AudioDevice(
       device_id="mic-primary",
       name="Primary USB Microphone",
       channels=1,
       default_sample_rate=16000,
       is_default=True,
       sample_width=2,
   )
   adapter = MockAudioDeviceAdapter(devices=[primary_mic], initial_permission=PermissionState.GRANTED)
   ```
2. **In OS Physical Hardware Mode:**
   - **Windows:** Open PowerShell and run `Get-PnpDevice -Class AudioEndpoint` to verify drivers. Open Windows Settings $\to$ *System* $\to$ *Sound* $\to$ *Input* to confirm the microphone is active and not muted.
   - **macOS / Linux:** Run `system_profiler SPAudioDataType` or `arecord -l` to verify hardware enumeration.

---

### Scenario 2: Permission Denials & Mid-Stream Revocation

#### Problem Description
Attempting to start audio capture raises:
```python
AudioError: Microphone permission denied. Cannot start audio capture.
```
Or mid-stream capture raises:
```python
AudioError: Audio capture aborted: device became DENIED.
```

#### Diagnostic Commands
Check permission state directly on the adapter:
```python
perm = adapter.get_permission_state()
print(f"Current Permission State: {perm.value}")
```

#### Remediation Steps
1. **Initial Permission Grant:**
   ```python
   if adapter.get_permission_state() == PermissionState.PROMPT:
       granted = adapter.request_permission()
       if granted != PermissionState.GRANTED:
           raise RuntimeError("User declined microphone permission.")
   ```
2. **OS Privacy Settings:**
   - **Windows:** Go to *Settings* $\to$ *Privacy & security* $\to$ *Microphone*. Ensure *"Microphone access"* and *"Let apps access your microphone"* are toggled **ON**.
   - **macOS:** Go to *System Settings* $\to$ *Privacy & Security* $\to$ *Microphone* and ensure your terminal/IDE (e.g. VS Code, Terminal) is checked.
3. **Mid-Stream Revocation Recovery:** If the OS revokes permission while streaming, the pipeline safely transitions to `LifecycleState.ERROR`. Do not retry in a tight loop; prompt the user to re-enable permission before calling `controller.reset()`.

---

### Scenario 3: Mid-Stream Hardware Disconnection & Recovery

#### Problem Description
A USB headset or wireless microphone disconnects while a user is actively speaking.

#### Automatic Recovery Architecture
The `AudioLifecycleController` includes built-in recovery logic:
```
Active Stream [RECORDING]
       |
  (USB Disconnect)
       |
       v
State: [RECONNECTING] (attempts up to max_reconnect_attempts)
       |
       +---> [Search for Fallback Device (is_default=True)]
       |
       +---> [Request Permission if PROMPT]
       |
       +---> [Resume AudioStream with same session_id]
       |
       v
State: [RECORDING] (0 host crash, stream uninterrupted)
```

#### Code Configuration for Resilient Capture
```python
controller = AudioLifecycleController(
    adapter=adapter,
    max_reconnect_attempts=3,      # Retry up to 3 times before failing
    reconnect_delay_seconds=0.1,   # 100ms debounce between attempts
    auto_reconnect=True,           # Automatic fallback enabled
)
```

#### Exhaustion Handling
If all available devices are unplugged and no fallback device exists:
- The controller safely transitions to `LifecycleState.ERROR`.
- Telemetry records `reconnect_count` without deadlocking background threads.
- Calling `controller.cancel()` resets the controller safely.

---

### Scenario 4: Buffer Overflow & Ingestion Backpressure

#### Problem Description
Under high load or slow downstream consumption (e.g. cloud transcription latency spike), the buffer overflows:
- Under `REJECT_NEW`: `AudioError("Audio buffer overflow: reached capacity of 50 chunks.")`
- Under `DROP_OLDEST`: Old chunks are dropped; `dropped_chunk_counter` increments.

#### Strategy Selection Guide
Configure `BoundedAudioBuffer` based on your use case:

| Strategy | Behavior on Overflow | Recommended Use Case |
| :--- | :--- | :--- |
| `DropStrategy.DROP_OLDEST` | Evicts oldest chunk at queue head. | **Conversational Voicebots (Default):** Discards stale speech so the bot responds to what the user said most recently. |
| `DropStrategy.DROP_NEWEST` | Discards incoming chunk immediately. | **Archival / Recording:** Preserves earlier audio without corrupting existing captured blocks. |
| `DropStrategy.REJECT_NEW` | Raises `AudioError` immediately. | **Strict Debugging / Unit Tests:** Guarantees no silent data loss during performance testing. |

#### Proactive Backpressure Signaling
Listen to `is_backpressure_active` (triggers at 80% occupancy):
```python
buffer = BoundedAudioBuffer(max_chunks=50, high_water_mark=0.8)

# Upstream ingest loop:
if buffer.is_backpressure_active:
    # Throttle producer or log warning before chunks are dropped
    logger.warning("Audio buffer at 80% capacity! Backpressure active.")

buffer.push(chunk)
```

---

### Scenario 5: Frame Misalignment & Audio Artifacts

#### Problem Description
Creating or processing an audio chunk raises:
```python
AudioError: Audio chunk byte length (321) is not an integer multiple of frame size (2).
```

#### Frame Size Reference Table
| Channels | Sample Width | Bytes Per Frame | Valid Chunk Lengths (bytes) |
| :---: | :---: | :---: | :--- |
| 1 (Mono) | 2 (16-bit PCM) | **2 bytes** | Any multiple of 2 (e.g. 640 bytes = 320 frames / 20ms) |
| 2 (Stereo) | 2 (16-bit PCM) | **4 bytes** | Any multiple of 4 (e.g. 1280 bytes = 320 frames / 20ms) |
| 1 (Mono) | 3 (24-bit PCM) | **3 bytes** | Any multiple of 3 (e.g. 960 bytes = 320 frames / 20ms) |
| 1 (Mono) | 4 (32-bit Float) | **4 bytes** | Any multiple of 4 (e.g. 1280 bytes = 320 frames / 20ms) |

#### Remediation
Always slice byte streams using the deterministic `AudioChunker`:
```python
from voicebot.chunker import AudioChunker
from voicebot.schemas import AudioFormat

fmt = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
chunker = AudioChunker(audio_format=fmt, frames_per_chunk=320)  # Exactly 20ms per chunk

# Automatically enforces frame alignment and handles partial trailing bytes
for chunk in chunker.chunk_bytes(raw_pcm_bytes):
    process(chunk)
```

---

### Scenario 6: User Interruption (Barge-In) & Safe Cancellation

#### Problem Description
When the user speaks while the assistant is replying, audio queued in memory must be cancelled immediately to prevent the bot from responding to out-of-date utterances.

#### Remediation Procedure
Call `controller.cancel(buffer=buffer, processor=processor)`:
```python
# Barge-in detected: cancel active turn immediately
controller.cancel(buffer=audio_buffer, processor=event_processor)

# Assert clean cancellation
assert controller.state == LifecycleState.CANCELLED
assert controller.is_cancelled is True
assert audio_buffer.current_occupancy == 0  # 100% memory purged
```
This guarantees:
1. Active `capture_stream` loop terminates immediately.
2. `BoundedAudioBuffer` memory is freed (`clear()`).
3. `SpeechEventProcessor` resets debouncing and clears active correlation IDs.

---

## 4. Operational Checklist for Production Readiness

Before releasing the audio module to production or QA:
- [x] Run full test suite: `python -m pytest projects/sde-2-voicebot/tests/ -v` (assert 230+ tests pass).
- [x] Run stress tests: `python -m pytest projects/sde-2-voicebot/tests/test_stress_and_recovery.py -v`.
- [x] Run regression fixtures: `python -m pytest projects/sde-2-voicebot/tests/test_troubleshooting_regressions.py -v`.
- [x] Verify zero disk writes: `python -m pytest projects/sde-2-voicebot/tests/test_profiling_and_privacy.py -k test_zero_disk_writes_during_active_pipeline`.
- [x] Verify visible capture indicators operate in all states (`RECORDING`, `PAUSED`, `RECONNECTING`, `CANCELLED`).
