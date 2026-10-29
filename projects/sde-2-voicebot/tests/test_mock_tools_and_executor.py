"""
Unit Tests for Mock Tools and Workflow Executor.
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M

Day 3-4 & Day 5-6 Deliverables:
Validates two harmless mock tools, tool registry, consequential action approval gating,
interactive approval/rejection handling, and mock plan execution.
"""

import pytest

from src.workflow.schemas import (
    ApprovalStatus,
    RiskLevel,
    StepStatus,
    ToolFailureBehavior,
    ToolSpec,
    WorkflowPlan,
    WorkflowState,
    WorkflowStep,
)
from src.workflow.tools import (
    BaseTool,
    MockKnowledgeSearchTool,
    MockNotificationTool,
    MockStudentRecordUpdateTool,
    ToolRegistry,
)
from src.workflow.executor import WorkflowExecutor


# ============================================================================
# Mock Tools Tests
# ============================================================================

def test_mock_knowledge_search_tool_happy_path():
    tool = MockKnowledgeSearchTool()
    assert tool.name == "knowledge_search"
    assert tool.risk_level == RiskLevel.INFORMATIONAL
    assert tool.is_consequential is False

    # Search for an existing keyword in mock corpus
    result = tool.execute({"query": "cs101"})
    assert result["status"] == "success"
    assert result["count"] > 0
    assert result["mock_mode"] is True
    assert "CS101" in result["results"][0]["title"]


def test_mock_knowledge_search_tool_missing_arg_raises():
    tool = MockKnowledgeSearchTool()
    with pytest.raises(ValueError, match="missing required argument: 'query'"):
        tool.execute({})


def test_mock_notification_tool_happy_path():
    tool = MockNotificationTool()
    assert tool.name == "send_notification"
    assert tool.risk_level == RiskLevel.LOW_RISK
    assert tool.is_consequential is False

    result = tool.execute({
        "recipient": "student@university.edu",
        "message": "Your registration is confirmed.",
        "channel": "email",
    })
    assert result["status"] == "success"
    assert result["delivered"] is True
    assert result["mock_mode"] is True
    assert result["recipient"] == "student@university.edu"


def test_mock_notification_tool_missing_arg_raises():
    tool = MockNotificationTool()
    with pytest.raises(ValueError, match="missing required argument: 'message'"):
        tool.execute({"recipient": "test@test.com"})


def test_mock_student_record_update_tool_is_consequential():
    tool = MockStudentRecordUpdateTool()
    assert tool.name == "update_student_record"
    assert tool.risk_level == RiskLevel.SENSITIVE
    assert tool.is_consequential is True

    result = tool.execute({
        "student_id": "STU-9921",
        "field": "enrollment_status",
        "new_value": "ACTIVE",
    })
    assert result["status"] == "success"
    assert result["updated"] is True
    assert result["mock_mode"] is True


def test_tool_registry():
    registry = ToolRegistry.get_default_registry()
    assert registry.has("knowledge_search")
    assert registry.has("send_notification")
    assert registry.has("update_student_record")
    assert len(registry.list_tools()) == 3

    # Duplicate registration raises error
    with pytest.raises(ValueError, match="already registered"):
        registry.register(MockKnowledgeSearchTool())

    # Non-existent tool raises KeyError
    with pytest.raises(KeyError, match="not registered"):
        registry.get("unregistered_tool")


# ============================================================================
# WorkflowExecutor Tests
# ============================================================================

def test_executor_harmless_workflow_runs_to_succeeded():
    """A workflow with only harmless tools runs automatically from DRAFT to SUCCEEDED."""
    step1 = WorkflowStep(
        step_id="step-1",
        tool_name="knowledge_search",
        arguments={"query": "registration deadline"},
        description="Lookup deadline",
        risk_level=RiskLevel.INFORMATIONAL,
    )
    step2 = WorkflowStep(
        step_id="step-2",
        tool_name="send_notification",
        arguments={"recipient": "karthik@student.edu", "message": "Add/drop ends Friday."},
        description="Notify student",
        depends_on=["step-1"],
        risk_level=RiskLevel.LOW_RISK,
    )
    plan = WorkflowPlan(
        session_id="sess-001",
        correlation_id="corr-001",
        title="Student Deadline Notification Workflow",
        steps=[step1, step2],
    )

    executor = WorkflowExecutor(plan)
    assert executor.current_state == WorkflowState.DRAFT

    result = executor.run()
    assert result is not None
    assert result.final_state == WorkflowState.SUCCEEDED
    assert executor.current_state == WorkflowState.SUCCEEDED
    assert "step-1" in result.step_results
    assert "step-2" in result.step_results
    assert result.step_results["step-1"]["count"] > 0
    assert result.step_results["step-2"]["delivered"] is True
    assert step1.status == StepStatus.SUCCEEDED
    assert step2.status == StepStatus.SUCCEEDED


def test_executor_consequential_action_pauses_for_approval():
    """A workflow with consequential action must halt and enter AWAITING_APPROVAL."""
    step1 = WorkflowStep(
        step_id="step-1",
        tool_name="knowledge_search",
        arguments={"query": "tuition"},
        description="Lookup balance",
        risk_level=RiskLevel.INFORMATIONAL,
    )
    step2 = WorkflowStep(
        step_id="step-2",
        tool_name="update_student_record",
        arguments={"student_id": "STU-883", "field": "financial_hold", "new_value": "CLEARED"},
        description="Clear student financial hold",
        risk_level=RiskLevel.SENSITIVE,  # Auto-requires approval
        depends_on=["step-1"],
    )
    plan = WorkflowPlan(
        session_id="sess-conseq-1",
        correlation_id="corr-conseq-1",
        title="Tuition Clearance Workflow",
        steps=[step1, step2],
    )

    executor = WorkflowExecutor(plan)
    result = executor.run()

    # Step 1 succeeded, step 2 stopped for approval
    assert result is None  # Paused awaiting approval
    assert executor.current_state == WorkflowState.AWAITING_APPROVAL
    assert step1.status == StepStatus.SUCCEEDED
    assert step2.status == StepStatus.AWAITING_APPROVAL
    assert len(executor.pending_approvals) == 1

    approval_id = list(executor.pending_approvals.keys())[0]
    appr_req = executor.pending_approvals[approval_id]
    assert appr_req.step_id == "step-2"
    assert appr_req.risk_level == RiskLevel.SENSITIVE
    assert appr_req.status == ApprovalStatus.PENDING

    # Now grant approval
    final_result = executor.approve_request(approval_id, approver="Dean of Admissions", resume=True)
    assert final_result is not None
    assert final_result.final_state == WorkflowState.SUCCEEDED
    assert executor.current_state == WorkflowState.SUCCEEDED
    assert step2.status == StepStatus.SUCCEEDED
    assert final_result.step_results["step-2"]["updated"] is True


def test_executor_consequential_action_rejected_cancels_workflow():
    """Rejecting a consequential approval request halts workflow and transitions to CANCELLED."""
    step = WorkflowStep(
        step_id="step-conseq",
        tool_name="update_student_record",
        arguments={"student_id": "STU-999", "field": "grade", "new_value": "A+"},
        description="Alter final grade",
        risk_level=RiskLevel.DESTRUCTIVE,
    )
    plan = WorkflowPlan(
        session_id="sess-reject",
        correlation_id="corr-reject",
        title="Grade Alteration Workflow",
        steps=[step],
    )

    executor = WorkflowExecutor(plan)
    res = executor.run()
    assert res is None
    assert executor.current_state == WorkflowState.AWAITING_APPROVAL

    approval_id = list(executor.pending_approvals.keys())[0]
    final_result = executor.reject_request(approval_id, reason="Unauthorized grade modification attempt")

    assert final_result.final_state == WorkflowState.CANCELLED
    assert executor.current_state == WorkflowState.CANCELLED
    assert step.status == StepStatus.CANCELLED
    assert "Unauthorized grade modification" in step.error_message


def test_executor_pause_and_resume():
    """Workflow can be paused and resumed cleanly."""
    step1 = WorkflowStep(
        step_id="s1",
        tool_name="knowledge_search",
        arguments={"query": "exam policy"},
        description="Search policy",
    )
    plan = WorkflowPlan(
        session_id="sess-pr",
        correlation_id="corr-pr",
        title="Pause Resume Plan",
        steps=[step1],
    )
    executor = WorkflowExecutor(plan)

    # Transition to running
    executor.state_machine.transition(WorkflowState.RUNNING)
    executor.pause(reason="Network jitter")
    assert executor.current_state == WorkflowState.PAUSED

    result = executor.resume()
    assert result is not None
    assert result.final_state == WorkflowState.SUCCEEDED
    assert executor.current_state == WorkflowState.SUCCEEDED


def test_executor_unregistered_tool_fails_workflow():
    """Invoking an unapproved/unregistered tool marks workflow FAILED."""
    step = WorkflowStep(
        step_id="bad-step",
        tool_name="unknown_external_tool",
        description="Run malicious or unknown tool",
    )
    plan = WorkflowPlan(
        session_id="sess-bad",
        correlation_id="corr-bad",
        title="Unknown Tool Plan",
        steps=[step],
    )
    executor = WorkflowExecutor(plan)
    result = executor.run()

    assert result is not None
    assert result.final_state == WorkflowState.FAILED
    assert executor.current_state == WorkflowState.FAILED
    assert step.status == StepStatus.FAILED
    assert "not registered" in result.error_details["error"]
