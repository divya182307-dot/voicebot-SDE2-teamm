"""
Week 3 Tests: Checkpoint & Resume, Failed-Step Recovery, Idempotency Keys.
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M

Days 15-16 Deliverables:
1. Checkpoint capture at step boundaries
2. Resuming execution from checkpoints without re-running completed steps
3. Failed-step recovery with argument correction
4. Idempotency key tracking and cache replay
"""

import time
from typing import Any, Dict
import pytest

from src.workflow.checkpoint import CheckpointManager, CheckpointStore
from src.workflow.executor import WorkflowExecutor
from src.workflow.idempotency import IdempotencyStore
from src.workflow.schemas import (
    RiskLevel,
    StepStatus,
    WorkflowPlan,
    WorkflowState,
    WorkflowStep,
)
from src.workflow.tools import BaseTool, ToolRegistry, ToolSpec


class CountingMockTool(BaseTool):
    """Harmless mock tool that tracks invocation count to verify execution prevention."""

    def __init__(self, name: str = "counting_tool"):
        self.invocations: int = 0
        self.last_arg: Any = None
        spec = ToolSpec(
            name=name,
            purpose="In-memory harmless counter tool for testing",
            input_schema={"type": "object", "properties": {"val": {"type": "string"}}},
            output_schema={"type": "object"},
            risk_level=RiskLevel.INFORMATIONAL,
        )
        super().__init__(spec)

    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self.invocations += 1
        self.last_arg = arguments.get("val")
        if arguments.get("fail"):
            raise ValueError(f"Forced mock failure: {arguments.get('fail')}")
        return {"status": "ok", "val": self.last_arg, "count": self.invocations}


@pytest.fixture
def mock_registry():
    registry = ToolRegistry()
    tool = CountingMockTool("counting_tool")
    registry.register(tool)
    return registry, tool


def test_checkpoint_capture_after_steps(mock_registry):
    """Verify that a checkpoint is captured after each step execution."""
    registry, tool = mock_registry
    cp_store = CheckpointStore()
    cp_mgr = CheckpointManager(cp_store)

    plan = WorkflowPlan(
        plan_id="plan-cp-1",
        session_id="sess-1",
        correlation_id="corr-1",
        title="Checkpoint Test Plan",
        steps=[
            WorkflowStep(
                step_id="step-1",
                tool_name="counting_tool",
                description="First step",
                arguments={"val": "alpha"},
            ),
            WorkflowStep(
                step_id="step-2",
                tool_name="counting_tool",
                description="Second step",
                arguments={"val": "beta"},
                depends_on=["step-1"],
            ),
        ],
    )

    executor = WorkflowExecutor(plan=plan, registry=registry, checkpoint_manager=cp_mgr)
    result = executor.run()

    assert result is not None
    assert result.final_state == WorkflowState.SUCCEEDED

    # Verify checkpoints were created
    checkpoints = cp_store.list_checkpoints(plan_id="plan-cp-1")
    assert len(checkpoints) >= 2

    latest_cp = cp_store.get_latest("plan-cp-1")
    assert latest_cp is not None
    assert "step-1" in latest_cp.completed_step_ids
    assert "step-2" in latest_cp.completed_step_ids
    assert latest_cp.workflow_state == WorkflowState.SUCCEEDED


def test_resume_does_not_rerun_completed_steps(mock_registry):
    """
    Acceptance Criteria 1: A workflow can checkpoint and resume;
    recovery does NOT re-run completed steps.
    """
    registry, tool = mock_registry
    cp_store = CheckpointStore()
    cp_mgr = CheckpointManager(cp_store)

    plan = WorkflowPlan(
        plan_id="plan-resume-1",
        session_id="sess-1",
        correlation_id="corr-1",
        title="Resume Skipping Test",
        steps=[
            WorkflowStep(
                step_id="step-1",
                tool_name="counting_tool",
                description="Step 1",
                arguments={"val": "one"},
            ),
            WorkflowStep(
                step_id="step-2",
                tool_name="counting_tool",
                description="Step 2 (consequential)",
                arguments={"val": "two"},
                risk_level=RiskLevel.SENSITIVE,  # Pauses for approval
                depends_on=["step-1"],
            ),
        ],
    )

    executor = WorkflowExecutor(plan=plan, registry=registry, checkpoint_manager=cp_mgr)
    executor.run()

    # Step 1 ran and succeeded; Step 2 paused awaiting approval
    assert tool.invocations == 1
    assert plan.steps[0].status == StepStatus.SUCCEEDED
    assert plan.steps[1].status == StepStatus.AWAITING_APPROVAL

    # Capture latest checkpoint
    latest_cp = cp_store.get_latest("plan-resume-1")
    assert latest_cp is not None
    assert latest_cp.completed_step_ids == ["step-1"]

    # Now create a fresh executor instance restored from the checkpoint
    fresh_plan = WorkflowPlan(
        plan_id="plan-resume-1",
        session_id="sess-1",
        correlation_id="corr-1",
        title="Resume Skipping Test",
        steps=[
            WorkflowStep(
                step_id="step-1",
                tool_name="counting_tool",
                description="Step 1",
                arguments={"val": "one"},
            ),
            WorkflowStep(
                step_id="step-2",
                tool_name="counting_tool",
                description="Step 2 (consequential)",
                arguments={"val": "two"},
                risk_level=RiskLevel.SENSITIVE,
                depends_on=["step-1"],
            ),
        ],
    )

    resumed_executor = WorkflowExecutor.from_checkpoint(
        checkpoint=latest_cp,
        plan=fresh_plan,
        registry=registry,
        checkpoint_manager=cp_mgr,
    )

    # Approve step-2
    appr_id = list(executor.pending_approvals.keys())[0]
    resumed_executor.pending_approvals[appr_id] = executor.pending_approvals[appr_id]
    resumed_executor.approve_request(appr_id, resume=True)

    # Step 1 must NOT have been re-run! Total invocations should now be exactly 2 (step 1 once, step 2 once)
    assert tool.invocations == 2
    assert fresh_plan.steps[0].status == StepStatus.SUCCEEDED
    assert fresh_plan.steps[1].status == StepStatus.SUCCEEDED


def test_failed_step_recovery_without_rerunning_prior_steps(mock_registry):
    """
    Acceptance Criteria 1: Failed-step recovery allows correcting a failure
    and resuming without re-executing completed predecessor steps.
    """
    registry, tool = mock_registry
    cp_store = CheckpointStore()
    cp_mgr = CheckpointManager(cp_store)

    plan = WorkflowPlan(
        plan_id="plan-recovery-1",
        session_id="sess-1",
        correlation_id="corr-1",
        title="Failed Step Recovery Plan",
        steps=[
            WorkflowStep(
                step_id="step-1",
                tool_name="counting_tool",
                description="Initial successful step",
                arguments={"val": "init"},
            ),
            WorkflowStep(
                step_id="step-2",
                tool_name="counting_tool",
                description="Step that fails initially",
                arguments={"val": "bad", "fail": "Invalid parameter"},
                depends_on=["step-1"],
            ),
            WorkflowStep(
                step_id="step-3",
                tool_name="counting_tool",
                description="Downstream step",
                arguments={"val": "final"},
                depends_on=["step-2"],
            ),
        ],
    )

    executor = WorkflowExecutor(plan=plan, registry=registry, checkpoint_manager=cp_mgr)
    result = executor.run()

    # Workflow failed at step-2
    assert result is not None
    assert result.final_state == WorkflowState.FAILED
    assert plan.steps[0].status == StepStatus.SUCCEEDED
    assert plan.steps[1].status == StepStatus.FAILED
    assert plan.steps[2].status == StepStatus.PENDING
    assert tool.invocations == 2  # step 1 succeeded (1), step 2 failed (1)

    # Checkpoint captured the failure
    latest_cp = cp_store.get_latest("plan-recovery-1")
    assert latest_cp is not None
    assert latest_cp.failed_step_id == "step-2"
    assert latest_cp.completed_step_ids == ["step-1"]

    # Recover failed step-2 with corrected arguments (remove "fail" flag)
    recover_result = executor.recover_failed_step(
        step_id="step-2",
        updated_arguments={"val": "corrected_good_value"},
        resume=True,
    )

    assert recover_result is not None
    assert recover_result.final_state == WorkflowState.SUCCEEDED
    assert plan.steps[0].status == StepStatus.SUCCEEDED
    assert plan.steps[1].status == StepStatus.SUCCEEDED
    assert plan.steps[2].status == StepStatus.SUCCEEDED

    # Verify step-1 was NEVER re-invoked during recovery!
    # Total invocations: step 1 (1) + step 2 failed (1) + step 2 retry (1) + step 3 (1) = 4
    assert tool.invocations == 4


def test_idempotency_keys_prevent_duplicate_execution(mock_registry):
    """
    Acceptance Criteria 1: Idempotency keys prevent duplicate execution.
    """
    registry, tool = mock_registry
    idemp_store = IdempotencyStore()

    key = IdempotencyStore.compute_key(
        plan_id="plan-idemp-1",
        step_id="step-1",
        tool_name="counting_tool",
        arguments={"val": "cache_me"},
    )

    # Run step the first time
    plan1 = WorkflowPlan(
        plan_id="plan-idemp-1",
        session_id="sess-1",
        correlation_id="corr-1",
        title="Idempotency Test 1",
        steps=[
            WorkflowStep(
                step_id="step-1",
                tool_name="counting_tool",
                description="Step with explicit idempotency key",
                arguments={"val": "cache_me"},
                idempotency_key=key,
                is_idempotent=True,
            ),
        ],
    )

    exec1 = WorkflowExecutor(plan=plan1, registry=registry, idempotency_store=idemp_store)
    res1 = exec1.run()
    assert res1.final_state == WorkflowState.SUCCEEDED
    assert tool.invocations == 1
    assert idemp_store.has(key)

    # Run another plan that executes the exact same step with the same key
    plan2 = WorkflowPlan(
        plan_id="plan-idemp-2",
        session_id="sess-2",
        correlation_id="corr-2",
        title="Idempotency Test 2",
        steps=[
            WorkflowStep(
                step_id="step-duplicate",
                tool_name="counting_tool",
                description="Duplicate step call",
                arguments={"val": "cache_me"},
                idempotency_key=key,
                is_idempotent=True,
            ),
        ],
    )

    exec2 = WorkflowExecutor(plan=plan2, registry=registry, idempotency_store=idemp_store)
    res2 = exec2.run()

    assert res2.final_state == WorkflowState.SUCCEEDED
    # Tool invocation count must still be 1! It was satisfied from the cache!
    assert tool.invocations == 1
    assert res2.step_results["step-duplicate"] == res1.step_results["step-1"]

