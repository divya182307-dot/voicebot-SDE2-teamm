"""
Unit tests for validation of ReasoningRequest, ReasoningResult, and ActionStep.

Tests domain validation, business integrity rules, and safety gates aligned with:
- PRD Section 16: Multimodal AI Requirements
- PRD Section 18: Human-in-the-Loop Safety & Risk Categorization (Category A, B, C, D)
- SDD Sections 4.3, 4.4, 5, 6: Agent Orchestrator & Action Planning

Covers:
1. Valid inputs (standard, boundaries, categories)
2. Invalid inputs (structural, bounds, missing required relationships)
3. Edge cases (multimodal requirements, whitespace normalization, prompt boundaries)
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

from pydantic import ValidationError

from app.schemas.common import (
    ContextType,
    ExecutionStatus,
    InputModality,
    RiskLevel,
    SourceType,
)
from app.schemas.context import ContextItem, ScreenContext, SourceReference
from app.schemas.reasoning import ActionStep, ReasoningRequest, ReasoningResult


# ===========================================================================
# 1. VALID INPUT TESTS
# ===========================================================================

def test_valid_reasoning_request_voice_minimal():
    """Validates minimal valid voice reasoning request."""
    req = ReasoningRequest(
        request_id="req-valid-001",
        session_id="sess-valid-001",
        user_query="How do I resolve a NullPointerException?",
    )
    assert req.request_id == "req-valid-001"
    assert req.session_id == "sess-valid-001"
    assert req.user_query == "How do I resolve a NullPointerException?"
    assert req.modality == InputModality.VOICE
    assert req.screen_context is None
    assert req.context_items == []
    assert req.conversation_history == []
    assert req.available_tools == []
    assert req.max_tokens == 1024
    assert req.temperature == 0.2


def test_valid_reasoning_request_multimodal_with_screen():
    """Validates multimodal request containing an authorized ScreenContext."""
    screen = ScreenContext(
        capture_id="cap-screen-001",
        width=1920,
        height=1080,
        application_name="VS Code",
        ocr_text="Traceback line 42",
    )
    req = ReasoningRequest(
        request_id="req-multi-001",
        session_id="sess-multi-001",
        user_query="What is the error on my screen?",
        modality=InputModality.MULTIMODAL,
        screen_context=screen,
        available_tools=["file_search", "code_analyzer"],
    )
    assert req.modality == InputModality.MULTIMODAL
    assert req.screen_context is not None
    assert req.screen_context.capture_id == "cap-screen-001"
    assert req.available_tools == ["file_search", "code_analyzer"]


def test_valid_reasoning_request_multimodal_with_visual_item():
    """Validates multimodal request containing visual context_items without screen_context."""
    item = ContextItem(
        item_id="ctx-vis-001",
        context_type=ContextType.SCREEN_OCR,
        title="Screen OCR Text",
        content="ZeroDivisionError in calculate_average",
    )
    req = ReasoningRequest(
        request_id="req-multi-002",
        session_id="sess-multi-002",
        user_query="Explain the error in the active editor.",
        modality=InputModality.MULTIMODAL,
        context_items=[item],
    )
    assert req.modality == InputModality.MULTIMODAL
    assert len(req.context_items) == 1
    assert req.context_items[0].context_type == ContextType.SCREEN_OCR


def test_valid_reasoning_request_boundaries():
    """Validates request boundary values: max_tokens, temperature, query length, history turns, items count."""
    long_query = "x" * 4000
    turns = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"Turn {i}"} for i in range(30)]
    items = [
        ContextItem(
            item_id=f"ctx-item-{i:03d}",
            context_type=ContextType.CODE_SNIPPET,
            title=f"Snippet {i}",
            content=f"def func_{i}(): pass",
        )
        for i in range(50)
    ]

    req = ReasoningRequest(
        request_id="req-boundary",
        session_id="sess-boundary",
        user_query=long_query,
        context_items=items,
        conversation_history=turns,
        max_tokens=8192,
        temperature=2.0,
    )
    assert len(req.user_query) == 4000
    assert len(req.conversation_history) == 30
    assert len(req.context_items) == 50
    assert req.max_tokens == 8192
    assert req.temperature == 2.0


def test_valid_reasoning_result_informational_category_a():
    """Validates Category A (Informational): no approval required, direct response."""
    src = SourceReference(
        source_id="src-001",
        source_type=SourceType.DOCUMENT,
        title="Python Documentation",
    )
    res = ReasoningResult(
        response_id="res-info-001",
        request_id="req-valid-001",
        session_id="sess-valid-001",
        user_intent="explain_concept",
        response_text="A NullPointerException occurs when accessing a member of a null object reference.",
        tool_call_required=False,
        action_plan=[],
        risk_level=RiskLevel.CATEGORY_A_INFORMATIONAL,
        requires_user_approval=False,
        approval_prompt=None,
        sources_used=[src],
        confidence_score=0.985,
        processing_time_ms=145.2,
        status=ExecutionStatus.SUCCESS,
    )
    assert res.risk_level == RiskLevel.CATEGORY_A_INFORMATIONAL
    assert res.requires_user_approval is False
    assert res.approval_prompt is None
    assert res.tool_call_required is False
    assert len(res.sources_used) == 1


def test_valid_reasoning_result_sensitive_category_c():
    """Validates Category C (Sensitive): multi-step plan, approval required with spoken prompt."""
    step1 = ActionStep(
        step_number=1,
        tool_name="move_file",
        tool_parameters={"source": "downloads/data.csv", "dest": "project/data.csv"},
        step_description="Move data.csv to project directory",
        risk_level=RiskLevel.CATEGORY_C_SENSITIVE,
        requires_approval=True,
    )
    step2 = ActionStep(
        step_number=2,
        tool_name="git_add",
        tool_parameters={"path": "project/data.csv"},
        step_description="Stage newly moved file in git repository",
        risk_level=RiskLevel.CATEGORY_B_LOW_RISK,
        requires_approval=False,
    )
    res = ReasoningResult(
        response_id="res-sens-001",
        request_id="req-valid-002",
        session_id="sess-valid-002",
        user_intent="organize_project_files",
        response_text="I found data.csv in Downloads. I have staged a plan to move it and track it with git.",
        tool_call_required=True,
        action_plan=[step1, step2],
        risk_level=RiskLevel.CATEGORY_C_SENSITIVE,
        requires_user_approval=True,
        approval_prompt="Shall I move data.csv into your project directory and stage it in git?",
        confidence_score=0.94,
        processing_time_ms=180.0,
        status=ExecutionStatus.NEEDS_APPROVAL,
    )
    assert res.tool_call_required is True
    assert len(res.action_plan) == 2
    assert res.requires_user_approval is True
    assert res.approval_prompt is not None
    assert res.status == ExecutionStatus.NEEDS_APPROVAL


def test_valid_reasoning_result_destructive_category_d():
    """Validates Category D (High-Risk/Destructive): strict approval gate."""
    step = ActionStep(
        step_number=1,
        tool_name="permanent_delete",
        tool_parameters={"targets": ["temp/old_data.bin"]},
        step_description="Permanently delete old_data.bin",
        risk_level=RiskLevel.CATEGORY_D_HIGH_RISK_DESTRUCTIVE,
        requires_approval=True,
    )
    res = ReasoningResult(
        response_id="res-dest-001",
        request_id="req-valid-003",
        session_id="sess-valid-003",
        user_intent="delete_file",
        response_text="Permanent deletion requested. Explicit safety approval is mandatory.",
        tool_call_required=True,
        action_plan=[step],
        risk_level=RiskLevel.CATEGORY_D_HIGH_RISK_DESTRUCTIVE,
        requires_user_approval=True,
        approval_prompt="DANGER: Are you sure you want to permanently delete old_data.bin? This cannot be undone.",
        confidence_score=0.99,
        processing_time_ms=110.5,
        status=ExecutionStatus.NEEDS_APPROVAL,
    )
    assert res.risk_level == RiskLevel.CATEGORY_D_HIGH_RISK_DESTRUCTIVE
    assert res.requires_user_approval is True


# ===========================================================================
# 2. INVALID INPUT TESTS
# ===========================================================================

def test_invalid_request_empty_or_whitespace_fields():
    """Rejects empty or whitespace-only identifiers and queries."""
    with pytest.raises(ValidationError):
        ReasoningRequest(request_id="   ", session_id="sess-1", user_query="Valid query")

    with pytest.raises(ValidationError):
        ReasoningRequest(request_id="req-1", session_id="", user_query="Valid query")

    with pytest.raises(ValidationError):
        ReasoningRequest(request_id="req-1", session_id="sess-1", user_query="   \n\t  ")


def test_invalid_request_id_too_long():
    """Rejects request_id exceeding 64 characters."""
    with pytest.raises(ValidationError):
        ReasoningRequest(
            request_id="x" * 65,
            session_id="sess-1",
            user_query="Valid query",
        )


def test_invalid_request_query_too_long():
    """Rejects user_query exceeding 4000 characters."""
    with pytest.raises(ValidationError):
        ReasoningRequest(
            request_id="req-1",
            session_id="sess-1",
            user_query="x" * 4001,
        )


def test_invalid_request_max_tokens_out_of_bounds():
    """Rejects max_tokens below 64 or above 8192."""
    with pytest.raises(ValidationError):
        ReasoningRequest(request_id="r1", session_id="s1", user_query="q", max_tokens=63)

    with pytest.raises(ValidationError):
        ReasoningRequest(request_id="r1", session_id="s1", user_query="q", max_tokens=8193)


def test_invalid_request_temperature_out_of_bounds():
    """Rejects temperature below 0.0 or above 2.0."""
    with pytest.raises(ValidationError):
        ReasoningRequest(request_id="r1", session_id="s1", user_query="q", temperature=-0.1)

    with pytest.raises(ValidationError):
        ReasoningRequest(request_id="r1", session_id="s1", user_query="q", temperature=2.1)


def test_invalid_request_conversation_history_too_many_turns():
    """Rejects conversation_history exceeding 30 turns."""
    turns = [{"role": "user", "content": f"Turn {i}"} for i in range(31)]
    with pytest.raises(ValidationError):
        ReasoningRequest(
            request_id="r1",
            session_id="s1",
            user_query="q",
            conversation_history=turns,
        )


def test_invalid_request_conversation_history_malformed():
    """Rejects turns with invalid roles or missing fields."""
    with pytest.raises(ValidationError):
        # Missing 'content'
        ReasoningRequest(
            request_id="r1",
            session_id="s1",
            user_query="q",
            conversation_history=[{"role": "user"}],
        )

    with pytest.raises(ValidationError):
        # Invalid role
        ReasoningRequest(
            request_id="r1",
            session_id="s1",
            user_query="q",
            conversation_history=[{"role": "superuser", "content": "hello"}],
        )

    with pytest.raises(ValidationError):
        # Empty content
        ReasoningRequest(
            request_id="r1",
            session_id="s1",
            user_query="q",
            conversation_history=[{"role": "user", "content": "   "}],
        )


def test_invalid_request_available_tools_invalid_characters():
    """Rejects tool names containing dangerous or invalid characters."""
    with pytest.raises(ValidationError):
        ReasoningRequest(
            request_id="r1",
            session_id="s1",
            user_query="q",
            available_tools=["valid_tool", "rm -rf /; bad tool!"],
        )

    with pytest.raises(ValidationError):
        ReasoningRequest(
            request_id="r1",
            session_id="s1",
            user_query="q",
            available_tools=["   "],
        )


def test_invalid_request_multimodal_missing_visual_context():
    """Rejects MULTIMODAL requests that provide no screen_context and no visual context_items."""
    with pytest.raises(ValidationError) as exc_info:
        ReasoningRequest(
            request_id="r1",
            session_id="s1",
            user_query="What is on my screen?",
            modality=InputModality.MULTIMODAL,
            screen_context=None,
            context_items=[],
        )
    assert "Multimodal request requires visual context" in str(exc_info.value)


def test_invalid_result_empty_or_whitespace_fields():
    """Rejects ReasoningResult with empty core text fields."""
    with pytest.raises(ValidationError):
        ReasoningResult(
            response_id="   ",
            request_id="r1",
            session_id="s1",
            user_intent="test",
            response_text="Valid text",
            confidence_score=0.9,
            processing_time_ms=10.0,
        )

    with pytest.raises(ValidationError):
        ReasoningResult(
            response_id="res-1",
            request_id="r1",
            session_id="s1",
            user_intent="   ",
            response_text="Valid text",
            confidence_score=0.9,
            processing_time_ms=10.0,
        )

    with pytest.raises(ValidationError):
        ReasoningResult(
            response_id="res-1",
            request_id="r1",
            session_id="s1",
            user_intent="test",
            response_text="   \n\t ",
            confidence_score=0.9,
            processing_time_ms=10.0,
        )


def test_invalid_result_confidence_out_of_bounds():
    """Rejects confidence scores outside [0.0, 1.0]."""
    with pytest.raises(ValidationError):
        ReasoningResult(
            response_id="res-1",
            request_id="r1",
            session_id="s1",
            user_intent="test",
            response_text="Text",
            confidence_score=-0.05,
            processing_time_ms=10.0,
        )

    with pytest.raises(ValidationError):
        ReasoningResult(
            response_id="res-1",
            request_id="r1",
            session_id="s1",
            user_intent="test",
            response_text="Text",
            confidence_score=1.001,
            processing_time_ms=10.0,
        )


def test_invalid_result_processing_time_negative():
    """Rejects negative processing times."""
    with pytest.raises(ValidationError):
        ReasoningResult(
            response_id="res-1",
            request_id="r1",
            session_id="s1",
            user_intent="test",
            response_text="Text",
            confidence_score=0.9,
            processing_time_ms=-1.0,
        )


def test_invalid_result_tool_call_without_action_plan():
    """Rejects tool_call_required=True when action_plan is empty."""
    with pytest.raises(ValidationError) as exc_info:
        ReasoningResult(
            response_id="res-1",
            request_id="r1",
            session_id="s1",
            user_intent="test",
            response_text="Planning action",
            tool_call_required=True,
            action_plan=[],
            confidence_score=0.9,
            processing_time_ms=10.0,
        )
    assert "action_plan must contain at least one ActionStep" in str(exc_info.value)


def test_invalid_result_action_plan_without_tool_call_required():
    """Rejects populated action_plan when tool_call_required=False."""
    step = ActionStep(
        step_number=1,
        tool_name="tool_a",
        step_description="Perform action",
    )
    with pytest.raises(ValidationError) as exc_info:
        ReasoningResult(
            response_id="res-1",
            request_id="r1",
            session_id="s1",
            user_intent="test",
            response_text="Text",
            tool_call_required=False,
            action_plan=[step],
            confidence_score=0.9,
            processing_time_ms=10.0,
        )
    assert "tool_call_required must be True" in str(exc_info.value)


def test_invalid_result_non_sequential_action_steps():
    """Rejects action plans with gaps or non-sequential step numbers."""
    step1 = ActionStep(step_number=1, tool_name="tool_1", step_description="Step 1")
    step3 = ActionStep(step_number=3, tool_name="tool_3", step_description="Step 3")

    with pytest.raises(ValidationError) as exc_info:
        ReasoningResult(
            response_id="res-1",
            request_id="r1",
            session_id="s1",
            user_intent="test",
            response_text="Executing",
            tool_call_required=True,
            action_plan=[step1, step3],
            confidence_score=0.9,
            processing_time_ms=10.0,
        )
    assert "ActionStep sequence numbers must be contiguous" in str(exc_info.value)


def test_invalid_result_category_c_without_approval():
    """PRD Sec 18: Rejects Category C (Sensitive) if requires_user_approval is False."""
    step = ActionStep(
        step_number=1,
        tool_name="move_file",
        step_description="Move sensitive file",
        risk_level=RiskLevel.CATEGORY_C_SENSITIVE,
        requires_approval=True,
    )
    with pytest.raises(ValidationError) as exc_info:
        ReasoningResult(
            response_id="res-1",
            request_id="r1",
            session_id="s1",
            user_intent="file_move",
            response_text="Moving file without consent",
            tool_call_required=True,
            action_plan=[step],
            risk_level=RiskLevel.CATEGORY_C_SENSITIVE,
            requires_user_approval=False,  # ILLEGAL: Bypassing approval
            approval_prompt="Move file?",
            confidence_score=0.9,
            processing_time_ms=10.0,
        )
    assert "requires_user_approval must be True for sensitive/destructive operations" in str(exc_info.value)


def test_invalid_result_category_d_without_approval():
    """PRD Sec 18: Rejects Category D (Destructive) if requires_user_approval is False."""
    step = ActionStep(
        step_number=1,
        tool_name="delete_database",
        step_description="Wipe database",
        risk_level=RiskLevel.CATEGORY_D_HIGH_RISK_DESTRUCTIVE,
        requires_approval=True,
    )
    with pytest.raises(ValidationError) as exc_info:
        ReasoningResult(
            response_id="res-1",
            request_id="r1",
            session_id="s1",
            user_intent="destroy_data",
            response_text="Destroying data",
            tool_call_required=True,
            action_plan=[step],
            risk_level=RiskLevel.CATEGORY_D_HIGH_RISK_DESTRUCTIVE,
            requires_user_approval=False,  # ILLEGAL
            approval_prompt="Destroy?",
            confidence_score=0.95,
            processing_time_ms=10.0,
        )
    assert "requires_user_approval must be True" in str(exc_info.value)


def test_invalid_result_sensitive_missing_approval_prompt():
    """Rejects sensitive operations missing an approval prompt."""
    step = ActionStep(
        step_number=1,
        tool_name="write_config",
        step_description="Update settings",
        risk_level=RiskLevel.CATEGORY_C_SENSITIVE,
        requires_approval=True,
    )
    with pytest.raises(ValidationError) as exc_info:
        ReasoningResult(
            response_id="res-1",
            request_id="r1",
            session_id="s1",
            user_intent="config_change",
            response_text="Modifying config",
            tool_call_required=True,
            action_plan=[step],
            risk_level=RiskLevel.CATEGORY_C_SENSITIVE,
            requires_user_approval=True,
            approval_prompt=None,  # Missing required prompt
            confidence_score=0.9,
            processing_time_ms=10.0,
        )
    assert "approval_prompt is required" in str(exc_info.value)


def test_invalid_result_category_a_with_approval():
    """PRD Sec 18: Category A (Informational) must never require approval."""
    with pytest.raises(ValidationError) as exc_info:
        ReasoningResult(
            response_id="res-1",
            request_id="r1",
            session_id="s1",
            user_intent="explain_concept",
            response_text="Here is the explanation.",
            risk_level=RiskLevel.CATEGORY_A_INFORMATIONAL,
            requires_user_approval=True,  # ILLEGAL: Informational cannot require approval
            confidence_score=0.9,
            processing_time_ms=10.0,
        )
    assert "Informational (Category A) responses must not require user approval" in str(exc_info.value)


def test_invalid_result_category_a_with_approval_prompt():
    """Category A responses must not provide an approval prompt."""
    with pytest.raises(ValidationError) as exc_info:
        ReasoningResult(
            response_id="res-1",
            request_id="r1",
            session_id="s1",
            user_intent="explain_concept",
            response_text="Here is the explanation.",
            risk_level=RiskLevel.CATEGORY_A_INFORMATIONAL,
            requires_user_approval=False,
            approval_prompt="Do you want to see this explanation?",  # Invalid for Cat A
            confidence_score=0.9,
            processing_time_ms=10.0,
        )
    assert "approval_prompt must not be set for Category A" in str(exc_info.value)


def test_invalid_result_risk_level_lower_than_action_steps():
    """Rejects overall result having lower risk level than its individual action steps."""
    step = ActionStep(
        step_number=1,
        tool_name="delete_all",
        step_description="Purge directory",
        risk_level=RiskLevel.CATEGORY_D_HIGH_RISK_DESTRUCTIVE,
        requires_approval=True,
    )
    with pytest.raises(ValidationError) as exc_info:
        ReasoningResult(
            response_id="res-1",
            request_id="r1",
            session_id="s1",
            user_intent="delete",
            response_text="Deleting directory",
            tool_call_required=True,
            action_plan=[step],
            risk_level=RiskLevel.CATEGORY_A_INFORMATIONAL,  # Downgrading risk is illegal
            requires_user_approval=False,
            confidence_score=0.9,
            processing_time_ms=10.0,
        )
    assert "Overall risk_level" in str(exc_info.value)


def test_invalid_action_step_sensitive_without_approval():
    """ActionStep itself must enforce requires_approval=True for Category C and D."""
    with pytest.raises(ValidationError) as exc_info:
        ActionStep(
            step_number=1,
            tool_name="rm_file",
            step_description="Remove file",
            risk_level=RiskLevel.CATEGORY_C_SENSITIVE,
            requires_approval=False,  # Must be True
        )
    assert "must require approval" in str(exc_info.value)


# ===========================================================================
# 3. EDGE CASES
# ===========================================================================

def test_edge_case_whitespace_stripping():
    """Validates that leading and trailing whitespaces are cleanly stripped."""
    req = ReasoningRequest(
        request_id="  req-space-1  ",
        session_id="  sess-space-1  ",
        user_query="   What is Python?   ",
    )
    assert req.request_id == "req-space-1"
    assert req.session_id == "sess-space-1"
    assert req.user_query == "What is Python?"


def test_edge_case_empty_approval_prompt_coerced_to_none():
    """Whitespace-only approval prompt on informational response is coerced to None."""
    res = ReasoningResult(
        response_id="res-1",
        request_id="r1",
        session_id="s1",
        user_intent="test",
        response_text="Answering question.",
        risk_level=RiskLevel.CATEGORY_A_INFORMATIONAL,
        requires_user_approval=False,
        approval_prompt="   \t  ",  # Coerced to None
        confidence_score=0.9,
        processing_time_ms=10.0,
    )
    assert res.approval_prompt is None


def test_edge_case_approval_prompt_boundary_length():
    """Prompt of exactly 500 characters is valid; 501 characters is rejected."""
    step = ActionStep(
        step_number=1,
        tool_name="sensitive_action",
        step_description="Perform action",
        risk_level=RiskLevel.CATEGORY_C_SENSITIVE,
        requires_approval=True,
    )
    prompt_500 = "x" * 500
    res = ReasoningResult(
        response_id="res-500",
        request_id="r1",
        session_id="s1",
        user_intent="test",
        response_text="Sensitive action",
        tool_call_required=True,
        action_plan=[step],
        risk_level=RiskLevel.CATEGORY_C_SENSITIVE,
        requires_user_approval=True,
        approval_prompt=prompt_500,
        confidence_score=0.9,
        processing_time_ms=10.0,
        status=ExecutionStatus.NEEDS_APPROVAL,
    )
    assert len(res.approval_prompt) == 500

    # 501 characters must fail
    with pytest.raises(ValidationError):
        ReasoningResult(
            response_id="res-501",
            request_id="r1",
            session_id="s1",
            user_intent="test",
            response_text="Sensitive action",
            tool_call_required=True,
            action_plan=[step],
            risk_level=RiskLevel.CATEGORY_C_SENSITIVE,
            requires_user_approval=True,
            approval_prompt="x" * 501,
            confidence_score=0.9,
            processing_time_ms=10.0,
            status=ExecutionStatus.NEEDS_APPROVAL,
        )


def test_edge_case_confidence_boundary_values():
    """Confidence exactly 0.0 and 1.0 are valid."""
    res_zero = ReasoningResult(
        response_id="res-c0",
        request_id="r1",
        session_id="s1",
        user_intent="uncertain_intent",
        response_text="I am not confident in this answer.",
        confidence_score=0.0,
        processing_time_ms=0.0,
    )
    assert res_zero.confidence_score == 0.0
    assert res_zero.processing_time_ms == 0.0

    res_max = ReasoningResult(
        response_id="res-c1",
        request_id="r1",
        session_id="s1",
        user_intent="certain_intent",
        response_text="I am completely confident.",
        confidence_score=1.0,
        processing_time_ms=15.0,
    )
    assert res_max.confidence_score == 1.0
