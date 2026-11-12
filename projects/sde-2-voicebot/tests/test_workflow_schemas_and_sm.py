"""
Unit tests for Workflow schemas and State Machine.
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M
"""

import pytest
from datetime import datetime
from pydantic import ValidationError

from src.workflow.schemas import (
    ApprovalRequest,
    ApprovalStatus,
    RiskLevel,
    StepStatus,
    ToolFailureBehavior,
    ToolSpec,
    WorkflowPlan,
    WorkflowResult,
    WorkflowState,
    WorkflowStep,
)
from src.workflow.state_machine import (
    InvalidStateTransitionError,
    WorkflowStateMachine,
)


# ============================================================================
# ToolSpec Tests
# ============================================================================

def test_tool_spec_creation_valid():
    tool = ToolSpec(
        name="read_file",
        purpose="Reads text content from a specified file path",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"content": {"type": "string"}}},
        permission_requirements=["fs:read"],
        risk_level=RiskLevel.INFORMATIONAL,
        failure_behavior=ToolFailureBehavior.FAIL_WORKFLOW,
    )
    assert tool.name == "read_file"
    assert tool.risk_level == RiskLevel.INFORMATIONAL
    assert tool.failure_behavior == ToolFailureBehavior.FAIL_WORKFLOW


def test_tool_spec_empty_name_fails():
    with pytest.raises(ValidationError):
        ToolSpec(name="   ", purpose="Empty tool")


# ============================================================================
# WorkflowStep Tests
# ============================================================================

def test_workflow_step_consequential_auto_approval():
    """Sensitive and Destructive steps must automatically enforce requires_approval = True."""
    # Sensitive step with requires_approval=False explicitly passed -> must be overridden to True
    sensitive_step = WorkflowStep(
        tool_name="modify_file",
        arguments={"path": "main.py"},
        description="Modify code",
        risk_level=RiskLevel.SENSITIVE,
        requires_approval=False,
    )
    assert sensitive_step.requires_approval is True

    # Destructive step
    destructive_step = WorkflowStep(
        tool_name="delete_file",
        arguments={"path": "old.py"},
        description="Delete file",
        risk_level=RiskLevel.DESTRUCTIVE,
    )
    assert destructive_step.requires_approval is True

    # Informational step does not require approval by default
    info_step = WorkflowStep(
        tool_name="search_files",
        arguments={"pattern": "*.py"},
        description="Search repo",
        risk_level=RiskLevel.INFORMATIONAL,
    )
    assert info_step.requires_approval is False


# ============================================================================
# WorkflowPlan Validation Tests
# ============================================================================

def test_workflow_plan_valid():
    step1 = WorkflowStep(
        step_id="step-1",
        tool_name="search_files",
        description="Find files",
        risk_level=RiskLevel.INFORMATIONAL,
    )
    step2 = WorkflowStep(
        step_id="step-2",
        tool_name="read_file",
        description="Read file",
        depends_on=["step-1"],
        risk_level=RiskLevel.INFORMATIONAL,
    )
    plan = WorkflowPlan(
        session_id="sess-001",
        correlation_id="corr-101",
        title="Find and Read File",
        steps=[step1, step2],
    )
    assert plan.state == WorkflowState.DRAFT
    assert len(plan.steps) == 2
    assert plan.steps[1].depends_on == ["step-1"]


def test_workflow_plan_duplicate_step_id_rejected():
    step1 = WorkflowStep(step_id="dup-id", tool_name="tool_a", description="First")
    step2 = WorkflowStep(step_id="dup-id", tool_name="tool_b", description="Second")
    with pytest.raises(ValidationError, match="Duplicate step_id detected"):
        WorkflowPlan(
            session_id="sess-1",
            correlation_id="corr-1",
            title="Duplicate Steps Plan",
            steps=[step1, step2],
        )


def test_workflow_plan_non_existent_dependency_rejected():
    step = WorkflowStep(
        step_id="step-1",
        tool_name="tool_a",
        description="First",
        depends_on=["step-999"],
    )
    with pytest.raises(ValidationError, match="depends on non-existent step"):
        WorkflowPlan(
            session_id="sess-1",
            correlation_id="corr-1",
            title="Invalid Dependency",
            steps=[step],
        )


def test_workflow_plan_self_dependency_rejected():
    step = WorkflowStep(
        step_id="step-1",
        tool_name="tool_a",
        description="Self loop",
        depends_on=["step-1"],
    )
    with pytest.raises(ValidationError, match="cannot depend on itself"):
        WorkflowPlan(
            session_id="sess-1",
            correlation_id="corr-1",
            title="Self Dependency",
            steps=[step],
        )


# ============================================================================
# ApprovalRequest & WorkflowResult Tests
# ============================================================================

def test_approval_request_model():
    req = ApprovalRequest(
        session_id="sess-123",
        correlation_id="corr-456",
        plan_id="plan-789",
        step_id="step-002",
        tool_name="delete_file",
        risk_level=RiskLevel.DESTRUCTIVE,
        action_summary="Permanently delete old logs",
        target_resources=["/logs/old.log"],
    )
    assert req.status == ApprovalStatus.PENDING
    assert req.risk_level == RiskLevel.DESTRUCTIVE
    assert "/logs/old.log" in req.target_resources


def test_workflow_result_model():
    res = WorkflowResult(
        plan_id="plan-1",
        session_id="sess-1",
        correlation_id="corr-1",
        final_state=WorkflowState.SUCCEEDED,
        step_results={"step-1": {"found": 3}},
        started_at=datetime.now(),
    )
    assert res.final_state == WorkflowState.SUCCEEDED
    assert res.step_results["step-1"]["found"] == 3


# ============================================================================
# WorkflowStateMachine Tests
# ============================================================================

def test_state_machine_happy_path():
    plan = WorkflowPlan(
        session_id="sess-1",
        correlation_id="corr-1",
        title="Happy path workflow",
        steps=[
            WorkflowStep(step_id="s1", tool_name="search", description="Search")
        ],
    )
    sm = WorkflowStateMachine(plan)
    assert sm.current_state == WorkflowState.DRAFT

    # DRAFT -> RUNNING
    sm.transition(WorkflowState.RUNNING, reason="Starting execution")
    assert sm.current_state == WorkflowState.RUNNING
    assert plan.state == WorkflowState.RUNNING

    # RUNNING -> PAUSED
    sm.transition(WorkflowState.PAUSED, reason="User requested pause")
    assert sm.current_state == WorkflowState.PAUSED

    # PAUSED -> RUNNING
    sm.transition(WorkflowState.RUNNING, reason="User resumed")
    assert sm.current_state == WorkflowState.RUNNING

    # RUNNING -> SUCCEEDED
    sm.transition(WorkflowState.SUCCEEDED, reason="All steps done")
    assert sm.current_state == WorkflowState.SUCCEEDED
    assert sm.is_terminal() is True
    assert len(sm.history) == 4


def test_state_machine_approval_and_rejection():
    plan = WorkflowPlan(
        session_id="sess-1",
        correlation_id="corr-1",
        title="Plan needing approval",
        steps=[
            WorkflowStep(step_id="s1", tool_name="delete_file", description="Delete", risk_level=RiskLevel.DESTRUCTIVE)
        ],
    )
    sm = WorkflowStateMachine(plan)

    # Initial readiness check transitions directly to AWAITING_APPROVAL because of destructive step
    target = sm.check_initial_readiness()
    assert target == WorkflowState.AWAITING_APPROVAL
    assert sm.current_state == WorkflowState.AWAITING_APPROVAL

    # Rejection of approval leads to CANCELLED (per non-negotiable PRD safety rule)
    sm.transition(WorkflowState.CANCELLED, reason="User rejected consequential operation")
    assert sm.current_state == WorkflowState.CANCELLED
    assert sm.is_terminal() is True


def test_state_machine_invalid_transition_raises():
    plan = WorkflowPlan(
        session_id="sess-1",
        correlation_id="corr-1",
        title="Invalid transition test",
        steps=[],
    )
    sm = WorkflowStateMachine(plan)

    # DRAFT directly to SUCCEEDED is invalid
    with pytest.raises(InvalidStateTransitionError, match="Cannot transition workflow from 'draft' to 'succeeded'"):
        sm.transition(WorkflowState.SUCCEEDED)

    # Transition to RUNNING
    sm.transition(WorkflowState.RUNNING)

    # Transition to terminal SUCCEEDED
    sm.transition(WorkflowState.SUCCEEDED)

    # Terminal state cannot transition to anything
    with pytest.raises(InvalidStateTransitionError, match="Cannot transition workflow from 'succeeded' to 'running'"):
        sm.transition(WorkflowState.RUNNING)
