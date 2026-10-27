# SDE-2 Voicebot - Week 1 Deliverables (Days 2 & 3)

**Academia - AI Voice Co-Pilot**  
**Track:** SDE-2 Voicebot (`projects/sde-2-voicebot/`)  
**Phase:** Week 1 — Foundation (Day 2 & Day 3 Deliverables)

---

## Deliverables Summary

### 1. Synthetic Frames with Screen Capture Disabled by Default (Day 2)
- **Module:** `app.vision.synthetic_frames`
- **Class:** `ScreenCaptureManager`
- **Privacy Enforcement:** Screen capture is strictly **disabled by default** (`is_capture_enabled = False`), adhering to PRD NG3 and Section 19 Privacy requirements. Attempting to capture without explicit consent raises `ScreenCaptureDisabledException`.
- **Scenarios Supported:**
  - `CODE_EDITOR_ERROR`: VS Code active window with traceback (UC-02).
  - `RESEARCH_PAPER_PDF`: PDF viewer with academic methodology excerpt (UC-03).
  - `SPREADSHEET_ANALYSIS`: Tabular quarterly sales data and trends (UC-04).
  - `FILE_EXPLORER`: Downloads directory with file metadata (UC-06, UC-08).
  - `REDACTED_PRIVACY`: PII/secret masking demonstration (`contains_sensitive_data = True`).
- **Authorization Lifecycles:** Supports explicit `enable_capture()` / `disable_capture()` and scoped context management via `with manager.authorized_session(): ...`.

### 2. Deterministic Mock Reasoning Engine (Day 2)
- **Module:** `app.reasoning.mock_engine`
- **Class:** `DeterministicMockReasoningEngine`
- **Consistency Guarantee:** Generates 100% reproducible outputs for identical `ReasoningRequest` payloads using deterministic input digest hashing.
- **Scenarios Handled:**
  - UC-01: Screen content description (Category A: Informational).
  - UC-02: Error explanation and resolution guidance (Category A: Informational).
  - UC-03: Document section summarization (Category A: Informational).
  - UC-04: Tabular trend analysis (Category A: Informational).
  - UC-08: File organization action plan (Category C: Sensitive, requires user approval).
  - High-Risk / Destructive: Permanent deletion (Category D: High-Risk/Destructive, strict approval gate).
  - General assistance fallback: Deterministic seed-based response.

### 3. Versioned Prompts with Trusted / Untrusted Isolation (Day 2)
- **Modules:** `app.prompts.models`, `app.prompts.registry`
- **Classes:** `VersionedPrompt`, `RenderedPrompt`, `PromptRegistry`
- **Security Boundary:**
  - **Trusted Developer Directives:** Placed in system instructions with operational rules and security guardrails.
  - **Untrusted User & Screen Data:** Encapsulated in explicit delimiters (`<untrusted_user_input>`, `<untrusted_screen_context>`, `<untrusted_retrieved_context>`).
  - **Injection Sanitization:** Neutralizes attempts to inject closing delimiter tags to prevent prompt breakouts.
- **Versions Registered:**
  - `multimodal_co_pilot:1.0.0`: Baseline prompt.
  - `multimodal_co_pilot:1.1.0`: Hardened prompt with injection defense.
  - `agent_orchestrator:1.0.0`: Multi-step tool planning prompt.

### 4. Reasoning Request & Result Validation Suite (Day 3)
- **Module:** `app.schemas.reasoning`
- **Test File:** `tests/test_reasoning_validation.py` (33 unit tests)
- **Classes:** `ReasoningRequest`, `ReasoningResult`, `ActionStep`
- **Coverage:**
  1. **Valid Inputs (PRD Sec 16, 18):**
     - Minimal valid voice reasoning requests.
     - Multimodal requests with authorized `ScreenContext`.
     - Multimodal requests with visual `ContextItem` units (`screen_ocr`, `visual_summary`).
     - Request boundary values (`max_tokens`, `temperature`, query length, history turns).
     - Informational (Category A) direct responses without approval prompt.
     - Sensitive (Category C) agentic plans with user approval flags and confirmation prompts.
     - Destructive (Category D) operations with mandatory human-in-the-loop approval.
  2. **Invalid Inputs (PRD Sec 18, 24; SDD Sec 6):**
     - Empty or whitespace-only identifiers (`request_id`, `session_id`, `user_query`, `response_id`, `user_intent`).
     - Length over-bounds (ID > 64 chars, query > 4000 chars, description > 500 chars).
     - Value bounds: `temperature` out of [0.0, 2.0], `max_tokens` out of [64, 8192], `confidence_score` out of [0.0, 1.0], negative `processing_time_ms`.
     - Multimodal requests missing visual context (no screen and no visual items).
     - Malformed conversation history (missing role/content, invalid role, empty content, > 30 turns).
     - Tool name regex pattern violations (must be alphanumeric, underscores, hyphens).
     - Business logic violations: `tool_call_required=True` with empty `action_plan`, or `tool_call_required=False` with populated `action_plan`.
     - Non-sequential `ActionStep` numbering (must be contiguous 1-based: 1, 2, 3...).
     - Risk level inconsistency (overall risk level cannot be lower than the highest risk level among individual action steps).
     - Sensitive / Destructive operations with `requires_user_approval=False` or missing `approval_prompt`.
     - Category A informational responses with `requires_user_approval=True` or unexpected `approval_prompt`.
  3. **Edge Cases:**
     - Automatic whitespace trimming across all string identifiers and queries.
     - Whitespace-only approval prompt coerced safely to `None` for informational responses.
     - Boundary length checks: prompt at exactly 500 characters valid, 501 characters rejected.
     - Confidence score boundaries: exactly 0.0 and 1.0 valid.

---

## Running Tests

From `projects/sde-2-voicebot/`:

```powershell
python tests/run_tests.py
```

### Test Suite Summary (50/50 Tests Passing):
- **Task 1: Synthetic Frames & Privacy:** 7 tests PASSED
- **Task 2: Deterministic Mock Reasoning:** 5 tests PASSED
- **Task 3: Versioned Prompts & Injection Defense:** 4 tests PASSED
- **Task 4: Complete End-to-End Integration:** 1 test PASSED
- **Task 5: Reasoning Request & Result Validation Suite (Day 3):** 33 tests PASSED
- **Total:** **50 / 50 PASSED (100% Success)**
