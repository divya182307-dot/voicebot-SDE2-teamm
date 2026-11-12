"""
Week 2 Policy, Plan Validation, Approval Expiry & Safe Executor Tests.
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M

Days 8-14 Deliverable:
Validates all Week 2 Acceptance Criteria:
1. Plan validator: dependency cycles and missing dependencies rejected with clear errors
2. Allow-listed tool registry: unknown tools, invalid argument types, and permission scopes enforced
3. Approval logic: rejection and expiry guarantee NO tool execution + safe audit events recorded
4. Executor timeouts: step timeout enforcement
5. Bounded retries: retries strictly bounded and ONLY executed for idempotent calls
6. Safe cancellation: immediate cancellation preventing downstream tool calls
"""

import time
from datetime import datetime, timedelta, timezone
import pytest

from src.workflow.schemas import (
    ApprovalRequest,
    ApprovalStatus,
    RetryPolicy,
    RiskLevel,
    StepStatus,
    ToolSpec,
    WorkflowPlan,
    WorkflowResult,
    WorkflowState,
    WorkflowStep,
)
from src.workflow.tools import (
    BaseTool,
    MockCourseScheduleTool,
    MockKnowledgeSearchTool,
    ToolRegistry,
)
from src.workflow.validator import (
    PlanValidationError,
    PlanValidator,
)
from src.workflow.executor import WorkflowExecutor


# ============================================================================
# 1. Plan Validator & Dependency / Cycle Tests (Days 8-9)
# ============================================================================

def test_validator_rejects_missing_dependency():
    """Missing dependency is rejected with a clear descriptive error."""
    step = WorkflowStep(
        step_id="step-2",
        tool_name="knowledge_search",
        arguments={"query": "cs101"},
        description="Search info",
        depends_on=["non_existent_step_1"],
    )
    plan = WorkflowPlan.model_construct(
        session_id="sess-val-1",
        correlation_id="corr-val-1",
        title="Missing Dependency Plan",
        steps=[step],
    )
    validator = PlanValidator()
    with pytest.raises(PlanValidationError) as exc_info:
        validator.validate_dependencies_and_cycles(plan)
    assert "depends on non-existent step 'non_existent_step_1'" in str(exc_info.value)
    assert exc_info.value.step_id == "step-2"


def test_validator_rejects_cycles_with_clear_error():
    """Dependency cycles are detected and rejected with clear error path."""
    step1 = WorkflowStep(
        step_id="step-a",
        tool_name="knowledge_search",
        arguments={"query": "a"},
        description="Step A",
        depends_on=["step-b"],
    )
    step2 = WorkflowStep(
        step_id="step-b",
        tool_name="course_schedule",
        arguments={"course_code": "CS101"},
        description="Step B",
        depends_on=["step-a"],
    )
    plan = WorkflowPlan.model_construct(
        session_id="sess-val-2",
        correlation_id="corr-val-2",
        title="Direct Cycle Plan",
        steps=[step1, step2],
    )
    validator = PlanValidator()
    with pytest.raises(PlanValidationError) as exc_info:
        validator.validate_dependencies_and_cycles(plan)
    assert "Cyclic dependency detected" in str(exc_info.value)


def test_validator_rejects_unknown_tool():
    """Steps referencing unapproved or unknown tools are rejected."""
    step = WorkflowStep(
        step_id="step-unregistered",
        tool_name="unregistered_external_tool",
        arguments={"cmd": "do_something"},
        description="Run unknown tool",
    )
    plan = WorkflowPlan(
        session_id="sess-val-3",
        correlation_id="corr-val-3",
        title="Unknown Tool Plan",
        steps=[step],
    )
    validator = PlanValidator()
    with pytest.raises(PlanValidationError) as exc_info:
        validator.validate_tools_and_arguments(plan)
    assert "references unknown tool 'unregistered_external_tool' not in allow-list" in str(exc_info.value)


def test_validator_rejects_invalid_argument_types():
    """Tools validate argument types (e.g. integer instead of string)."""
    step = WorkflowStep(
        step_id="step-bad-args",
        tool_name="course_schedule",
        # course_code must be a string, not an integer
        arguments={"course_code": 101},
        description="Look up schedule with bad arg type",
    )
    plan = WorkflowPlan(
        session_id="sess-val-4",
        correlation_id="corr-val-4",
        title="Bad Arg Type Plan",
        steps=[step],
    )
    validator = PlanValidator()
    with pytest.raises(PlanValidationError) as exc_info:
        validator.validate_tools_and_arguments(plan)
    assert "must be a string" in str(exc_info.value)


def test_validator_enforces_permission_scopes():
    """Caller lacking required tool permissions is rejected."""
    step = WorkflowStep(
        step_id="step-perm",
        tool_name="knowledge_search",  # Requires kb:read
        arguments={"query": "tuition"},
        description="Query knowledge base",
    )
    plan = WorkflowPlan(
        session_id="sess-val-5",
        correlation_id="corr-val-5",
        title="Permission Scopes Plan",
        steps=[step],
    )
    # Caller only holds schedule:read, lacking kb:read
    validator = PlanValidator(granted_permissions=["schedule:read"])
    with pytest.raises(PlanValidationError) as exc_info:
        validator.validate_permission_scopes(plan)
    assert "requires permission 'kb:read'" in str(exc_info.value)


# ============================================================================
# 2. Approval Logic, Rejection & Expiry Tests (Days 10-11)
# ============================================================================

def test_approval_rejection_guarantees_no_execution_and_audit_event():
    """Rejection strictly prevents tool execution and records safe audit event."""
    execution_flag = {"executed": False}

    class SpySensitiveTool(BaseTool):
        def __init__(self):
            super().__init__(
                ToolSpec(
                    name="spy_sensitive_tool",
                    purpose="Spy tool to check if execution happens",
                    risk_level=RiskLevel.SENSITIVE,
                    input_schema={"type": "object", "properties": {"val": {"type": "string"}}},
                )
            )
        def execute(self, arguments):
            execution_flag["executed"] = True
            return {"status": "executed"}

    registry = ToolRegistry()
    registry.register(SpySensitiveTool())

    step = WorkflowStep(
        step_id="step-sensitive",
        tool_name="spy_sensitive_tool",
        arguments={"val": "data"},
        description="Sensitive modification",
        risk_level=RiskLevel.SENSITIVE,
    )
    plan = WorkflowPlan(
        session_id="sess-rej-1",
        correlation_id="corr-rej-1",
        title="Reject Test Plan",
        steps=[step],
    )

    executor = WorkflowExecutor(plan, registry=registry)
    result = executor.run()
    assert result is None
    assert executor.current_state == WorkflowState.AWAITING_APPROVAL
    assert execution_flag["executed"] is False

    # Reject request
    approval_id = list(executor.pending_approvals.keys())[0]
    final_res = executor.reject_request(approval_id, reason="Security review denied access")

    # Guarantees:
    assert final_res.final_state == WorkflowState.CANCELLED
    assert executor.current_state == WorkflowState.CANCELLED
    assert execution_flag["executed"] is False  # ZERO tool execution!
    assert step.status == StepStatus.CANCELLED
    assert "Security review denied access" in step.error_message

    # Verify audit event
    rej_events = [e for e in executor.events if e.event_type == "APPROVAL_REJECTED"]
    assert len(rej_events) == 1
    assert "Tool execution prevented" in rej_events[0].message


def test_approval_expiry_guarantees_no_execution_and_audit_event():
    """Approval expiry strictly prevents tool execution and records safe audit event."""
    executed = False

    class MockSensitiveAction(BaseTool):
        def __init__(self):
            super().__init__(
                ToolSpec(
                    name="sensitive_action",
                    purpose="Sensitive action",
                    risk_level=RiskLevel.SENSITIVE,
                )
            )
        def execute(self, arguments):
            nonlocal executed
            executed = True
            return {"status": "done"}

    registry = ToolRegistry()
    registry.register(MockSensitiveAction())

    step = WorkflowStep(
        step_id="step-exp",
        tool_name="sensitive_action",
        description="Perform sensitive action",
        risk_level=RiskLevel.SENSITIVE,
    )
    plan = WorkflowPlan(
        session_id="sess-exp-1",
        correlation_id="corr-exp-1",
        title="Expiry Test Plan",
        steps=[step],
    )

    # Short TTL for approval
    executor = WorkflowExecutor(plan, registry=registry, default_approval_ttl_seconds=0.01)
    executor.run()
    assert executor.current_state == WorkflowState.AWAITING_APPROVAL
    assert executed is False

    approval_id = list(executor.pending_approvals.keys())[0]
    appr_req = executor.pending_approvals[approval_id]

    # Advance time to force expiration
    appr_req.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert appr_req.is_expired() is True

    # Calling expire_request
    final_res = executor.expire_request(approval_id, reason="Approval window timed out (300s TTL)")

    # Guarantees
    assert final_res.final_state == WorkflowState.CANCELLED
    assert executor.current_state == WorkflowState.CANCELLED
    assert executed is False  # ZERO tool execution!
    assert step.status == StepStatus.CANCELLED

    # Verify audit event
    exp_events = [e for e in executor.events if e.event_type == "APPROVAL_EXPIRED"]
    assert len(exp_events) == 1
    assert "Tool execution strictly prevented" in exp_events[0].message


def test_approving_expired_request_refuses_execution():
    """Attempting to approve an expired request refuses approval and prevents execution."""
    step = WorkflowStep(
        step_id="step-late-appr",
        tool_name="course_schedule",
        arguments={"course_code": "CS101"},
        description="Late schedule check",
        risk_level=RiskLevel.SENSITIVE,
    )
    plan = WorkflowPlan(
        session_id="sess-late-1",
        correlation_id="corr-late-1",
        title="Late Approval Plan",
        steps=[step],
    )
    executor = WorkflowExecutor(plan)
    executor.run()

    approval_id = list(executor.pending_approvals.keys())[0]
    # Manually expire
    executor.pending_approvals[approval_id].expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)

    # Approve call will detect expiration and refuse execution
    res = executor.approve_request(approval_id, approver="Late Admin")
    assert res is not None
    assert res.final_state == WorkflowState.CANCELLED
    assert executor.current_state == WorkflowState.CANCELLED
    assert step.status == StepStatus.CANCELLED


# ============================================================================
# 3. Timeouts, Bounded Retries & Cancellation Tests (Days 12-13)
# ============================================================================

def test_executor_enforces_step_timeout():
    """Step execution exceeding timeout_seconds is halted with TimeoutError."""
    class SlowMockTool(BaseTool):
        def __init__(self):
            super().__init__(
                ToolSpec(
                    name="slow_tool",
                    purpose="Simulates slow response",
                    risk_level=RiskLevel.INFORMATIONAL,
                )
            )
        def execute(self, arguments):
            time.sleep(0.3)
            return {"status": "finished"}

    registry = ToolRegistry()
    registry.register(SlowMockTool())

    step = WorkflowStep(
        step_id="step-timeout",
        tool_name="slow_tool",
        description="Slow step",
        timeout_seconds=0.05,  # 50ms timeout < 300ms sleep
    )
    plan = WorkflowPlan(
        session_id="sess-to-1",
        correlation_id="corr-to-1",
        title="Timeout Plan",
        steps=[step],
    )
    executor = WorkflowExecutor(plan, registry=registry)
    result = executor.run()

    assert result is not None
    assert result.final_state == WorkflowState.FAILED
    assert executor.current_state == WorkflowState.FAILED
    assert step.status == StepStatus.FAILED
    assert "timed out after 0.05 seconds" in step.error_message


def test_bounded_retries_for_idempotent_step():
    """Idempotent step retries up to bounded max_retries upon failure."""
    calls = 0

    class FlakyIdempotentTool(BaseTool):
        def __init__(self):
            super().__init__(
                ToolSpec(
                    name="flaky_idempotent",
                    purpose="Fails twice then succeeds",
                    risk_level=RiskLevel.INFORMATIONAL,
                )
            )
        def execute(self, arguments):
            nonlocal calls
            calls += 1
            if calls < 3:
                raise ConnectionError(f"Transient error on call {calls}")
            return {"status": "recovered", "calls": calls}

    registry = ToolRegistry()
    registry.register(FlakyIdempotentTool())

    step = WorkflowStep(
        step_id="step-retry-ok",
        tool_name="flaky_idempotent",
        description="Flaky idempotent step",
        is_idempotent=True,
        retry_policy=RetryPolicy(max_retries=3, backoff_seconds=0.01),
    )
    plan = WorkflowPlan(
        session_id="sess-ret-1",
        correlation_id="corr-ret-1",
        title="Bounded Retry Plan",
        steps=[step],
    )
    executor = WorkflowExecutor(plan, registry=registry)
    result = executor.run()

    assert result is not None
    assert result.final_state == WorkflowState.SUCCEEDED
    assert calls == 3  # Failed 2 times, succeeded on 3rd attempt
    assert step.status == StepStatus.SUCCEEDED

    retry_events = [e for e in executor.events if e.event_type == "STEP_RETRY_ATTEMPT"]
    assert len(retry_events) == 2


def test_retries_strictly_prohibited_for_non_idempotent_step():
    """Non-idempotent steps (is_idempotent=False) are NEVER retried, even if retry_policy is defined."""
    calls = 0

    class NonIdempotentTool(BaseTool):
        def __init__(self):
            super().__init__(
                ToolSpec(
                    name="non_idempotent_tool",
                    purpose="Non-idempotent action",
                    risk_level=RiskLevel.LOW_RISK,
                )
            )
        def execute(self, arguments):
            nonlocal calls
            calls += 1
            raise RuntimeError("Non-idempotent operation failed")

    registry = ToolRegistry()
    registry.register(NonIdempotentTool())

    step = WorkflowStep(
        step_id="step-non-idemp",
        tool_name="non_idempotent_tool",
        description="Charge credit card / mutate state",
        is_idempotent=False,  # Strictly non-idempotent!
        retry_policy=RetryPolicy(max_retries=5, backoff_seconds=0.01),
    )
    plan = WorkflowPlan(
        session_id="sess-no-ret",
        correlation_id="corr-no-ret",
        title="No Retry for Non-Idempotent Step",
        steps=[step],
    )
    executor = WorkflowExecutor(plan, registry=registry)
    result = executor.run()

    assert result is not None
    assert result.final_state == WorkflowState.FAILED
    assert calls == 1  # Exactly ONE call, NO retries!
    assert step.status == StepStatus.FAILED

    skipped_events = [e for e in executor.events if e.event_type == "RETRY_SKIPPED"]
    assert len(skipped_events) == 1
    assert "retries strictly prohibited" in skipped_events[0].message


def test_executor_cancellation_halts_workflow_safely():
    """Manual cancellation halts workflow immediately and cancels remaining steps."""
    step1 = WorkflowStep(
        step_id="s1",
        tool_name="knowledge_search",
        arguments={"query": "exam policy"},
        description="Step 1",
    )
    step2 = WorkflowStep(
        step_id="s2",
        tool_name="course_schedule",
        arguments={"course_code": "CS101"},
        description="Step 2",
        depends_on=["s1"],
    )
    plan = WorkflowPlan(
        session_id="sess-cancel-1",
        correlation_id="corr-cancel-1",
        title="Cancellation Plan",
        steps=[step1, step2],
    )
    executor = WorkflowExecutor(plan)
    res = executor.cancel(reason="Emergency user abort")

    assert res.final_state == WorkflowState.CANCELLED
    assert executor.current_state == WorkflowState.CANCELLED
    assert step1.status == StepStatus.CANCELLED
    assert step2.status == StepStatus.CANCELLED
    cancel_events = [e for e in executor.events if e.event_type == "WORKFLOW_CANCELLED"]
    assert len(cancel_events) == 1
