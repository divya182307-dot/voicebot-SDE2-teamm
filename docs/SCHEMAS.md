# Data Contracts & Schemas Documentation

**Product:** Academia - AI Voice Co-Pilot  
**Phase:** Week 1 — Product Foundation (Day 1 Architecture & Contracts)  
**References:** 
- `01. Product Requirements Document (PRD)` (Sections 14, 15, 16, 17, 18, 20)
- `02. System Design Document (SDD)` (Sections 4.3, 4.4, 5, 6, Safety Layer)
- `03. Technical Architecture & Design` (Sections 1, 2, 4, 5, 6)

---

## 1. Schema Overview

The AI Voice Co-Pilot operates under a multi-modal agentic loop:  
$$\text{Observe} \rightarrow \text{Understand} \rightarrow \text{Reason} \rightarrow \text{Plan} \rightarrow \text{Act} \rightarrow \text{Verify} \rightarrow \text{Respond}$$

To ensure strict boundaries across the 8 engineering sub-teams, communication occurs across five core schemas:
1. **`SourceReference`**: Tracks provenance and attribution across all inputs (screen, files, documents, terminal).
2. **`ScreenContext`**: Standardizes visual and OCR captures of the user's active workspace under strict privacy boundaries.
3. **`ContextItem`**: Represents an atomic unit of context assembled by the Context Engine before delivery to the Multimodal AI.
4. **`ReasoningRequest`**: Packages user input (voice/text), active screen context, aggregated context items, and permitted tools for the AI reasoning layer.
5. **`ReasoningResult`**: Outputs structured decisions from the Multimodal AI and Agent Orchestrator, including text responses, tool execution plans, risk levels, and human-in-the-loop approval gates.

---

## 2. Detailed Schema Specifications

### 2.1 `SourceReference`
Tracks the exact origin of contextual information to support Explainability (PRD 10.5) and Groundedness.

| Field Name | Type | Units | Constraints | Description |
| :--- | :--- | :--- | :--- | :--- |
| `source_id` | `string` | Dimensionless ID | Required, $1 \le \text{length} \le 64$ | Unique identifier for the source item (e.g., UUIDv4). |
| `source_type` | `SourceType` (Enum) | Categorical | Required, one of: `screen`, `active_window`, `document`, `audio_voice`, `terminal`, `application_state`, `browser`, `retrieved_knowledge`, `conversation_history` | The originating medium or modality of the information. |
| `application_name` | `string` (Optional) | Application ID | Optional, $\text{length} \le 255$, Default: `None` | Name of the application hosting the source content (e.g. `'VS Code'`, `'Adobe Acrobat'`). |
| `window_title` | `string` (Optional) | Text String | Optional, $\text{length} \le 500$, Default: `None` | Title of the active OS window or document tab. |
| `document_uri` | `string` (Optional) | RFC 3986 URI / Path | Optional, $\text{length} \le 2048$, Default: `None` | URI or absolute local path to the file or document. |
| `page_number` | `integer` (Optional) | Pages (Count) | Optional, $\ge 1$, Default: `None` | 1-based page index if referencing a paginated document (PDF, presentation). |
| `line_number` | `integer` (Optional) | Lines (Count) | Optional, $\ge 1$, Default: `None` | 1-based line number for code or plain text files. |
| `bounding_box` | `BoundingBox` (Optional) | Pixels / Ratio | Optional, Default: `None` | Spatial boundary on screen/document where element resides. |
| `timestamp` | `datetime` | UTC ISO 8601 | Required, default UTC now | Exact timestamp when the reference was created. |

---

### 2.2 `ScreenContext`
Captures authorized visual context and OCR text from the user's workspace (PRD Section 14, FR-VISION-001..006).

| Field Name | Type | Units | Constraints | Description |
| :--- | :--- | :--- | :--- | :--- |
| `capture_id` | `string` | Dimensionless ID | Required, $1 \le \text{length} \le 64$ | Unique capture event identifier (UUIDv4). |
| `timestamp` | `datetime` | UTC ISO 8601 | Required, default UTC now | Capture timestamp. |
| `capture_mode` | `CaptureMode` (Enum) | Categorical | Required, one of: `fullscreen`, `active_window`, `region`, `selection`. Default: `active_window` | Boundary scope of the capture, adhering to data minimization. |
| `application_name` | `string` (Optional) | Application ID | Optional, $\text{length} \le 255$, Default: `None` | Application corresponding to the captured window/region. |
| `window_title` | `string` (Optional) | Text String | Optional, $\text{length} \le 500$, Default: `None` | Window title of the captured window. |
| `width` | `integer` | Pixels (`px`) | Required, $1 \le \text{width} \le 16384$ | Horizontal resolution of the captured area. |
| `height` | `integer` | Pixels (`px`) | Required, $1 \le \text{height} \le 16384$ | Vertical resolution of the captured area. |
| `dpi_scale` | `float` | Scale Factor | Required, $0.5 \le \text{dpi\_scale} \le 5.0$, Default: `1.0` | OS DPI display scaling factor (e.g. 1.0, 1.25, 2.0). |
| `bounding_box` | `BoundingBox` (Optional) | Pixels (`px`) | Optional, Default: `None` | Coordinates of active region within the monitor workspace. |
| `image_format` | `string` | MIME type | Required, matches regex: `^(image/png\|image/jpeg\|image/webp)$`, Default: `image/webp` | Encoding format of the visual snapshot. |
| `image_base64` | `string` (Optional) | Encoded Bytes | Optional, $\text{length} \le 10,000,000$ (max ~10 MB payload), Default: `None` | Base64-encoded visual frame passed to vision model. |
| `ocr_text` | `string` (Optional) | Characters | Optional, $\text{length} \le 100,000$, Default: `None` | Text extracted via OCR from the captured area (FR-VISION-003). |
| `ocr_confidence` | `float` (Optional) | Probability Score | Optional, $0.0 \le \text{ocr\_confidence} \le 1.0$, Default: `None` | Average confidence score of the OCR engine. |
| `contains_sensitive_data` | `boolean` | Boolean flag | Required, Default: `False` | Privacy flag indicating PII/credential detection (PRD Section 19). |

---

### 2.3 `ContextItem`
Standardized knowledge atom curated by the Context Engine (SDD Section 4.4, Tech Arch Section 5).

| Field Name | Type | Units | Constraints | Description |
| :--- | :--- | :--- | :--- | :--- |
| `item_id` | `string` | Dimensionless ID | Required, $1 \le \text{length} \le 64$ | Unique identifier (UUIDv4) for this context element. |
| `context_type` | `ContextType` (Enum) | Categorical | Required, one of: `user_query`, `screen_ocr`, `visual_summary`, `application_metadata`, `document_excerpt`, `terminal_output`, `code_snippet`, `dialogue_history`, `retrieved_doc` | Classification category of the context item. |
| `title` | `string` | Text String | Required, $1 \le \text{length} \le 120$ | Short header/label for the context item. |
| `content` | `string` | Text Characters | Required, $1 \le \text{length} \le 250,000$ | Cleaned textual content/payload. |
| `metadata` | `dict[str, Any]` | Key-Value pairs | Optional, Default: `{}` | Domain-specific metadata (file extension, process PID, error code). |
| `source` | `SourceReference` (Optional) | Object | Optional, Default: `None` | Provenance link to the source origin. |
| `relevance_score` | `float` | Normalized Score | Required, $0.0 \le \text{relevance\_score} \le 1.0$, Default: `1.0` | Relevance score computed by Context Engine for filtering noise. |
| `token_count` | `integer` (Optional) | Tokens (Count) | Optional, $\ge 0$, Default: `None` | Token count of the content used for LLM context budget management. |
| `timestamp` | `datetime` | UTC ISO 8601 | Required, default UTC now | Ingestion/creation timestamp. |

---

### 2.4 `ReasoningRequest`
Input payload submitted to the Multimodal AI Layer (PRD Section 16, SDD Section 5, Tech Arch Section 6).

| Field Name | Type | Units | Constraints | Description |
| :--- | :--- | :--- | :--- | :--- |
| `request_id` | `string` | Dimensionless ID | Required, $1 \le \text{length} \le 64$ | Unique request identifier (UUIDv4). |
| `session_id` | `string` | Dimensionless ID | Required, $1 \le \text{length} \le 64$ | Dialogue session identifier. |
| `user_query` | `string` | Text Characters | Required, $1 \le \text{length} \le 4000$ | Transcribed user voice query or prompt. |
| `modality` | `InputModality` (Enum) | Categorical | Required, one of: `voice`, `text`, `multimodal`. Default: `voice` | Originating modality of the input. |
| `screen_context` | `ScreenContext` (Optional) | Object | Optional, Default: `None` | Captured visual and OCR context snapshot. |
| `context_items` | `list[ContextItem]` | Array of Objects | Optional, $\text{count} \le 50$, Default: `[]` | Ranked context items curated by Context Engine. |
| `conversation_history` | `list[dict[str, str]]` | Message Array | Optional, $\text{count} \le 30$, Default: `[]` | Recent dialogue turns `[{"role": "user"|"assistant", "content": "..."}]`. |
| `available_tools` | `list[str]` | Tool Identifiers | Optional, Default: `[]` | List of authorized tools available for agent execution. |
| `allow_agentic_planning`| `boolean` | Boolean flag | Required, Default: `True` | Flag permitting multi-step agent planning vs single direct answer. |
| `max_tokens` | `integer` | Tokens (Count) | Required, $64 \le \text{max\_tokens} \le 8192$, Default: `1024` | Ceiling on LLM generation token budget. |
| `temperature` | `float` | Scalar Factor | Required, $0.0 \le \text{temperature} \le 2.0$, Default: `0.2` | Sampling temperature for LLM generation. |
| `stream_response` | `boolean` | Boolean flag | Required, Default: `False` | Whether response tokens should stream via WebSocket. |
| `timestamp` | `datetime` | UTC ISO 8601 | Required, default UTC now | Request timestamp. |

---

### 2.5 `ReasoningResult`
Output produced by the Multimodal AI Layer & Agent Orchestrator (PRD Section 16 & 18, SDD Section 6, Tech Arch Section 6 & 7).

| Field Name | Type | Units | Constraints | Description |
| :--- | :--- | :--- | :--- | :--- |
| `response_id` | `string` | Dimensionless ID | Required, $1 \le \text{length} \le 64$ | Unique response identifier (UUIDv4). |
| `request_id` | `string` | Dimensionless ID | Required, $1 \le \text{length} \le 64$ | Correlating request identifier. |
| `session_id` | `string` | Dimensionless ID | Required, $1 \le \text{length} \le 64$ | Dialogue session identifier. |
| `user_intent` | `string` | Intent Identifier | Required, $1 \le \text{length} \le 100$ | Classified intent (e.g. `'explain_error'`, `'summarize_document'`). |
| `response_text` | `string` | Text Characters | Required | Natural language text delivered to user via TTS (FR-VOICE-005) & UI. |
| `reasoning_summary` | `string` (Optional) | Text Characters | Optional, Default: `None` | High-level rationale explaining derived plan or answer (Explainability). |
| `tool_call_required` | `boolean` | Boolean flag | Required, Default: `False` | True if multi-step agent tool execution is required. |
| `action_plan` | `list[ActionStep]` | Array of Objects | Optional, Default: `[]` | Multi-step tool execution sequence (SDD Section 6). |
| `risk_level` | `RiskLevel` (Enum) | Categorical | Required, one of: `category_a_informational`, `category_b_low_risk`, `category_c_sensitive`, `category_d_high_risk_destructive`. Default: `category_a_informational` | Highest risk classification for the proposed action (PRD Section 18). |
| `requires_user_approval`| `boolean` | Boolean flag | Required, Default: `False` | Flag indicating whether explicit human approval is needed prior to tool execution. |
| `approval_prompt` | `string` (Optional) | Text Characters | Optional, $\text{length} \le 500$, Default: `None` | Prompt presented to user for confirmation (e.g., `'Shall I rename the file?'`). |
| `sources_used` | `list[SourceReference]` | Array of Objects | Optional, Default: `[]` | Provenance citations backing the response. |
| `confidence_score` | `float` | Probability Score | Required, $0.0 \le \text{confidence\_score} \le 1.0$ | Model confidence score in its intent determination and answer. |
| `processing_time_ms` | `float` | Milliseconds (`ms`) | Required, $\ge 0.0$ | Total latency for context curation, reasoning, and plan generation. |
| `status` | `ExecutionStatus` (Enum) | Categorical | Required, one of: `success`, `requires_clarification`, `needs_approval`, `execution_in_progress`, `failed`. Default: `success` | Current execution status. |
| `timestamp` | `datetime` | UTC ISO 8601 | Required, default UTC now | Response timestamp. |

---

## 3. Supporting Models & Enums

### 3.1 `ActionStep`
Represents an individual step in a planned agentic workflow.
- `step_number`: `integer`, $\ge 1$, 1-based ordinal step number.
- `tool_name`: `string`, $1 \le \text{length} \le 100$, target registered tool ID.
- `tool_parameters`: `dict[str, Any]`, parameter inputs for tool invocation.
- `step_description`: `string`, $1 \le \text{length} \le 500$, human-readable description of what will be done.
- `risk_level`: `RiskLevel` (Enum), Category A, B, C, or D.
- `requires_approval`: `boolean`, whether this specific action requires explicit approval.

### 3.2 `BoundingBox`
Represents 2D visual boundaries.
- `x_min`: `float`, $\ge 0.0$, units: pixels (`px`) or normalized $[0.0, 1.0]$.
- `y_min`: `float`, $\ge 0.0$, units: pixels (`px`) or normalized $[0.0, 1.0]$.
- `x_max`: `float`, $\ge \text{x\_min}$, units: pixels (`px`) or normalized $[0.0, 1.0]$.
- `y_max`: `float`, $\ge \text{y\_min}$, units: pixels (`px`) or normalized $[0.0, 1.0]$.
- `is_normalized`: `boolean`, indicates coordinate scale.

### 3.3 Risk Classification Matrix (PRD Section 18)
| Level | Category Name | Description | User Approval Required |
| :--- | :--- | :--- | :--- |
| **A** | `category_a_informational` | Explanations, answering questions, summarization | **No** (Direct response) |
| **B** | `category_b_low_risk` | Search information, open permitted document | **Configurable Policy** |
| **C** | `category_c_sensitive` | Modifying files, sending emails, changing settings | **Yes** (Explicit approval) |
| **D** | `category_d_high_risk_destructive` | Deleting files, privileged system execution, financial | **Yes** (Strict explicit confirmation) |
