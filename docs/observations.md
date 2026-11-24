# Observation Capture, Processing & Retention

This document summarizes **what data the system captures**, how it is processed, and what is retained in memory.

## Captured Signals
| Signal Type | Source | Example | Retention Policy |
|-------------|--------|---------|------------------|
| Screen frame | `app.vision.capture_adapter` (WebRTC / OS screenshot) | Image bitmap, OCR text, visual element summary | Stored in `ObservationManager._cached_frames` for the lifetime of the process (default TTL 30 s for freshness). |
| Context items | `app.context.builder` (files, terminal output, document snippets) | `ContextItem` objects containing raw text and metadata | Stored as `Observation` objects in `ObservationManager._active_observations` until consent is withdrawn or the manager is reset. |
| Voice utterance | `app.vision.voice_adapter` (speech‑to‑text) | Transcribed query string | Stored as an `Observation` with source type `AUDIO_VOICE`. |
| Prompt version | Internal API | String identifier supplied by the caller (e.g., `v1.2‑20231119`) | Recorded in `ObservationManager._current_prompt_version` and attached to each new `Observation` via the `metadata` dictionary. |

## Processing Steps
1. **Consent verification** – `ObservationManager._verify_consent_before_ingestion()` ensures the user has opted‑in. If consent is withdrawn, all buffers are purged.
2. **Frame hashing & deduplication** – SHA‑256 hash of frame content + geometry. Duplicate detection increments `self._duplicate_frames_detected`.
3. **Staleness checking** – Frames older than `freshness_ttl_seconds` are marked as stale (`is_stale=True`) and counted.
4. **Source linking** – Each `Observation` receives a `SourceReference` containing:
   - `source_id` (e.g., `src-frame-…`)
   - `source_type` (SCREEN, DOCUMENT, AUDIO_VOICE)
   - Application/window identifiers, bounding box, timestamp.
5. **Grounding** – `GroundedAnswer` objects reference the observations that provide evidence, exposing `sources_cited` and `evidence_observations`.
6. **Latency instrumentation** – The manager records ingestion latency (ms) in `self._ingest_latency_ms`. This can be extended to expose metrics via an endpoint.

## Retention & Privacy
* All in‑memory buffers are **cleared** when `withdraw_consent()` is called – this satisfies the *redaction* requirement.
* Observations are **not persisted** to disk by default; they live only for the process lifetime.
* `has_evidence` flag signals whether an observation contains verifiable content; if `False`, the downstream answer will emit a “no evidence” reply.
* Prompt version strings are **not logged**; they are stored only in the observation metadata for debugging/audit.

## API for Prompt Version Tracking
```python
# Caller can set the current prompt version before ingestion
obs_manager.set_prompt_version("v1.2‑20231119")

# The version is automatically added to each Observation's metadata:
# {"prompt_version": "v1.2‑20231119"}
```

---
*Generated on 2026‑11‑24.*
