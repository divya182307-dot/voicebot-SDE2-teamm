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
│   ├── context/
│   │   ├── __init__.py
│   │   └── builder.py                  # BoundedContextBuilder (recency, relevance, token budget, stale filter)
│   ├── llm/
│   │   ├── __init__.py
│   │   └── client_adapter.py           # LLMClientAdapter (timeout, retry, structured validation)
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
│       ├── capture_adapter.py          # Opt-in capture adapter with sampling & size limits
│       ├── synthetic_frames.py         # ScreenCaptureManager with privacy enforcement
│       └── vision_adapter.py           # OCR & vision adapter interface + deterministic engine
├── results/
│   ├── test_server.ps1                 # Endpoint smoke test script
│   └── view_results.html               # Interactive deliverables viewer & scorecard
├── tests/
│   ├── __init__.py
│   ├── conftest.py                     # Pytest fixtures and mock test setups
│   ├── run_tests.py                    # Standalone test runner (102/102 passing tests)
│   ├── test_bounded_context_builder.py # Recency, relevance, budget & stale filter tests (11 tests)
│   ├── test_capture_and_vision_adapters.py # Opt-in, rate limiting, size & vision tests (15 tests)
│   ├── test_llm_client_adapter.py      # Timeout, retry & structured validation tests (12 tests)
│   ├── test_malformed_output.py        # Malformed output & schema error handling tests (13 tests)
│   ├── test_day2_integration.py        # Complete end-to-end integration test
│   ├── test_mock_reasoning.py          # Deterministic reasoning & safety tests (5 tests)
│   ├── test_reasoning_validation.py    # Request & result validation test suite (33 tests)
│   ├── test_synthetic_frames.py        # Privacy & synthetic capture tests (7 tests)
│   └── test_versioned_prompts.py       # Prompt isolation & injection defense tests (4 tests)
├── .gitignore                          # Python cache and temporary file exclusions
├── benchmark_cli.py                    # Voice, Text, and Performance benchmark CLI
├── demo.py                             # Day 7 demonstration script (grounded response demo)
├── demo_adapters.py                    # Opt-in capture & vision adapter terminal demo
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

#### 📅 Week 2 / W3 Implementation: Production Adapters, Hardening & Voice CLI

1. **Opt-In Capture Adapter with Sampling & Size Limits (`app/vision/capture_adapter.py`)**:
   - **Strict Opt-In Policy:** Capture is locked by default. Calls to `capture()` without prior `opt_in()` immediately raise `CaptureNotAuthorizedException`. Supports scoped authorization via `with adapter.authorized_session(): ...`.
   - **Sliding-Window Rate Limiter:** Enforces minimum capture intervals (default 0.5s) and rolling 1-second request ceilings (default 2 fps) to prevent CPU/GPU saturation, raising `SamplingLimitExceededException` upon breach.
   - **Payload & Resolution Guard:** Restricts capture dimensions (max 1920x1080) and raw payload size (max 2.0MB). Dynamically scales down oversized frames while preserving aspect ratio, or strictly rejects with `CaptureSizeLimitExceededException`.
   - **Capture Metrics:** Tracks total requests, accepted frames, throttled requests, and rejected sizes.

2. **OCR & Vision Adapter Interface (`app/vision/vision_adapter.py`)**:
   - **Abstract Interface:** Defines `BaseVisionAdapter` contract for OCR (`extract_text`), visual element analysis (`analyze_visuals`), and full frame analysis (`process_screen_context`).
   - **Deterministic Implementation:** High-performance, offline `DeterministicVisionAdapter` returning structured `OCRResult` and `VisionAnalysisResult` with bounding boxes and confidence scores.
   - **Sensitive Data & PII Redaction:** Integrates `RuleBasedSensitiveDataScanner` to automatically detect and redact API keys (`sk-...`), bearer tokens, passwords, credit cards, and SSNs.

3. **Bounded Context Builder with Recency, Relevance & Token Budget (`app/context/builder.py`)**:
   - **Recency Time-Decay Scoring:** Applies exponential time-decay ($e^{-\lambda \Delta t}$) prioritizing immediate user and system events over historical logs.
   - **Keyword Relevance Selection:** Computes word overlap and semantic match between active user query and context items.
   - **Stale Context Filtering:** Automatically prunes items exceeding Time-To-Live (TTL), with granular per-type thresholds (e.g. 300s default, 600s for code snippets) and superseded item filtering.
   - **Strict Token Budget Ceiling:** Accurately estimates token consumption across text, code, and system metadata, packing items strictly under the configured ceiling (e.g. 1024 tokens) to prevent LLM context overflow.

4. **LLM Client Adapter with Timeout, Retry & Structured Output (`app/llm/client_adapter.py`)**:
   - **Timeout Protection:** Configurable per-request timeout (default 10s) raising `LLMTimeoutException`.
   - **Exponential Backoff with Jitter:** Automatic retries for transient HTTP 503 / network errors with randomized jitter to prevent thundering herd problems.
   - **Structured-Output Validation:** Extracts raw JSON from markdown code fences (` ```json `), strips conversational preambles/postambles, and strictly parses into target Pydantic models.
   - **Malformed-Output Rejection:** Detects truncated JSON, missing braces, unquoted keys, and schema violations, retrying or raising `StructuredOutputValidationException`.

5. **Interactive Voice CLI & Audio Synthesizer (`voice_cli.py`)**:
   - **Live Voice Interaction:** Interactive terminal dialogue shell with multi-turn conversation support.
   - **Windows Voice Dictation (`Win + H`):** Direct microphone speech-to-text dictation into the prompt.
   - **Windows System.Speech (SAPI TTS):** Speaks responses aloud through computer speakers with `--speak`.
   - **Safety Gate Visualization:** Renders Category A execution vs Category D verbal confirmation gates.

---

### 🧪 Running the Tests (102 Tests Passing)

To run the complete automated test suite locally:

```powershell
python tests/run_tests.py
```

```text
===========================================================================
 SDE-2 VOICEBOT: DAY 2 & DAY 3 AUTOMATED TEST SUITE
===========================================================================

[SUITE] Running: Task 1: Synthetic Frames (Screen Capture Disabled by Default)
  [PASS] test_all_synthetic_scenarios_generate_valid_screen_context
  [PASS] test_authorized_session_context_manager
  [PASS] test_capture_fallback_when_disabled
  [PASS] test_capture_raises_when_disabled
  [PASS] test_create_custom_synthetic_frame
  [PASS] test_explicit_enable_and_disable
  [PASS] test_screen_capture_disabled_by_default
  [PASS] test_synthetic_frames_determinism

[SUITE] Running: Task 2: Deterministic Mock Reasoning Engine
  [PASS] test_destructive_action_category_d_safety_gate
  [PASS] test_determinism_identical_input_produces_identical_output
  [PASS] test_uc01_screen_explanation
  [PASS] test_uc02_error_explanation
  [PASS] test_uc08_controlled_action_requires_approval

[SUITE] Running: Task 3: Versioned Prompts with Trusted/Untrusted Separation
  [PASS] test_injection_sanitization_prevents_delimiter_breakout
  [PASS] test_registry_retrieval_and_versioning
  [PASS] test_registry_unknown_prompt_or_version_raises
  [PASS] test_trusted_instructions_separated_from_untrusted_content

[SUITE] Running: Task 4: Complete End-to-End Pipeline Integration
  [PASS] test_complete_day2_end_to_end_pipeline

[SUITE] Running: Task 5: Reasoning Request & Result Validation Suite
  [PASS] test_edge_case_approval_prompt_boundary_length
  [PASS] test_edge_case_confidence_boundary_values
  [PASS] test_edge_case_empty_approval_prompt_coerced_to_none
  [PASS] test_edge_case_whitespace_stripping
  [PASS] test_invalid_action_step_sensitive_without_approval
  [PASS] test_invalid_request_available_tools_invalid_characters
  [PASS] test_invalid_request_conversation_history_malformed
  [PASS] test_invalid_request_conversation_history_too_many_turns
  [PASS] test_invalid_request_empty_or_whitespace_fields
  [PASS] test_invalid_request_id_too_long
  [PASS] test_invalid_request_max_tokens_out_of_bounds
  [PASS] test_invalid_request_multimodal_missing_visual_context
  [PASS] test_invalid_request_query_too_long
  [PASS] test_invalid_request_temperature_out_of_bounds
  [PASS] test_invalid_result_action_plan_without_tool_call_required
  [PASS] test_invalid_result_category_a_with_approval
  [PASS] test_invalid_result_category_a_with_approval_prompt
  [PASS] test_invalid_result_category_c_without_approval
  [PASS] test_invalid_result_category_d_without_approval
  [PASS] test_invalid_result_confidence_out_of_bounds
  [PASS] test_invalid_result_empty_or_whitespace_fields
  [PASS] test_invalid_result_non_sequential_action_steps
  [PASS] test_invalid_result_processing_time_negative
  [PASS] test_invalid_result_risk_level_lower_than_action_steps
  [PASS] test_invalid_result_sensitive_missing_approval_prompt
  [PASS] test_invalid_result_tool_call_without_action_plan
  [PASS] test_valid_reasoning_request_boundaries
  [PASS] test_valid_reasoning_request_multimodal_with_screen
  [PASS] test_valid_reasoning_request_multimodal_with_visual_item
  [PASS] test_valid_reasoning_request_voice_minimal
  [PASS] test_valid_reasoning_result_destructive_category_d
  [PASS] test_valid_reasoning_result_informational_category_a
  [PASS] test_valid_reasoning_result_sensitive_category_c

[SUITE] Running: Task 6: Opt-In Capture Adapter & OCR/Vision Adapter Interface
  [PASS] test_authorized_session_context_manager
  [PASS] test_capture_adapter_metrics
  [PASS] test_opt_in_enables_capture
  [PASS] test_opt_in_required_by_default
  [PASS] test_opt_out_revokes_capture
  [PASS] test_sampling_rate_limit_min_interval
  [PASS] test_sampling_rate_limit_sliding_window
  [PASS] test_sensitive_data_scanner_redaction
  [PASS] test_size_limits_payload_bytes_exceeded
  [PASS] test_size_limits_scale_down_aspect_ratio
  [PASS] test_size_limits_strict_rejection
  [PASS] test_vision_adapter_analyze_visuals
  [PASS] test_vision_adapter_detects_sensitive_data_and_pii
  [PASS] test_vision_adapter_extract_text
  [PASS] test_vision_adapter_process_screen_context

[SUITE] Running: Task 7: Bounded Context Builder (Recency, Relevance & Budget)
  [PASS] test_deterministic_reproducibility
  [PASS] test_priority_weighting
  [PASS] test_recency_scoring_time_decay
  [PASS] test_relevance_selection_keyword_overlap
  [PASS] test_screen_context_dynamic_ingestion
  [PASS] test_stale_filter_expiration_default_ttl
  [PASS] test_stale_filter_superseded_items
  [PASS] test_stale_filter_type_specific_ttl
  [PASS] test_token_budget_packing_strict_ceiling
  [PASS] test_token_estimator_context_item
  [PASS] test_token_estimator_text_and_code

[SUITE] Running: Task 8: LLM Client Adapter (Timeout, Retry & Structured Output)
  [PASS] test_max_retries_exhausted_raises_exception
  [PASS] test_non_retriable_auth_error_no_retry
  [PASS] test_structured_output_parser_clean_json
  [PASS] test_structured_output_parser_invalid_schema
  [PASS] test_structured_output_parser_markdown_code_fences
  [PASS] test_structured_output_validation_exhausted_raises_exception
  [PASS] test_structured_output_validation_retry_and_recovery
  [PASS] test_structured_output_validation_success
  [PASS] test_structured_output_validation_with_domain_reasoning_result
  [PASS] test_successful_text_generation
  [PASS] test_timeout_raises_llm_timeout_exception
  [PASS] test_transient_failure_retry_and_recovery

[SUITE] Running: Task 9: Malformed Output & Schema Error Handling Tests
  [PASS] test_conversational_preamble_and_postamble_isolation
  [PASS] test_llm_adapter_exhausted_retries_raises_detailed_exception
  [PASS] test_llm_adapter_recovers_from_malformed_outputs
  [PASS] test_malformed_action_steps_in_action_plan
  [PASS] test_malformed_html_xml_payload
  [PASS] test_malformed_json_missing_braces
  [PASS] test_malformed_json_truncated
  [PASS] test_malformed_json_unquoted_keys
  [PASS] test_malformed_non_json_conversational_refusal
  [PASS] test_malformed_reasoning_result_invalid_enum_literals
  [PASS] test_malformed_reasoning_result_missing_mandatory_fields
  [PASS] test_malformed_reasoning_result_negative_latency
  [PASS] test_malformed_reasoning_result_out_of_bounds_confidence

===========================================================================
 TEST RUN SUMMARY: 102/102 PASSED in 0.569s (Failed: 0)
===========================================================================
```
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
