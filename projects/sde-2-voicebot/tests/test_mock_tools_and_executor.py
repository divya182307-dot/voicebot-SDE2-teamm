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
    MockCourseScheduleTool,
    MockKnowledgeSearchTool,
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


def test_mock_course_schedule_tool_happy_path():
    tool = MockCourseScheduleTool()
    assert tool.name == "course_schedule"
    assert tool.risk_level == RiskLevel.INFORMATIONAL
    assert tool.is_consequential is False

    result = tool.execute({"course_code": "CS101"})
    assert result["status"] == "success"
    assert result["course_code"] == "CS101"
    assert result["mock_mode"] is True
    assert "Alan Turing" in result["instructor"]
    assert "Turing Hall" in result["location"]


def test_mock_course_schedule_tool_missing_arg_raises():
    tool = MockCourseScheduleTool()
    with pytest.raises(ValueError, match="missing required argument: 'course_code'"):
        tool.execute({})


def test_mock_tools_harmless_and_consequential_behavior():
    # Verify that the two default mock tools are harmless with no external sending
    search_tool = MockKnowledgeSearchTool()
    schedule_tool = MockCourseScheduleTool()
    assert search_tool.is_consequential is False
    assert schedule_tool.is_consequential is False

    # Verify consequential behavior logic using a test consequential BaseTool
    class DummySensitiveTool(BaseTool):
        def __init__(self):
            super().__init__(
                ToolSpec(
                    name="dummy_sensitive",
                    purpose="Dummy tool for testing consequential classification",
                    risk_level=RiskLevel.SENSITIVE,
                )
            )

        def execute(self, arguments):
            return {"status": "success"}

    tool = DummySensitiveTool()
    assert tool.name == "dummy_sensitive"
    assert tool.risk_level == RiskLevel.SENSITIVE
    assert tool.is_consequential is True


def test_tool_registry():
    registry = ToolRegistry.get_default_registry()
    assert registry.has("knowledge_search")
    assert registry.has("course_schedule")
    assert len(registry.list_tools()) == 2

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
        tool_name="course_schedule",
        arguments={"course_code": "CS101"},
        description="Lookup course schedule",
        depends_on=["step-1"],
        risk_level=RiskLevel.INFORMATIONAL,
    )
    plan = WorkflowPlan(
        session_id="sess-001",
        correlation_id="corr-001",
        title="Student Deadline and Course Schedule Workflow",
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
    assert result.step_results["step-2"]["course_code"] == "CS101"
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
        tool_name="course_schedule",
        arguments={"course_code": "CS101"},
        description="Access restricted exam schedule",
        risk_level=RiskLevel.SENSITIVE,  # Auto-requires approval
        depends_on=["step-1"],
    )
    plan = WorkflowPlan(
        session_id="sess-conseq-1",
        correlation_id="corr-conseq-1",
        title="Restricted Course Schedule Workflow",
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
    assert final_result.step_results["step-2"]["course_code"] == "CS101"


def test_executor_consequential_action_rejected_cancels_workflow():
    """Rejecting a consequential approval request halts workflow and transitions to CANCELLED."""
    step = WorkflowStep(
        step_id="step-conseq",
        tool_name="course_schedule",
        arguments={"course_code": "CS101"},
        description="Unauthorized schedule override",
        risk_level=RiskLevel.DESTRUCTIVE,
    )
    plan = WorkflowPlan(
        session_id="sess-reject",
        correlation_id="corr-reject",
        title="Unauthorized Schedule Override Workflow",
        steps=[step],
    )

    executor = WorkflowExecutor(plan)
    res = executor.run()
    assert res is None
    assert executor.current_state == WorkflowState.AWAITING_APPROVAL

    approval_id = list(executor.pending_approvals.keys())[0]
    final_result = executor.reject_request(approval_id, reason="Unauthorized schedule modification attempt")

    assert final_result.final_state == WorkflowState.CANCELLED
    assert executor.current_state == WorkflowState.CANCELLED
    assert step.status == StepStatus.CANCELLED
    assert "Unauthorized schedule modification attempt" in step.error_message


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
