"""
Comprehensive SDE-2 Voicebot Engine Demonstration Runner.
Demonstrates:
1. Opt-in Capture Adapter with Privacy, Sampling Limits, and Size Bounds.
2. OCR & Vision Understanding with Sensitive Data / PII Detection.
3. Bounded Context Builder with Recency, Relevance, Token Budgeting, and Stale Filtering.
4. LLM Client Adapter with Timeout, Retry, and Structured-Output Validation (with Malformed Recovery).
5. Grounded Multimodal Reasoning & Category C/D Human-In-The-Loop Safety Gates.

Usage:
    python projects/sde-2-voicebot/demo.py
"""

from datetime import datetime, timezone
import json
import os
import sys
import time

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from app.schemas.common import ContextType, ExecutionStatus, InputModality, RiskLevel
from app.schemas.context import ContextItem, ScreenContext
from app.schemas.reasoning import ReasoningRequest, ReasoningResult
from app.vision import (
    CaptureConfig,
    CaptureNotAuthorizedException,
    DeterministicVisionAdapter,
    OptInCaptureAdapter,
    SamplingLimitExceededException,
    ScreenCaptureManager,
    SyntheticScenario,
)
from app.context.builder import (
    BoundedContextBuilder,
    BoundedContextConfig,
    StaleFilterConfig,
    TokenEstimator,
)
from app.llm import (
    LLMClientAdapter,
    LLMClientConfig,
    MockDeterministicLLMProvider,
    StructuredOutputParser,
)
from app.reasoning.mock_engine import DeterministicMockReasoningEngine


def banner(title: str):
    print("\n" + "=" * 75)
    print(f" {title}")
    print("=" * 75)


def demo_1_capture_and_vision():
    banner("1. OPT-IN CAPTURE ADAPTER & VISION UNDERSTANDING")
    adapter = OptInCaptureAdapter(config=CaptureConfig(min_interval_seconds=1.0, max_width=1920, max_height=1080))
    print(f"[*] Initial Opt-In Authorization: {adapter.is_opted_in} (STRICT PRIVACY DEFAULT)")

    # 1. Blocked unauthorized capture
    print("\n[Step 1.1] Attempting screen capture without user consent:")
    try:
        adapter.capture()
    except CaptureNotAuthorizedException as e:
        print(f"  [X] BLOCKED BY DEFAULT: {e}")

    # 2. User opt-in and capture
    print("\n[Step 1.2] User explicitly authorizes screen capture session:")
    adapter.opt_in(consent_token="user-consent-wk1")
    frame = adapter.capture(scenario=SyntheticScenario.CODE_EDITOR_ERROR)
    print(f"  [OK] Captured Frame ID : {frame.capture_id}")
    print(f"  [OK] Active Application: {frame.application_name} ({frame.width}x{frame.height}px)")
    print(f"  [OK] Extracted OCR     : {frame.ocr_text.splitlines()[0]}")

    # 3. Sampling anti-surveillance throttle
    print("\n[Step 1.3] Attempting rapid continuous capture (violating 1.0s interval):")
    try:
        adapter.capture()
    except SamplingLimitExceededException as e:
        print(f"  [X] THROTTLED (PRD NG3 Anti-Surveillance): {e}")

    # 4. OCR & Vision layout understanding with PII check
    print("\n[Step 1.4] Multimodal Vision Understanding & PII Screening:")
    vision = DeterministicVisionAdapter()
    analysis = vision.analyze_visuals(frame)
    print(f"  [>] Semantic Summary   : {analysis.visual_summary}")
    print(f"  [>] Detected UI Widgets: {analysis.detected_elements}")
    print(f"  [>] Contains PII/Secrets: {analysis.contains_sensitive_data}")


def demo_2_bounded_context_builder():
    banner("2. BOUNDED CONTEXT BUILDER (RECENCY, RELEVANCE & BUDGET)")
    now = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
    config = BoundedContextConfig(token_budget=150)
    builder = BoundedContextBuilder(config=config)

    items = [
        ContextItem(
            item_id="ctx-error-trace",
            context_type=ContextType.TERMINAL_OUTPUT,
            title="Runtime Error Traceback",
            content="ZeroDivisionError: division by zero in calculate_average",
            relevance_score=0.98,
            timestamp=now,
        ),
        ContextItem(
            item_id="ctx-code-file",
            context_type=ContextType.CODE_SNIPPET,
            title="calculator.py",
            content="def calculate_average(items):\n    return sum(items) / len(items)",
            relevance_score=0.92,
            timestamp=now,
        ),
        ContextItem(
            item_id="ctx-stale-terminal",
            context_type=ContextType.TERMINAL_OUTPUT,
            title="Old Terminal Output (10 min ago)",
            content="npm install --save react-dom",
            relevance_score=0.40,
            timestamp=datetime(2026, 11, 2, 11, 50, 0, tzinfo=timezone.utc),  # Stale (> 120s TTL)
        ),
        ContextItem(
            item_id="ctx-huge-doc",
            context_type=ContextType.DOCUMENT_EXCERPT,
            title="Large Documentation Manual",
            content="A " * 300,  # ~300 tokens: Exceeds 150 token budget
            relevance_score=0.60,
            timestamp=now,
        ),
    ]
    builder.add_items(items)

    result = builder.build(query="Why does calculate_average divide by zero?", now=now)
    print(f"[*] Candidate items evaluated : {len(items)}")
    print(f"[*] Pruned stale items (TTL)  : {[it.item_id for it in result.discarded_stale_items]}")
    print(f"[*] Selected context items    : {[it.item_id for it in result.selected_items]}")
    print(f"[*] Discarded budget overflow : {[it.item_id for it in result.discarded_budget_items]}")
    print(f"[*] Total Estimated Tokens    : {result.total_tokens} / {result.token_budget} max ceiling")
    print(f"[*] Token Capacity Remaining  : {result.remaining_budget} tokens")


def demo_3_llm_adapter_and_malformed_recovery():
    banner("3. LLM CLIENT ADAPTER (TIMEOUT, RETRY & MALFORMED RECOVERY)")
    provider = MockDeterministicLLMProvider()

    # Simulate realistic LLM unreliability:
    # 1. First attempt: Truncated malformed JSON
    provider.queue_response('{"response_id": "resp-001", "user_intent":')
    # 2. Second attempt: Conversational refusal
    provider.queue_response('I apologize, but I failed to output JSON format.')
    # 3. Third attempt: Valid structured ReasoningResult
    valid_result = {
        "response_id": "resp-llm-recovered-01",
        "request_id": "req-demo-01",
        "session_id": "sess-demo-01",
        "user_intent": "explain_technical_error",
        "response_text": "The ZeroDivisionError occurred because items was empty, resulting in division by len=0.",
        "reasoning_summary": "Identified division by zero and formulated fix.",
        "tool_call_required": False,
        "risk_level": "category_a_informational",
        "requires_user_approval": False,
        "confidence_score": 0.98,
        "processing_time_ms": 14.5,
        "status": "success",
    }
    provider.queue_response(f"```json\n{json.dumps(valid_result)}\n```")

    config = LLMClientConfig(max_retries=3, timeout_seconds=5.0)
    client = LLMClientAdapter(provider=provider, config=config, sleeper=lambda s: None)

    print("[*] Dispatching structured request to LLM Client Adapter...")
    print("  [Attempt 1] Received truncated malformed JSON -> Triggered self-correction re-prompt")
    print("  [Attempt 2] Received non-JSON conversational text -> Triggered schema constraint re-prompt")
    print("  [Attempt 3] Conforming structured output received -> Validating against ReasoningResult schema")

    res = client.generate_structured("Explain the error", response_model=ReasoningResult)
    print(f"\n  [OK] Model successfully validated into : {type(res).__name__}")
    print(f"  [OK] Validated Response ID           : {res.response_id}")
    print(f"  [OK] Detected User Intent            : {res.user_intent}")
    print(f"  [OK] Spoken Response                 : \"{res.response_text}\"")
    print(f"  [OK] Telemetry Metrics               : {client.get_metrics()}")


def demo_4_grounded_reasoning_and_safety_gate():
    banner("4. GROUNDED MULTIMODAL REASONING & SAFETY GATES (PRD SEC 18)")
    engine = DeterministicMockReasoningEngine()

    # Scenario A: Informational request (ZeroDivisionError)
    req_info = ReasoningRequest(
        request_id="req-grounded-01",
        session_id="sess-01",
        user_query="Why is this code throwing an exception?",
        modality=InputModality.VOICE,
        screen_context=ScreenCaptureManager.generate_synthetic_scenario(SyntheticScenario.CODE_EDITOR_ERROR),
    )
    res_info = engine.reason(req_info)
    print("[Scenario A] Informational Voice Query (Category A):")
    print(f"  User Query        : '{req_info.user_query}'")
    print(f"  Classified Risk   : {res_info.risk_level.value}")
    print(f"  Requires Approval : {res_info.requires_user_approval}")
    print(f"  Spoken Output     : \"{res_info.response_text}\"")

    # Scenario B: Sensitive file operation (Category C: Safety Gate Triggered)
    req_action = ReasoningRequest(
        request_id="req-safety-02",
        session_id="sess-02",
        user_query="Move these generated result files into my project folder",
        modality=InputModality.VOICE,
    )
    res_action = engine.reason(req_action)
    print("\n[Scenario B] Sensitive Action Gate (Category C: Approval Required):")
    print(f"  User Query        : '{req_action.user_query}'")
    print(f"  Classified Risk   : {res_action.risk_level.value}")
    print(f"  Requires Approval : {res_action.requires_user_approval} (HALTS EXECUTION)")
    print(f"  Spoken Gate Prompt: \"{res_action.approval_prompt}\"")
    print(f"  Planned Steps     : Step 1 -> {res_action.action_plan[0].step_description}")


def main():
    banner("ACADEMIA AI VOICE CO-PILOT: SDE-2 COMPLETE ENGINE DEMO")
    demo_1_capture_and_vision()
    demo_2_bounded_context_builder()
    demo_3_llm_adapter_and_malformed_recovery()
    demo_4_grounded_reasoning_and_safety_gate()
    banner("COMPLETE DEMONSTRATION VERIFIED: ALL TASKS OPERATIONAL")


if __name__ == "__main__":
    main()
