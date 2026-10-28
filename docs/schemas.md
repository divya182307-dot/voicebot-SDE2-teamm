# Speech-to-Text Data Contracts: Schemas & Event Specifications

This document defines the canonical schemas for the **Voice & Speech-to-Text (STT)** pipeline within the **Academia – AI Voice Co-Pilot** system.

---

## 1. Overview

In the streaming voice architecture, speech recognition generates continuous hypotheses before locking in final words. To ensure clean interoperability across all 6 subteams (Voice, Backend, Multimodal AI, Agent, Screen Vision, Desktop UI), all components adhere to these data models:

* **`WordTiming`**: Word-level token timestamp and confidence for precision UI highlighting.
* **`TranscriptSegment`**: Atomic transcribed speech utterance or phrase.
* **`TranscriptError`**: Standardized diagnostic error payload.
* **`TranscriptEventType`**: Lifecycle classification of stream events.
* **`TranscriptEvent`**: WebSocket / message bus streaming event packet.

---

## 2. Field Specifications

### 2.1 `TranscriptSegment`

Represents an atomic transcribed phrase or sentence.

| Field | Type | Units | Default | Constraints / Validation | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `id` | `string` | N/A | UUID4 | Non-empty string | Unique identifier for the segment. |
| `start_time_ms` | `integer` | Milliseconds (ms) | *Required* | $\ge 0$ | Start offset relative to audio onset. |
| `end_time_ms` | `integer` | Milliseconds (ms) | *Required* | $\ge \text{start\_time\_ms}$ | End offset relative to audio onset. |
| `text` | `string` | N/A | *Required* | Non-empty, non-whitespace | Transcribed speech text. |
| `confidence` | `float` | Probability | *Required* | $0.0 \le c \le 1.0$ | Normalized confidence score from recognizer. |
| `is_final` | `boolean` | N/A | `false` | Boolean | `false` for interim hypotheses; `true` when finalized. |
| `language` | `string` | BCP-47 / ISO | `"en"` | Pattern: `^[a-zA-Z]{2,3}(-[a-zA-Z0-9]+)?$` | Language code (e.g., `"en"`, `"en-US"`, `"es"`). |
| `words` | `list[WordTiming]` | N/A | `None` | Optional list of words | Sub-segment word-level timestamps. |

#### Derived Properties
* `duration_ms`: Computed dynamically as `end_time_ms - start_time_ms`.

---

### 2.2 `WordTiming`

Sub-segment word breakdown.

| Field | Type | Units | Constraints | Description |
| :--- | :--- | :--- | :--- | :--- |
| `word` | `string` | N/A | Min length: 1 | Spoken word token. |
| `start_time_ms` | `integer` | Milliseconds (ms) | $\ge 0$ | Start offset relative to audio onset. |
| `end_time_ms` | `integer` | Milliseconds (ms) | $\ge \text{start\_time\_ms}$ | End offset relative to audio onset. |
| `confidence` | `float` | Probability | $0.0 \le c \le 1.0$ | Token recognition confidence. |

---

### 2.3 `TranscriptEventType` (Enum)

| Enum Value | Wire String | Meaning | Payload Requirement |
| :--- | :--- | :--- | :--- |
| `SPEECH_STARTED` | `"speech_started"` | Voice activity detected (VAD onset). | Neither `segment` nor `error` allowed. |
| `INTERIM_TRANSCRIPT` | `"interim_transcript"` | Partial, speculative speech hypothesis. | Requires `segment` with `is_final=False`. |
| `FINAL_TRANSCRIPT` | `"final_transcript"` | Confirmed, finalized speech utterance. | Requires `segment` with `is_final=True`. |
| `SPEECH_ENDED` | `"speech_ended"` | User stopped speaking (turn boundary). | Neither `segment` nor `error` allowed. |
| `ERROR` | `"error"` | Speech recognition or network failure. | Requires `error` payload. |

---

### 2.4 `TranscriptError`

Standard error structure when `event_type == "error"`.

| Field | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `code` | `string` | Min length: 1 | Machine-readable error code (e.g. `AUDIO_TIMEOUT`, `RATE_LIMIT`). |
| `message` | `string` | Min length: 1 | Human-readable explanation. |
| `details` | `dict[str, Any]` | Optional | Extensible diagnostic context dictionary. |

---

### 2.5 `TranscriptEvent`

Canonical event envelope transmitted via WebSockets and internal message queues.

| Field | Type | Default | Constraints | Description |
| :--- | :--- | :--- | :--- | :--- |
| `event_id` | `string` | UUID4 | Non-empty | Globally unique event trace ID. |
| `session_id` | `string` | *Required* | Non-empty | Client interaction session ID. |
| `event_type` | `TranscriptEventType` | *Required* | Valid enum | Event type classification. |
| `timestamp` | `datetime` | UTC `now()` | ISO-8601 UTC | Timestamp of event generation. |
| `segment` | `TranscriptSegment` | `None` | Mandatory on `interim` / `final` | Segment payload. |
| `error` | `TranscriptError` | `None` | Mandatory on `error` | Error payload. |
| `sequence_number`| `integer` | `None` | $\ge 0$ | Stream ordering sequence index. |
| `metadata` | `dict[str, Any]` | `None` | Optional | Custom telemetry/provider data. |

---

## 3. Strict Validation & Invariant Rules

The models enforce strict validation rules. Payloads violating these rules are immediately rejected with descriptive `ValidationError` exceptions:

1. **Negative Timestamps**: Any `start_time_ms < 0` or `end_time_ms < 0` is rejected.
2. **Time Inversion**: If `end_time_ms < start_time_ms`, validation fails.
3. **Out-of-Bounds Confidence**: Values $< 0.0$ or $> 1.0$ fail validation.
4. **Blank Text**: Segments with empty strings or only whitespace are rejected.
5. **Payload Consistency Invariants**:
   * If `event_type == "final_transcript"`, `segment` must exist and have `is_final == True`.
   * If `event_type == "interim_transcript"`, `segment` must exist and have `is_final == False`.
   * If `event_type == "error"`, `error` must exist.
   * `speech_started` and `speech_ended` events are prohibited from carrying `error` payloads.
6. **No Extra Undeclared Fields**: Unknown fields (`extra="forbid"`) are strictly disallowed to prevent schema drift across team integrations.

---

## 4. Payload Examples

### A. Interim Transcript (Streaming Partial)
```json
{
  "event_id": "8a31e899-73e4-411a-a533-e18e38d4f409",
  "session_id": "session-101",
  "event_type": "interim_transcript",
  "timestamp": "2026-10-26T09:30:00.120000Z",
  "sequence_number": 3,
  "segment": {
    "id": "seg-001",
    "start_time_ms": 0,
    "end_time_ms": 950,
    "text": "why is this",
    "confidence": 0.82,
    "is_final": false,
    "language": "en"
  }
}
```

### B. Final Transcript (Committed Utterance)
```json
{
  "event_id": "c1f7b029-4d62-4841-860e-b9b5ea76f1c4",
  "session_id": "session-101",
  "event_type": "final_transcript",
  "timestamp": "2026-10-26T09:30:01.850000Z",
  "sequence_number": 4,
  "segment": {
    "id": "seg-001",
    "start_time_ms": 0,
    "end_time_ms": 1820,
    "text": "Why is this application failing?",
    "confidence": 0.97,
    "is_final": true,
    "language": "en-US",
    "words": [
      {"word": "Why", "start_time_ms": 0, "end_time_ms": 250, "confidence": 0.99},
      {"word": "is", "start_time_ms": 260, "end_time_ms": 400, "confidence": 0.98},
      {"word": "this", "start_time_ms": 410, "end_time_ms": 650, "confidence": 0.96},
      {"word": "application", "start_time_ms": 660, "end_time_ms": 1200, "confidence": 0.97},
      {"word": "failing", "start_time_ms": 1210, "end_time_ms": 1820, "confidence": 0.98}
    ]
  }
}
```

### C. Error Event
```json
{
  "event_id": "e98e21a2-5b92-4217-9877-c99e1d88231c",
  "session_id": "session-101",
  "event_type": "error",
  "timestamp": "2026-10-26T09:30:05.000000Z",
  "error": {
    "code": "MICROPHONE_STREAM_DISCONNECTED",
    "message": "Input audio buffer underrun or microphone disconnected.",
    "details": {
      "device_index": 1,
      "buffer_size_bytes": 0
    }
  }
}
```

---

## 5. Team Consumption Guide

* **Backend Gateway (`/api/v1/voice/transcribe`)**: Validate incoming multipart audio or stream responses against `TranscriptEvent.model_dump_json()`.
* **Desktop UI Team**: Bind the visual speech bubble state directly to `event_type`:
  * If `interim_transcript`: Update speculative text in gray/italic font.
  * If `final_transcript`: Lock text into the chat transcript in permanent font.
  * If `error`: Display toast or error pill with `error.message`.
* **Multimodal AI & Agent**: Once `FINAL_TRANSCRIPT` or `SPEECH_ENDED` is received, pass the accumulated `segment.text` to the reasoning prompt.
