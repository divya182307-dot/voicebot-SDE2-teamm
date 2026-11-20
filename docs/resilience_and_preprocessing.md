# Resilience, Bounded Retries, Error Normalization & Audio Preprocessing (Days 12–13 Milestone)

This document details the fault-tolerance primitives and acoustic preprocessing engine implemented for **Week 2 (Days 12–13)** of the **Academia AI Voice Co-Pilot**.

---

## 1. Overview & Architecture

Production voicebots interface with external acoustic hardware and network-bound speech recognition APIs:
1. **Audio Variability**: Audio frames arrive in non-standard sample rates (8kHz telephony, 44.1kHz music, 48kHz OS default) with low volumes, DC biases, or stereo channels.
2. **Transient Network Faults**: Socket disconnects, rate limits (HTTP 429), timeouts, and temporary server outages (503s) can occur.
3. **Exception Leak Prevention**: Upstream callers (UI streams, LLM agents) must receive consistent, strongly-typed domain errors—**never raw socket, HTTP, or unhandled vendor exceptions**.

```
                   [ Raw Input Audio Frame ]
                   (e.g., 48kHz Stereo PCM)
                              │
                              ▼
               ┌───────────────────────────────┐
               │       AudioPreprocessor       │
               │  - Stereo -> Mono Downmix     │
               │  - Linear Resampling -> 16kHz │
               │  - DC Offset Centering        │
               │  - Peak / RMS Normalization   │
               └──────────────┬────────────────┘
                              │ Standardized 16kHz Mono PCM
                              ▼
               ┌───────────────────────────────┐
               │    TranscriptionOrchestrator  │
               │                               │
               │   ┌────────────────────────┐  │
               │   │     TimeoutPolicy      │  │
               │   └───────────┬────────────┘  │
               │               │               │
               │   ┌───────────▼────────────┐  │
               │   │      RetryPolicy       │  │
               │   │ (Exponential + Jitter) │  │
               │   └───────────┬────────────┘  │
               │               │               │
               │   ┌───────────▼────────────┐  │
               │   │    ErrorNormalizer     │  │
               │   │  (No Raw Leaks -> E2E) │  │
               │   └───────────┬────────────┘  │
               │               │               │
               │               ▼               │
               │       Transcriber Adapter     │
               └───────────────┬───────────────┘
                               │
                               ▼
                   [ Clean Transcript Events ]
```

---

## 2. Audio Preprocessing Engine (`src/voice/preprocessing.py`)

### A. Linear Interpolation Resampling (`resample_pcm16`)
* Pure-Python, ultra-efficient sample rate conversion using signed 16-bit PCM arrays (`array.array('h')`).
* Scales arbitrary source sampling rates ($8\text{kHz}, 22.05\text{kHz}, 24\text{kHz}, 32\text{kHz}, 44.1\text{kHz}, 48\text{kHz}$) into standard $16,000\text{Hz}$ speech audio.
* Full PEP 594 compliance (does not depend on the deprecated `audioop` module removed in Python 3.13+).

### B. Amplitude & Loudness Normalization (`normalize_amplitude_pcm16`)
* **Peak Normalization**: Scales waveform so the maximum peak matches target dBFS (e.g., `-1.0 dBFS` $\approx 89.1\%$ full scale), maximizing dynamic range without clipping.
* **RMS Normalization**: Adjusts gain to match conversational speech energy targets (e.g., `-20.0 dBFS`).
* **DC Offset Centering**: Computes mean offset $\mu = \frac{1}{N}\sum s_i$ and centers the waveform around 0.
* **Hard Clamping**: Clamps samples to $[-32768, 32767]$ to guarantee no integer overflow.

### C. Channel Downmixing (`convert_stereo_to_mono`)
* Fast downmixing of 2-channel interleaved stereo audio to 1-channel mono by averaging $(L_i + R_i) // 2$.

---

## 3. Resilience & Error Normalization Layer (`src/voice/resilience.py`)

### A. Bounded Exponential Backoff Retries (`RetryPolicy`)
* Configurable max attempts (`max_retries: int = 3`).
* Exponential delay scaling: $\text{delay} = \min(\text{initial} \times \text{factor}^{\text{attempt}-1}, \text{max\_delay})$.
* Full randomization jitter to avoid thundering herd contention.
* **Transient vs. Non-Retryable Error Classification**:
  * *Retryable*: Connection drops, reset by peer, timeouts, 429 rate limits, 503 service unavailable.
  * *Non-Retryable (Immediate Failure)*: 401/403 Authentication failures, invalid audio formats, state machine errors.

### B. Timeouts (`TimeoutPolicy`)
* Enforces deadlines across distinct phases:
  * `connect_timeout_seconds` (default: 3.0s)
  * `chunk_timeout_seconds` (default: 1.5s)
  * `operation_timeout_seconds` (default: 10.0s)
* Converts timeout deadlines into domain `TranscriberTimeoutError` exceptions.

### C. Error Normalizer (`ErrorNormalizer`)
* Translates raw vendor, socket, HTTP, and system exceptions into the domain taxonomy:
  * `ConnectionResetError` / socket drop $\rightarrow$ `TranscriberConnectionError`
  * `asyncio.TimeoutError` $\rightarrow$ `TranscriberTimeoutError`
  * `429 Too Many Requests` $\rightarrow$ `TranscriberRateLimitError`
  * `401 / 403 Forbidden` $\rightarrow$ `TranscriberAuthenticationError`
  * `500 / 502 / 503 / 504` $\rightarrow$ `TranscriberServiceUnavailableError`
  * Raw unknown exceptions $\rightarrow$ `TranscriberError`
* **Zero Exception Leak Guarantee**: Generates structured `TranscriptError` models and canonical `TranscriptEvent(event_type=ERROR)` packets.

---

## 4. Usage Example

```python
import asyncio
from src.voice import (
    AudioPreprocessorConfig,
    OrchestratorConfig,
    RetryConfig,
    TimeoutConfig,
    TranscriptionOrchestrator,
)

async def main():
    config = OrchestratorConfig(
        enable_preprocessing=True,
        preprocessor_config=AudioPreprocessorConfig(
            target_sample_rate=16000,
            enable_resampling=True,
            enable_normalization=True,
            normalization_method="peak",
            target_peak_dbfs=-1.0,
        ),
        retry_config=RetryConfig(max_retries=3, initial_delay_seconds=0.05),
        timeout_config=TimeoutConfig(chunk_timeout_seconds=1.5),
    )

    async with TranscriptionOrchestrator(session_id="lecture-02", config=config) as orch:
        # Ingest 48kHz audio directly - preprocessor automatically resamples and normalizes
        chunk_48k = b"\x00\x10" * 4800
        await orch.push_audio(chunk_48k, sample_rate=48000)
        await orch.finish_audio()

        print("Final Transcript:", orch.get_final_text())
        print("Metrics:", orch.metrics.model_dump())

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 5. Verification & Test Suite

Validated by **30 tests** across:
* `tests/test_preprocessing.py`: 13 tests for resampling, downmixing, peak normalization, RMS, and DC removal.
* `tests/test_resilience.py`: 17 tests for retries, timeouts, error normalization, and wrapper integration.

Run tests:
```bash
python -m pytest tests/test_preprocessing.py tests/test_resilience.py -v
```
All **154 tests** pass across the entire Voicebot repository.

