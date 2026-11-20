# In-Flight Cancellation & Automatic Mock Provider Fallback

**Milestone:** Week 3 (Days 17–18)  
**Modules:** `src/voice/orchestrator.py`, `src/voice/resilience.py`, `src/voice/exceptions.py`  
**Test Suite:** `tests/test_cancellation_and_fallback.py` (11 tests)  
**Overall Test Suite:** 193 passing tests

---

## 1. Overview & Architectural Goals

Days 17–18 deliver critical high-availability resilience capabilities for the Voicebot streaming pipeline:
1. **Clean In-Flight Cancellation (`cancel()`)**: Enables client applications, UI cancellation buttons, or workflow policy engines to immediately abort ongoing speech recognition sessions safely without hanging, resource leaks, or state corruption.
2. **Automatic Mock Provider Fallback**: When an external/vendor STT provider encounters quota limits (HTTP 429 / quota exhaustion) or network failures (connection reset, refused port, socket timeouts), the orchestrator automatically downgrades and transitions to the local `FakeTranscriber` mock provider without dropping the active session.
3. **Zero Leaked Raw Exceptions**: All network, socket, HTTP, and vendor errors are caught, strictly normalized through `ErrorNormalizer`, and emitted as canonical domain errors (`TranscriberQuotaExceededError`, `TranscriberRateLimitError`, `TranscriberConnectionError`, `TranscriberTimeoutError`) and `TranscriptEvent(ERROR)` events.

---

## 2. In-Flight Cancellation Mechanism

### Cancellation Lifecycle
Calling `await orchestrator.cancel(reason="...")` executes a coordinated 5-step clean shutdown:
1. **State Transition**: Safely transitions the orchestrator lifecycle from `RUNNING` or `STARTING` to `CANCELLED`.
2. **Ingestion Queue Draining**: Discards all buffered unread audio chunks from `_audio_queue`.
3. **Background Worker Cancellation**: Cancels the background audio processing task (`_audio_worker_task`) and awaits its termination.
4. **Provider Adapter Teardown**: Gracefully invokes `stop()` and detaches event listeners from the underlying provider adapter.
5. **Subscriber Queue Notification**: Pushes sentinel `None` to all active async generator queues (`orchestrator.stream()`), allowing consumer loops to exit immediately without hanging or throwing `asyncio.CancelledError`.

### Idempotency & Safety
- Calling `cancel()` repeatedly is idempotent and safe.
- Subsequent calls to `push_audio()` or `finish_audio()` raise typed `OrchestratorStateError` ("Cannot push audio in state 'cancelled'").
- `orchestrator.is_cancelled` and `orchestrator.is_closed` return `True`.

---

## 3. Automatic Mock Fallback Mechanism

### Eligibility Criteria
When a provider operation fails, `_is_fallback_eligible()` evaluates whether the failure qualifies for fallback:
- **Eligible Exception Types**:
  - `TranscriberQuotaExceededError` (account quota limit exhausted)
  - `TranscriberRateLimitError` (HTTP 429 / rate limit exceeded)
  - `TranscriberConnectionError` (socket drop, connection reset by peer, broken pipe)
  - `TranscriberTimeoutError` (connect deadline or chunk processing deadline exceeded)
  - `TranscriberServiceUnavailableError` (502 / 503 / 504 server outages)
  - `RetryExhaustedError` (all bounded exponential backoff retries failed)

### Fallback Execution Routine
1. **Normalized Downstream Notification**: Emits a `TranscriptEvent(ERROR)` with error code (`QUOTA_EXCEEDED`, `CONNECTION_FAILED`, etc.) and metadata `{"fallback_triggered": True, "fallback_provider": "FakeTranscriber"}`.
2. **Old Provider Detachment**: Detaches listeners from the failed primary adapter and stops it cleanly.
3. **Mock Provider Instantiation**: Instantiates a deterministic `FakeTranscriber` tied to the identical `session_id`, using `config.fallback_script`.
4. **Listener Re-binding & Startup**: Starts the fallback transcriber and wires events back into the reconciler and accumulator.
5. **Failed Chunk Replay**: Automatically pushes the chunk that triggered the failure to the new fallback provider so no speech is lost.
6. **Telemetry Update**: Increments `metrics.fallbacks_triggered += 1` and sets `metrics.is_fallback_active = True`.

---

## 4. Configuration Reference

### `OrchestratorConfig` Additions
| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `enable_mock_fallback` | `bool` | `True` | Automatically switch to `FakeTranscriber` when primary provider encounters quota or network failures. |
| `fallback_script` | `Optional[Union[str, List[str]]]` | `None` | Synthetic transcript text emitted if fallback is engaged. |

### `OrchestratorMetrics` Additions
| Metric | Type | Description |
| :--- | :--- | :--- |
| `cancellations_count` | `int` | Total cancellation requests processed. |
| `fallbacks_triggered` | `int` | Count of automatic fallbacks to mock provider. |
| `is_fallback_active` | `bool` | True if session is currently transcribing on the fallback provider. |

---

## 5. Usage Example

```python
import asyncio
from src.voice.orchestrator import TranscriptionOrchestrator, OrchestratorConfig

async def main():
    config = OrchestratorConfig(
        enable_mock_fallback=True,
        fallback_script="Backup transcript processed successfully.",
    )

    orchestrator = TranscriptionOrchestrator(
        session_id="session-prod-001",
        config=config,
    )

    await orchestrator.start()

    # Cancel if user hangs up early
    # await orchestrator.cancel(reason="Call hung up by user")

    # If primary provider encounters 429 quota exhaustion or connection drop,
    # orchestrator seamlessly falls back to FakeTranscriber!
```
