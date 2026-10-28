# voicebot-week1-teamm
AI Voice Co-Pilot - Team Project

## Academia – AI Voice Co-Pilot: SDE-2 Voicebot Engine

This module forms the reasoning, multimodal synthetic vision, prompt orchestration, and schema validation foundation of **Academia – AI Voice Co-Pilot**. It is designed to process multimodal user interactions (voice, text, and screen context), isolate untrusted inputs with security guardrails, generate deterministic mock grounded responses, and enforce strict human-in-the-loop safety gates.

---

### 📁 Repository Structure

```text
voicebot-SDE2-teamm/
├── app/
│   ├── __init__.py
│   ├── main.py                         # Live FastAPI backend & interactive web application
│   ├── prompts/
│   │   ├── __init__.py
│   │   ├── models.py                   # VersionedPrompt & RenderedPrompt definitions
│   │   └── registry.py                 # PromptRegistry & registered prompt versions
│   ├── reasoning/
│   │   ├── __init__.py
│   │   └── mock_engine.py              # Deterministic mock reasoning engine (PRD Categories A-D)
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── common.py                   # Enums (RiskLevel, SourceType, ContextType, InputModality)
│   │   ├── context.py                  # ScreenContext, ContextItem, SourceReference schemas
│   │   └── reasoning.py                # ReasoningRequest, ReasoningResult, ActionStep schemas
│   └── vision/
│       ├── __init__.py
│       └── synthetic_frames.py         # ScreenCaptureManager with privacy enforcement
├── results/
│   ├── day2_interactive_demo.jpg       # Visual snapshot of interactive CLI demo
│   ├── day2_test_results.jpg           # Visual snapshot of automated test suite
│   ├── test_server.ps1                 # Endpoint smoke test script
│   └── view_results.html               # Interactive deliverables viewer & scorecard
├── tests/
│   ├── __init__.py
│   ├── conftest.py                     # Pytest fixtures and mock test setups
│   ├── run_tests.py                    # Standalone test runner (50/50 passing tests)
│   ├── test_day2_integration.py        # Complete end-to-end integration test
│   ├── test_mock_reasoning.py          # Deterministic reasoning & safety tests (5 tests)
│   ├── test_reasoning_validation.py    # Request & result validation test suite (33 tests)
│   ├── test_synthetic_frames.py        # Privacy & synthetic capture tests (7 tests)
│   └── test_versioned_prompts.py       # Prompt isolation & injection defense tests (4 tests)
├── .gitignore                          # Python cache and temporary file exclusions
├── demo.py                             # Day 7 demonstration script (grounded response demo)
├── demo_day2.py                        # Interactive terminal demonstration script
├── README.md                           # Comprehensive Day 1–7 project documentation
└── run_server.py                       # Server runner for live execution engine
```

---

### 🚀 Day-wise Implementation Plan & Deliverables

#### 📅 Day 1–2: Define Schemas

Defined and documented the core data contracts in `app/schemas/`:

1. **`ScreenContext` (`app/schemas/context.py`)**:
   - `capture_id` (`str` [1–64 chars]): Unique capture identifier (UUIDv4).
   - `timestamp` (`datetime` [UTC ISO 8601]): Timestamp when screen capture was performed.
   - `application_name` (`Optional[str]` [max 255 chars]): Active OS application (e.g. `'VS Code'`, `'Chrome'`).
   - `window_title` (`Optional[str]` [max 500 chars]): Title of active window or document tab.
   - `width` / `height` (`int` [1–7680px / 1–4320px]): Pixel resolution dimensions.
   - `ocr_text` (`Optional[str]` [max 50,000 chars]): Text extracted via optical character recognition.
   - `visual_elements_summary` (`Optional[str]` [max 10,000 chars]): High-level semantic summary of visible UI widgets and content.
   - `contains_sensitive_data` (`bool`): Privacy flag indicating presence of PII or secrets.
   - `capture_mode` (`CaptureMode` Enum): Mode used (`full_screen`, `active_window`, `region_selection`, `synthetic`).

2. **`ContextItem` (`app/schemas/context.py`)**:
   - `item_id` (`str` [1–64 chars]): Unique context item identifier.
   - `context_type` (`ContextType` Enum): Context modality (`user_query`, `screen_ocr`, `visual_summary`, `application_metadata`, `document_excerpt`, `terminal_output`, `code_snippet`).
   - `content` (`str` [1–50,000 chars]): Text payload or serialized structured data.
   - `priority` (`int` [0–10]): Weighting priority (default `5`).
   - `timestamp` (`datetime` [UTC ISO 8601]): Timestamp when item was ingested.
   - `source` (`Optional[SourceReference]`): Attribution and provenance details.

3. **`SourceReference` (`app/schemas/context.py`)**:
   - `source_id` (`str` [1–64 chars]): Provenance tracker ID.
   - `source_type` (`SourceType` Enum): Origin modality (`screen`, `active_window`, `document`, `audio_voice`, `terminal`, `browser`).
   - `application_name` (`Optional[str]` [max 255 chars]): Host application name.
   - `window_title` (`Optional[str]` [max 500 chars]): Title of the active OS window.
   - `document_uri` (`Optional[str]` [max 2048 chars]): URI or local file path to source resource.
   - `page_number` (`Optional[int]` [>= 1]): 1-based page index for paginated documents.
   - `line_number` (`Optional[int]` [>= 1]): 1-based line number for code or text files.
   - `bounding_box` (`Optional[BoundingBox]`): Pixel / normalized spatial coordinates (`[x_min, y_min, x_max, y_max]`).
   - `timestamp` (`datetime` [UTC ISO 8601]): Timestamp of provenance recording.

4. **`ReasoningRequest` (`app/schemas/reasoning.py`)**:
   - `request_id` (`str` [1–64 chars]): Unique client request ID.
   - `session_id` (`str` [1–64 chars]): Active session identifier.
   - `user_query` (`str` [1–4,000 chars]): Transcribed voice utterance or query.
   - `modality` (`InputModality` Enum): Input modality (`voice`, `text`, `multimodal`).
   - `screen_context` (`Optional[ScreenContext]`): Visual context captured from user screen.
   - `context_items` (`List[ContextItem]`): Auxiliary context items.
   - `conversation_history` (`List[Dict[str, Any]]` [max 30 items]): Multi-turn dialogue history.
   - `available_tools` (`List[str]` [pattern `^[a-zA-Z0-9_-]+$`]): Registered tools available for planning.
   - `temperature` (`float` [0.0–2.0]): LLM sampling temperature (default `0.2`).
   - `max_tokens` (`int` [64–8,192]): Maximum generated tokens (default `1024`).

5. **`ReasoningResult` (`app/schemas/reasoning.py`)**:
   - `response_id` (`str` [1–64 chars]): Unique response identifier.
   - `request_id` (`str` [1–64 chars]): Correlating request identifier.
   - `user_intent` (`str` [1–255 chars]): Synthesized user intent.
   - `agent_response_text` (`str` [>= 1 char]): Spoken or displayed response.
   - `confidence_score` (`float` [0.0–1.0]): Model confidence score.
   - `risk_level` (`RiskLevel` Enum): Risk classification (`category_a_informational`, `category_b_low_risk`, `category_c_sensitive`, `category_d_high_risk_destructive`).
   - `requires_user_approval` (`bool`): Mandatory approval gate flag.
   - `approval_prompt` (`Optional[str]` [max 500 chars]): Spoken prompt presented to user when approval is required.
   - `tool_call_required` (`bool`): Flag indicating action plan presence.
   - `action_plan` (`List[ActionStep]`): Sequential 1-based action step sequence.
   - `sources_cited` (`List[SourceReference]`): Attribution sources cited in response.
   - `execution_status` (`ExecutionStatus` Enum): Execution status (`completed`, `needs_approval`, `rejected`, `failed`).
   - `processing_time_ms` (`float` [>= 0.0]): Processing latency in milliseconds.

---

#### 📅 Day 3–4: Synthetic Frames, Mock Reasoning, Prompts

1. **Synthetic Frames with Privacy Enforcement (`app/vision/synthetic_frames.py`)**:
   - **Capture Disabled by Default:** `is_capture_enabled = False` upon initialization, strictly enforcing PRD NG3 and Section 19 Privacy constraints.
   - **Privacy Protection:** Attempting capture without consent raises `ScreenCaptureDisabledException`.
   - **Fallback Safe Placeholder:** Supports `allow_fallback_when_disabled=True` returning zero image bytes (`image_base64 = ""`) with zero data leakage.
   - **Scoped Authorization:** Context manager `with manager.authorized_session(): ...` automatically enables capture for the scope and revokes access immediately upon exit.
   - **Scenarios Supported:** `CODE_EDITOR_ERROR`, `RESEARCH_PAPER_PDF`, `SPREADSHEET_ANALYSIS`, `FILE_EXPLORER`, `REDACTED_PRIVACY`.

2. **Deterministic Mock Reasoning Engine (`app/reasoning/mock_engine.py`)**:
   - **100% Deterministic Guarantee:** Computes SHA-256 digest over query, modality, application, window title, OCR, and context items to guarantee identical outputs for identical inputs.
   - **Safety Categories & Human-in-the-Loop Approval:**
     - **Category A (Informational):** Code error explanations (UC-02), document summaries (UC-03), and spreadsheet trends (UC-04). Delivered directly with `requires_user_approval = False`.
     - **Category C (Sensitive):** Multi-step file management plans (UC-08) requiring explicit user confirmation with `requires_user_approval = True` and a confirmation `approval_prompt`.
     - **Category D (High-Risk/Destructive):** Permanent file deletion operations requiring strict approval gates.
     - **Deterministic General Fallback:** Deterministic seed-based response for general queries.

3. **Versioned Prompts with Trusted / Untrusted Isolation (`app/prompts/`)**:
   - **Security Boundary:** Trusted developer directives placed in system instructions; untrusted user queries and screen data wrapped in explicit delimiters (`<untrusted_user_input>`, `<untrusted_screen_context>`, `<untrusted_retrieved_context>`).
   - **Injection Defense:** Automatically detects and sanitizes attempts to inject closing delimiter tags to prevent prompt breakouts.
   - **Registry Versions:**
     - `multimodal_co_pilot:1.0.0`: Baseline prompt template.
     - `multimodal_co_pilot:1.1.0`: Hardened prompt with delimiter injection defense.
     - `agent_orchestrator:1.0.0`: Tool planning template for multi-step tasks.

---

#### 📅 Day 5–6: Validation and Unit Tests

1. **Request & Result Schema Validation (`app/schemas/reasoning.py`)**:
   - Implemented Pydantic v2 model validators enforcing:
     - ID string length boundaries and automatic whitespace trimming.
     - Numeric ranges: `temperature` in `[0.0, 2.0]`, `max_tokens` in `[64, 8192]`, `confidence_score` in `[0.0, 1.0]`.
     - Regex tool identifier syntax (`^[a-zA-Z0-9_-]+$`).
     - Multimodal visual context enforcement (multimodal requests require `screen_context` or visual `context_items`).
     - Contiguous 1-based sequential step numbering (`1, 2, 3...`).
     - Safety consistency: Category C/D operations require `requires_user_approval=True` and `approval_prompt`, while Category A operations prohibit approval prompts.
     - Risk-level hierarchy: Overall risk cannot be lower than the highest risk level among individual steps.

2. **Automated Unit Test Suite (`tests/`)**:
   - Complete coverage across valid inputs, invalid boundaries, business rules, and edge cases.
   - **50 / 50 Tests Passing (100% Success Rate):**
     - `tests/test_reasoning_validation.py`: **33 unit tests** (valid payloads, boundary limits, invalid IDs/queries, missing visual context, tool regex violations, step order violations, safety gate mismatches).
     - `tests/test_synthetic_frames.py`: **7 unit tests** (privacy default, disabled exceptions, fallback placeholders, scoped sessions, scenario generation).
     - `tests/test_mock_reasoning.py`: **5 unit tests** (determinism guarantee, error grounding, document summarization, Category C/D approval gates).
     - `tests/test_versioned_prompts.py`: **4 unit tests** (registry retrieval, delimiter isolation, prompt injection neutralization).
     - `tests/test_day2_integration.py`: **1 end-to-end integration test** (complete pipeline).

---

#### 📅 Day 7: Pull Request and Demonstration

1. **Demonstrate a Request Producing a Mock Grounded Response:**
   - Run the interactive demonstration script:
     ```powershell
     python demo.py
     ```
     *(or `python demo_day2.py`)*
   - Visualizes:
     1. Synthetic frame capture with privacy disabled-by-default and safe placeholder fallback.
     2. Prompt injection neutralization preventing delimiter breakouts.
     3. A multimodal request grounded in active VS Code screen context (`ZeroDivisionError`) producing a deterministic explanation and fix recommendation.
     4. Safety gate halting execution for user confirmation on sensitive file operations.

2. **Live Real-Time Web Application & API:**
   - Start the interactive engine:
     ```powershell
     python run_server.py
     ```
   - **Interactive Web App UI:** [http://localhost:8001](http://localhost:8001)
   - **Interactive Swagger Docs:** [http://localhost:8001/docs](http://localhost:8001/docs)
   - **Live Test Suite Execution Endpoint:** `POST /api/tests/run` (runs all 50 tests live and returns execution metrics)

3. **Open GitHub Pull Request:**
   - Pull request into `main` branch with complete test output:  
     👉 **[Create Pull Request for 'divya'](https://github.com/divya182307-dot/voicebot-SDE2-teamm/compare/main...divya?expand=1)**

---

### 🧪 Running the Tests

To run the complete automated test suite locally:

```powershell
python tests/run_tests.py
```

```text
======================================================================
 SDE-2 VOICEBOT: AUTOMATED TEST SUITE EXECUTION
======================================================================
[*] Task 1: Synthetic Frames & Privacy Enforcement ...
  [PASS] test_screen_capture_disabled_by_default
  [PASS] test_screen_capture_raises_when_disabled
  [PASS] test_disabled_fallback_returns_zero_image_bytes
  [PASS] test_authorized_session_allows_capture_and_revokes
  [PASS] test_manual_enable_and_disable
  [PASS] test_generate_synthetic_scenario_all_types
  [PASS] test_redacted_privacy_flag

[*] Task 2: Deterministic Mock Reasoning Engine ...
  [PASS] test_deterministic_consistency_same_input
  [PASS] test_error_explanation_grounded_uc02
  [PASS] test_document_summarization_uc03
  [PASS] test_sensitive_action_requires_user_approval_uc08
  [PASS] test_destructive_action_strict_approval_gate

[*] Task 3: Versioned Prompts & Injection Defense ...
  [PASS] test_prompt_registry_registration_and_retrieval
  [PASS] test_prompt_v1_0_rendering_and_delimiters
  [PASS] test_prompt_v1_1_injection_sanitization
  [PASS] test_orchestrator_prompt_rendering

[*] Task 4: Complete End-to-End Integration ...
  [PASS] test_end_to_end_integration_flow

[*] Task 5: Reasoning Request & Result Validation Suite ...
  [PASS] test_valid_minimal_voice_request
  [PASS] test_valid_multimodal_request_with_screen_context
  [PASS] test_valid_multimodal_request_with_visual_context_item
  [PASS] test_valid_request_boundary_values
  [PASS] test_valid_informational_response_category_a
  [PASS] test_valid_sensitive_response_category_c
  [PASS] test_valid_destructive_response_category_d
  [PASS] test_invalid_empty_request_id
  [PASS] test_invalid_whitespace_only_session_id
  [PASS] test_invalid_empty_user_query
  [PASS] test_invalid_query_exceeding_max_length
  [PASS] test_invalid_temperature_out_of_bounds
  [PASS] test_invalid_max_tokens_out_of_bounds
  [PASS] test_invalid_multimodal_missing_visual_context
  [PASS] test_invalid_conversation_history_missing_required_keys
  [PASS] test_invalid_conversation_history_invalid_role
  [PASS] test_invalid_conversation_history_empty_content
  [PASS] test_invalid_conversation_history_turn_overflow
  [PASS] test_invalid_tool_name_pattern_violations
  [PASS] test_invalid_empty_response_id
  [PASS] test_invalid_empty_user_intent
  [PASS] test_invalid_empty_agent_response_text
  [PASS] test_invalid_confidence_score_out_of_bounds
  [PASS] test_invalid_negative_processing_time
  [PASS] test_invalid_tool_call_required_without_action_plan
  [PASS] test_invalid_action_plan_populated_when_tool_call_not_required
  [PASS] test_invalid_action_steps_non_sequential_numbering
  [PASS] test_invalid_risk_level_inconsistency
  [PASS] test_invalid_sensitive_operation_missing_approval_flag
  [PASS] test_invalid_sensitive_operation_missing_approval_prompt
  [PASS] test_invalid_destructive_operation_missing_approval_flag
  [PASS] test_invalid_destructive_operation_missing_approval_prompt
  [PASS] test_invalid_informational_response_with_approval_prompt

======================================================================
 TEST SUMMARY: 50 / 50 PASSED (100% SUCCESS)
 Duration: 0.082s
======================================================================
```

---

### 💡 Quick Start Example

#### Grounded Reasoning with Screen Context:

```python
from app.schemas.common import InputModality
from app.schemas.reasoning import ReasoningRequest
from app.vision.synthetic_frames import ScreenCaptureManager, SyntheticScenario
from app.reasoning.mock_engine import DeterministicMockReasoningEngine

# Initialize reasoning engine
engine = DeterministicMockReasoningEngine()

# Generate authorized synthetic screen frame with code error
screen_context = ScreenCaptureManager.generate_synthetic_scenario(SyntheticScenario.CODE_EDITOR_ERROR)

# Formulate multimodal request
request = ReasoningRequest(
    request_id="req-demo-001",
    session_id="sess-demo-001",
    user_query="Why is my script throwing this error?",
    modality=InputModality.MULTIMODAL,
    screen_context=screen_context,
)

# Execute grounded reasoning
result = engine.reason(request)

print("Intent:    ", result.user_intent)
print("Risk Level:", result.risk_level.value)
print("Response:  ", result.agent_response_text)
print("Confidence:", result.confidence_score)
```
