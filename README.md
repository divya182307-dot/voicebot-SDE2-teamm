# voicebot-week1-teamm
AI Voice Co-Pilot - Team Project

## Academia – AI Voice Co-Pilot: SDE-2 Voicebot Engine

This module forms the core reasoning, multimodal synthetic vision, prompt orchestration, and validation foundation of **Academia – AI Voice Co-Pilot**, responsible for deterministic mock reasoning, synthetic screen frame ingestion with privacy guardrails, versioned prompt templating with prompt injection defenses, and strict Pydantic v2 schema validation.

---

### 📁 Repository Structure

```text
voicebot-SDE2-teamm/
├── app/
│   ├── __init__.py
│   ├── main.py                         # Live FastAPI backend & interactive web app
│   ├── prompts/
│   │   ├── __init__.py
│   │   ├── models.py                   # VersionedPrompt, RenderedPrompt definitions
│   │   └── registry.py                 # PromptRegistry and registered templates
│   ├── reasoning/
│   │   ├── __init__.py
│   │   └── mock_engine.py              # Deterministic mock reasoning engine (PRD Categories A-D)
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── common.py                   # Enums (ContextType, ExecutionStatus, RiskLevel, etc.)
│   │   ├── context.py                  # ScreenContext, SourceReference, ContextItem schemas
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
│   ├── conftest.py                     # Pytest fixtures and mock setups
│   ├── run_tests.py                    # Standalone test runner (50 passing tests)
│   ├── test_day2_integration.py        # E2E integration verification
│   ├── test_mock_reasoning.py          # Deterministic reasoning tests
│   ├── test_reasoning_validation.py    # Schema validation test suite (33 tests)
│   ├── test_synthetic_frames.py        # Privacy and synthetic capture tests (7 tests)
│   └── test_versioned_prompts.py       # Prompt injection and template tests (4 tests)
├── .gitignore                          # Python cache and temporary file exclusions
├── demo_day2.py                        # Interactive terminal demonstration script
├── README.md                           # Comprehensive project documentation
└── run_server.py                       # Server runner for live execution engine
```

---

### 🚀 Deliverables Summary (Week 1 Complete)

#### 📅 Day 2: Synthetic Frames, Mock Reasoning & Versioned Prompts

1. **Synthetic Frames with Screen Capture Disabled by Default (`app/vision/synthetic_frames.py`)**:
   - **Privacy Enforcement:** Screen capture is strictly **disabled by default** (`is_capture_enabled = False`), adhering to PRD NG3 and Section 19 Privacy requirements. Attempting to capture without explicit consent raises `ScreenCaptureDisabledException`.
   - **Supported Scenarios:**
     - `CODE_EDITOR_ERROR`: VS Code active window with traceback (UC-02).
     - `RESEARCH_PAPER_PDF`: PDF viewer with academic methodology excerpt (UC-03).
     - `SPREADSHEET_ANALYSIS`: Tabular quarterly sales data and trends (UC-04).
     - `FILE_EXPLORER`: Downloads directory with file metadata (UC-06, UC-08).
     - `REDACTED_PRIVACY`: PII/secret masking demonstration (`contains_sensitive_data = True`).
   - **Authorization Lifecycles:** Supports explicit `enable_capture()` / `disable_capture()` and scoped context management via `with manager.authorized_session(): ...`.

2. **Deterministic Mock Reasoning Engine (`app/reasoning/mock_engine.py`)**:
   - **Deterministic Guarantee:** Generates 100% reproducible outputs for identical `ReasoningRequest` payloads using SHA-256 input digest hashing.
   - **Scenarios & Action Categories Handled:**
     - **Category A (Informational):** Screen content description (UC-01), error explanation (UC-02), document section summarization (UC-03), and tabular trend analysis (UC-04).
     - **Category C (Sensitive):** File organization action plan requiring explicit confirmation (UC-08).
     - **Category D (High-Risk/Destructive):** Permanent deletion gate with strict human-in-the-loop approval.
     - **General Assistance Fallback:** Deterministic seed-based response for general queries.

3. **Versioned Prompts with Trusted / Untrusted Isolation (`app/prompts/`)**:
   - **Security Boundary:** Trusted developer directives reside in system instructions with operational rules and security guardrails. Untrusted user and screen data are encapsulated inside explicit delimiters (`<untrusted_user_input>`, `<untrusted_screen_context>`, `<untrusted_retrieved_context>`).
   - **Prompt Injection Defense:** Neutralizes attempts to inject closing delimiter tags to prevent prompt breakouts.
   - **Registered Prompt Versions:**
     - `multimodal_co_pilot:1.0.0`: Baseline prompt.
     - `multimodal_co_pilot:1.1.0`: Hardened prompt with injection defense.
     - `agent_orchestrator:1.0.0`: Multi-step tool planning prompt.

---

#### 📅 Day 3: Reasoning Request & Result Validation Suite

1. **Reasoning Schemas (`app/schemas/reasoning.py`)**:
   - Pydantic v2 schemas for `ReasoningRequest`, `ReasoningResult`, and `ActionStep`.
   - Comprehensive boundary validation:
     - `temperature` validated within `[0.0, 2.0]`
     - `max_tokens` validated within `[64, 8192]`
     - `confidence_score` validated within `[0.0, 1.0]`
     - Automatic whitespace trimming across all string identifiers and queries.
     - Contiguous 1-based sequential step numbering (`1, 2, 3...`).
     - Tool name regex pattern enforcement (`^[a-zA-Z0-9_-]+$`).
     - Category-based approval gating: Category C/D operations require `requires_user_approval=True` and a valid `approval_prompt`, while Category A prohibits user approval prompts.

2. **Automated Validation Test Suite (`tests/test_reasoning_validation.py`)**:
   - 33 comprehensive unit tests validating:
     - Minimal voice queries, multimodal requests with authorized `ScreenContext`, and request boundaries.
     - Invalid payloads: empty identifiers, query length overflow (>4000 chars), missing visual context for multimodal requests, malformed conversation turns, regex tool name violations.
     - Business logic violations: `tool_call_required` mismatch with `action_plan`, non-sequential step numbering, risk level inconsistencies.
     - Edge cases: whitespace trimming, 500-char prompt boundaries, confidence score extremes.

---

### 🧪 Running the Tests

To run the complete automated test suite:

```powershell
python tests/run_tests.py
```

#### Test Suite Summary (50 / 50 Passing Tests — 100% Success):
- **Task 1: Synthetic Frames & Privacy Enforcement:** 7 tests PASSED
- **Task 2: Deterministic Mock Reasoning Engine:** 5 tests PASSED
- **Task 3: Versioned Prompts & Injection Defense:** 4 tests PASSED
- **Task 4: Complete End-to-End Integration:** 1 test PASSED
- **Task 5: Reasoning Request & Result Validation Suite:** 33 tests PASSED
- **Total:** **50 / 50 PASSED (100% Success)**

---

### 💡 Quick Start Example

#### 1. Running Deterministic Reasoning in Python:

```python
from app.schemas.reasoning import ReasoningRequest
from app.reasoning.mock_engine import DeterministicMockReasoningEngine

engine = DeterministicMockReasoningEngine()

# Category A: Informational Error Explanation
request = ReasoningRequest(
    request_id="req-demo-001",
    session_id="sess-demo-001",
    user_query="Why is my script throwing a ZeroDivisionError?",
)

result = engine.reason(request)
print("Intent:", result.user_intent)
print("Response:", result.agent_response_text)
print("Confidence:", result.confidence_score)
```

#### 2. Starting the Live Real-Time Web Application & API:

```powershell
python run_server.py
```

- **Interactive Web App UI:** [http://localhost:8001](http://localhost:8001)
- **Interactive Swagger Docs:** [http://localhost:8001/docs](http://localhost:8001/docs)
- **ReDoc API Documentation:** [http://localhost:8001/redoc](http://localhost:8001/redoc)
