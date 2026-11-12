"""
Tests for Invalid Plans and State Machine Transitions.
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M

Day 5-6 Deliverable:
Validates edge cases, invalid plans (cycles, missing deps, duplicates, invalid payloads),
and comprehensive state machine legal & illegal transitions per PRD Section 8 and 18.
"""

import pytest
from pydantic import ValidationError

from src.workflow.schemas import (
    RiskLevel,
    StepStatus,
    ToolSpec,
    WorkflowPlan,
    WorkflowState,
    WorkflowStep,
)
from src.workflow.state_machine import (
    InvalidStateTransitionError,
    WorkflowStateMachine,
)


# ============================================================================
# Invalid Plan Tests (Day 5-6)
# ============================================================================

def test_invalid_plan_empty_title():
    """Plan must have a non-empty title."""
    with pytest.raises(ValidationError):
        WorkflowPlan(
            session_id="sess-1",
            correlation_id="corr-1",
            # missing title
            steps=[],
        )


def test_invalid_plan_direct_cycle():
    """Two-step mutual dependency cycle (A -> B -> A) must be rejected."""
    step1 = WorkflowStep(
        step_id="step-a",
        tool_name="knowledge_search",
        description="Step A",
        depends_on=["step-b"],
    )
    step2 = WorkflowStep(
        step_id="step-b",
        tool_name="course_schedule",
        description="Step B",
        depends_on=["step-a"],
    )
    with pytest.raises(ValidationError, match="Cyclic dependency detected"):
        WorkflowPlan(
            session_id="sess-cycle",
            correlation_id="corr-cycle",
            title="Direct Cycle Plan",
            steps=[step1, step2],
        )


def test_invalid_plan_multi_step_cycle():
    """Three-step dependency cycle (A -> B -> C -> A) must be rejected."""
    step_a = WorkflowStep(step_id="step-a", tool_name="tool_1", description="A", depends_on=["step-c"])
    step_b = WorkflowStep(step_id="step-b", tool_name="tool_2", description="B", depends_on=["step-a"])
    step_c = WorkflowStep(step_id="step-c", tool_name="tool_3", description="C", depends_on=["step-b"])

    with pytest.raises(ValidationError, match="Cyclic dependency detected"):
        WorkflowPlan(
            session_id="sess-cycle3",
            correlation_id="corr-cycle3",
            title="3-Step Cycle Plan",
            steps=[step_a, step_b, step_c],
        )


def test_invalid_plan_missing_tool_name():
    """Step with empty or missing tool_name must fail validation."""
    with pytest.raises(ValidationError):
        WorkflowStep(
            step_id="s1",
            tool_name=None,  # type: ignore
            description="Missing tool",
        )


def test_invalid_plan_non_existent_dependency():
    """Step pointing to a non-existent dependency step_id must fail validation."""
    step1 = WorkflowStep(step_id="s1", tool_name="t1", description="Step 1", depends_on=["ghost-step"])
    with pytest.raises(ValidationError, match="depends on non-existent step 'ghost-step'"):
        WorkflowPlan(
            session_id="sess-missing",
            correlation_id="corr-missing",
            title="Missing Dependency Plan",
            steps=[step1],
        )


def test_invalid_plan_self_dependency():
    """Step depending on itself must fail validation."""
    step1 = WorkflowStep(step_id="loop-step", tool_name="t1", description="Self loop", depends_on=["loop-step"])
    with pytest.raises(ValidationError, match="cannot depend on itself"):
        WorkflowPlan(
            session_id="sess-loop",
            correlation_id="corr-loop",
            title="Self Loop Plan",
            steps=[step1],
        )


def test_invalid_plan_duplicate_step_ids():
    """Multiple steps sharing the same step_id must fail validation."""
    step1 = WorkflowStep(step_id="shared-id", tool_name="t1", description="Step 1")
    step2 = WorkflowStep(step_id="shared-id", tool_name="t2", description="Step 2")
    with pytest.raises(ValidationError, match="Duplicate step_id detected"):
        WorkflowPlan(
            session_id="sess-dup",
            correlation_id="corr-dup",
            title="Duplicate Step IDs",
            steps=[step1, step2],
        )


# ============================================================================
# State Machine Legal & Illegal Transitions Tests (Day 5-6)
# ============================================================================

def create_sample_plan(initial_state: WorkflowState = WorkflowState.DRAFT) -> WorkflowPlan:
    return WorkflowPlan(
        session_id="sess-sm",
        correlation_id="corr-sm",
        title="State Machine Test Plan",
        state=initial_state,
        steps=[
            WorkflowStep(step_id="s1", tool_name="knowledge_search", description="Search"),
        ],
    )


def test_state_machine_all_legal_transitions():
    """Verifies all explicitly allowed transitions from the PRD matrix."""
    # 1. DRAFT -> AWAITING_APPROVAL
    p1 = create_sample_plan(WorkflowState.DRAFT)
    sm1 = WorkflowStateMachine(p1)
    sm1.transition(WorkflowState.AWAITING_APPROVAL, reason="Approval needed")
    assert sm1.current_state == WorkflowState.AWAITING_APPROVAL

    # 2. DRAFT -> RUNNING
    p2 = create_sample_plan(WorkflowState.DRAFT)
    sm2 = WorkflowStateMachine(p2)
    sm2.transition(WorkflowState.RUNNING)
    assert sm2.current_state == WorkflowState.RUNNING

    # 3. DRAFT -> CANCELLED
    p3 = create_sample_plan(WorkflowState.DRAFT)
    sm3 = WorkflowStateMachine(p3)
    sm3.transition(WorkflowState.CANCELLED)
    assert sm3.current_state == WorkflowState.CANCELLED

    # 4. AWAITING_APPROVAL -> RUNNING (Approved)
    p4 = create_sample_plan(WorkflowState.AWAITING_APPROVAL)
    sm4 = WorkflowStateMachine(p4)
    sm4.transition(WorkflowState.RUNNING)
    assert sm4.current_state == WorkflowState.RUNNING

    # 5. AWAITING_APPROVAL -> CANCELLED (Rejected)
    p5 = create_sample_plan(WorkflowState.AWAITING_APPROVAL)
    sm5 = WorkflowStateMachine(p5)
    sm5.transition(WorkflowState.CANCELLED)
    assert sm5.current_state == WorkflowState.CANCELLED

    # 6. AWAITING_APPROVAL -> FAILED (Timeout / Expired)
    p6 = create_sample_plan(WorkflowState.AWAITING_APPROVAL)
    sm6 = WorkflowStateMachine(p6)
    sm6.transition(WorkflowState.FAILED)
    assert sm6.current_state == WorkflowState.FAILED

    # 7. RUNNING -> PAUSED -> RUNNING
    p7 = create_sample_plan(WorkflowState.RUNNING)
    sm7 = WorkflowStateMachine(p7)
    sm7.transition(WorkflowState.PAUSED)
    assert sm7.current_state == WorkflowState.PAUSED
    sm7.transition(WorkflowState.RUNNING)
    assert sm7.current_state == WorkflowState.RUNNING

    # 8. RUNNING -> AWAITING_APPROVAL (Consequential step encountered mid-flight)
    sm7.transition(WorkflowState.AWAITING_APPROVAL)
    assert sm7.current_state == WorkflowState.AWAITING_APPROVAL

    # 9. RUNNING -> SUCCEEDED (Terminal)
    p8 = create_sample_plan(WorkflowState.RUNNING)
    sm8 = WorkflowStateMachine(p8)
    sm8.transition(WorkflowState.SUCCEEDED)
    assert sm8.current_state == WorkflowState.SUCCEEDED
    assert sm8.is_terminal() is True

    # 10. RUNNING -> FAILED (Terminal)
    p9 = create_sample_plan(WorkflowState.RUNNING)
    sm9 = WorkflowStateMachine(p9)
    sm9.transition(WorkflowState.FAILED)
    assert sm9.current_state == WorkflowState.FAILED
    assert sm9.is_terminal() is True

    # 11. PAUSED -> CANCELLED (Terminal)
    p10 = create_sample_plan(WorkflowState.PAUSED)
    sm10 = WorkflowStateMachine(p10)
    sm10.transition(WorkflowState.CANCELLED)
    assert sm10.current_state == WorkflowState.CANCELLED
    assert sm10.is_terminal() is True


def test_state_machine_illegal_draft_transitions():
    """DRAFT cannot transition directly to SUCCEEDED, PAUSED, or FAILED."""
    p = create_sample_plan(WorkflowState.DRAFT)
    sm = WorkflowStateMachine(p)

    for invalid_target in [WorkflowState.SUCCEEDED, WorkflowState.PAUSED, WorkflowState.FAILED]:
        with pytest.raises(InvalidStateTransitionError):
            sm.transition(invalid_target)


def test_state_machine_illegal_awaiting_approval_transitions():
    """AWAITING_APPROVAL cannot jump straight to SUCCEEDED or PAUSED."""
    p = create_sample_plan(WorkflowState.AWAITING_APPROVAL)
    sm = WorkflowStateMachine(p)

    for invalid_target in [WorkflowState.SUCCEEDED, WorkflowState.PAUSED, WorkflowState.DRAFT]:
        with pytest.raises(InvalidStateTransitionError):
            sm.transition(invalid_target)


def test_state_machine_terminal_states_immutable():
    """SUCCEEDED, FAILED, and CANCELLED cannot transition anywhere."""
    for terminal_state in [WorkflowState.SUCCEEDED, WorkflowState.FAILED, WorkflowState.CANCELLED]:
        p = create_sample_plan(terminal_state)
        sm = WorkflowStateMachine(p)
        assert sm.is_terminal() is True

        for any_state in WorkflowState:
            with pytest.raises(InvalidStateTransitionError):
                sm.transition(any_state)


def test_state_machine_audit_trail_logging():
    """Audit events record precise timestamp, previous and next state, and reason."""
    plan = create_sample_plan(WorkflowState.DRAFT)
    sm = WorkflowStateMachine(plan)

    sm.transition(WorkflowState.RUNNING, reason="Initialization")
    sm.transition(WorkflowState.PAUSED, reason="Resource contention")
    sm.transition(WorkflowState.RUNNING, reason="Contention resolved")
    sm.transition(WorkflowState.SUCCEEDED, reason="Complete")

    assert len(sm.history) == 4
    assert sm.history[0].from_state == WorkflowState.DRAFT
    assert sm.history[0].to_state == WorkflowState.RUNNING
    assert sm.history[0].reason == "Initialization"

    assert sm.history[1].from_state == WorkflowState.RUNNING
    assert sm.history[1].to_state == WorkflowState.PAUSED
    assert sm.history[1].reason == "Resource contention"

    assert sm.history[3].to_state == WorkflowState.SUCCEEDED
