"""
Unit tests for Task 2: Deterministic mock reasoning that produces consistent results.
Compatible with pytest and standard Python test runners.
"""

from datetime import datetime, timezone

try:
    import pytest
except ImportError:
    class _PytestCompat:
        class raises:
            def __init__(self, expected_exc):
                self.expected_exc = expected_exc
                self.value = None
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                if exc_type is None:
                    raise AssertionError(f"Expected exception {self.expected_exc.__name__} not raised.")
                if not issubclass(exc_type, self.expected_exc):
                    return False
                self.value = exc_val
                return True
        @staticmethod
        def fixture(fn):
            return fn
    pytest = _PytestCompat()

from app.schemas.common import ExecutionStatus, InputModality, RiskLevel
from app.schemas.context import ContextItem, ContextType, ScreenContext
from app.schemas.reasoning import ReasoningRequest
from app.reasoning.mock_engine import DeterministicMockReasoningEngine


@pytest.fixture
def fixed_time():
    return datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def engine(fixed_time):
    return DeterministicMockReasoningEngine(fixed_timestamp=fixed_time)


def test_determinism_identical_input_produces_identical_output(engine):
    """Verify that identical inputs produce 100% consistent results across multiple calls."""
    screen = ScreenContext(
        capture_id="cap-test-01",
        application_name="VS Code",
        window_title="main.py",
        width=1920,
        height=1080,
        ocr_text="ZeroDivisionError: division by zero",
    )
    req1 = ReasoningRequest(
        request_id="req-same-01",
        session_id="sess-01",
        user_query="Why is this failing?",
        modality=InputModality.VOICE,
        screen_context=screen,
    )
    req2 = ReasoningRequest(
        request_id="req-same-01",
        session_id="sess-01",
        user_query="Why is this failing?",
        modality=InputModality.VOICE,
        screen_context=screen,
    )

    res1 = engine.reason(req1)
    res2 = engine.reason(req2)

    # Validate absolute determinism
    assert res1.response_id == res2.response_id
    assert res1.user_intent == res2.user_intent
    assert res1.response_text == res2.response_text
    assert res1.confidence_score == res2.confidence_score
    assert res1.risk_level == res2.risk_level
    assert res1.requires_user_approval == res2.requires_user_approval
    assert res1.tool_call_required == res2.tool_call_required
    assert res1.processing_time_ms == res2.processing_time_ms
    assert len(res1.action_plan) == len(res2.action_plan)


def test_uc01_screen_explanation(engine):
    """Verify UC-01 screen query produces Category A Informational response."""
    screen = ScreenContext(
        capture_id="cap-01",
        application_name="VS Code",
        window_title="calculator.py",
        width=1920,
        height=1080,
        ocr_text="def calculate(): pass",
    )
    req = ReasoningRequest(
        request_id="req-uc01",
        session_id="sess-01",
        user_query="What am I looking at?",
        screen_context=screen,
    )
    res = engine.reason(req)
    assert res.user_intent == "describe_active_screen"
    assert res.risk_level == RiskLevel.CATEGORY_A_INFORMATIONAL
    assert res.requires_user_approval is False
    assert "VS Code" in res.response_text


def test_uc02_error_explanation(engine):
    """Verify UC-02 error query detects ZeroDivisionError and formulates guidance."""
    screen = ScreenContext(
        capture_id="cap-02",
        application_name="Terminal",
        window_title="bash",
        width=1280,
        height=720,
        ocr_text="ZeroDivisionError: division by zero",
    )
    req = ReasoningRequest(
        request_id="req-uc02",
        session_id="sess-01",
        user_query="Why is this failing?",
        screen_context=screen,
    )
    res = engine.reason(req)
    assert res.user_intent == "explain_technical_error"
    assert res.risk_level == RiskLevel.CATEGORY_A_INFORMATIONAL
    assert "ZeroDivisionError" in res.response_text


def test_uc08_controlled_action_requires_approval(engine):
    """Verify UC-08 file move action triggers Category C Sensitive classification and approval gate."""
    req = ReasoningRequest(
        request_id="req-uc08",
        session_id="sess-01",
        user_query="Move these files into the project folder",
        available_tools=["move_file"],
    )
    res = engine.reason(req)
    assert res.user_intent == "organize_files_action"
    assert res.tool_call_required is True
    assert res.risk_level == RiskLevel.CATEGORY_C_SENSITIVE
    assert res.requires_user_approval is True
    assert res.approval_prompt is not None
    assert len(res.action_plan) == 1
    assert res.action_plan[0].tool_name == "move_file"
    assert res.status == ExecutionStatus.NEEDS_APPROVAL


def test_destructive_action_category_d_safety_gate(engine):
    """Verify destructive action triggers Category D Destructive classification and strict approval."""
    req = ReasoningRequest(
        request_id="req-destruct",
        session_id="sess-01",
        user_query="Delete files in directory rm -rf",
        available_tools=["delete_files"],
    )
    res = engine.reason(req)
    assert res.user_intent == "destructive_file_action"
    assert res.tool_call_required is True
    assert res.risk_level == RiskLevel.CATEGORY_D_HIGH_RISK_DESTRUCTIVE
    assert res.requires_user_approval is True
    assert "HIGH RISK" in res.approval_prompt or "permanently delete" in res.approval_prompt
