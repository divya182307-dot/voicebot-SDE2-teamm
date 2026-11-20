"""
Week 3 Tests: Reasoning Proposals, Backend Approval State & UI Integration.
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M

Days 19-20 Deliverables:
1. Accept WorkflowProposals from reasoning (W3) and validate them against policy
2. Backend approval state synchronization with TTL tracking
3. UI approval and rejection controls
4. Strict enforcement: Duplicate and expired approvals NEVER execute a tool
"""

import time
from datetime import datetime, timedelta, timezone
import pytest

from src.workflow.integration import (
    ApprovalIntegrationError,
    BackendApprovalService,
    WorkflowProposalParser,
    WorkflowUIBridge,
)
from src.workflow.schemas import (
    ApprovalRequest,
    ApprovalStatus,
    ProposalStep,
    RiskLevel,
    StepStatus,
    WorkflowPlan,
    WorkflowProposal,
    WorkflowState,
    WorkflowStep,
)
from src.workflow.tools import (
    BaseTool,
    MockCourseScheduleTool,
    MockKnowledgeSearchTool,
    ToolRegistry,
    ToolSpec,
)


class SideEffectDetectorTool(BaseTool):
    """Harmless tool that tracks every invocation to strictly verify zero-execution guarantees."""

    def __init__(self, name: str = "side_effect_detector", risk_level: RiskLevel = RiskLevel.SENSITIVE):
        self.invocation_count = 0
        spec = ToolSpec(
            name=name,
            purpose="In-memory tool detecting side-effects for testing",
            input_schema={"type": "object", "properties": {"target": {"type": "string"}}},
            output_schema={"type": "object"},
            risk_level=risk_level,
        )
        super().__init__(spec)

    def execute(self, arguments):
        self.invocation_count += 1
        return {"status": "executed", "count": self.invocation_count}


@pytest.fixture
def integrated_setup():
    registry = ToolRegistry()
    registry.register(MockKnowledgeSearchTool())
    registry.register(MockCourseScheduleTool())
    detector = SideEffectDetectorTool()
    registry.register(detector)

    approval_service = BackendApprovalService(default_ttl_seconds=300.0)
    ui_bridge = WorkflowUIBridge(registry=registry, approval_service=approval_service)

    return registry, detector, approval_service, ui_bridge


def test_reasoning_proposal_accepted_and_validated(integrated_setup):
    """
    Acceptance Criteria 3: WorkflowProposals from reasoning are accepted and validated.
    """
    registry, _, _, ui_bridge = integrated_setup

    proposal = WorkflowProposal(
        session_id="sess-student-101",
        source_utterance="Can you tell me CS101 class times and exam policies?",
        intent="academic_inquiry",
        confidence=0.98,
        title="Student Class and Exam Policy Inquiry",
        proposed_steps=[
            ProposalStep(
                step_id="step-1",
                tool_name="knowledge_search",
                description="Search exam policy FAQ",
                arguments={"query": "exam policy"},
            ),
            ProposalStep(
                step_id="step-2",
                tool_name="course_schedule",
                description="Lookup CS101 lecture timetable",
                arguments={"course_code": "CS101"},
                depends_on=["step-1"],
            ),
        ],
    )

    plan = ui_bridge.submit_proposal(proposal)
    assert plan is not None
    assert plan.session_id == "sess-student-101"
    assert len(plan.steps) == 2
    assert plan.steps[0].tool_name == "knowledge_search"
    assert plan.steps[1].tool_name == "course_schedule"

    # Execute workflow via UI bridge
    result = ui_bridge.execute_workflow(plan.plan_id)
    assert result is not None
    assert result.final_state == WorkflowState.SUCCEEDED


def test_ui_approval_flow_resumes_workflow(integrated_setup):
    """
    Acceptance Criteria 3: UI reads pending approvals and approves consequential steps.
    """
    registry, detector, approval_service, ui_bridge = integrated_setup

    proposal = WorkflowProposal(
        session_id="sess-student-102",
        source_utterance="Modify my proctored exam time",
        intent="sensitive_modification",
        title="Restricted Action Workflow",
        proposed_steps=[
            ProposalStep(
                step_id="step-conseq",
                tool_name="side_effect_detector",
                description="Perform sensitive record modification",
                arguments={"target": "exam_booking"},
                risk_level=RiskLevel.SENSITIVE,
            ),
        ],
    )

    plan = ui_bridge.submit_proposal(proposal)
    result = ui_bridge.execute_workflow(plan.plan_id)

    # Workflow paused awaiting approval
    assert result is None
    pending = ui_bridge.list_pending_approvals(session_id="sess-student-102")
    assert len(pending) == 1
    appr_id = pending[0].approval_id

    # Zero tool executions prior to approval
    assert detector.invocation_count == 0

    # UI issues approval
    resume_result = ui_bridge.ui_approve(appr_id, approver="Dean of Academic Affairs")
    assert resume_result is not None
    assert resume_result.final_state == WorkflowState.SUCCEEDED
    assert detector.invocation_count == 1


def test_ui_rejection_guarantees_zero_execution(integrated_setup):
    """
    Acceptance Criteria 3 & 4: UI rejection guarantees ZERO tool execution.
    """
    registry, detector, approval_service, ui_bridge = integrated_setup

    proposal = WorkflowProposal(
        session_id="sess-student-103",
        source_utterance="Drop core graduation course without advisor",
        intent="unauthorized_drop",
        title="Unauthorized Drop Request",
        proposed_steps=[
            ProposalStep(
                step_id="step-drop",
                tool_name="side_effect_detector",
                description="Unauthorized drop",
                arguments={"target": "cs_core"},
                risk_level=RiskLevel.DESTRUCTIVE,
            ),
        ],
    )

    plan = ui_bridge.submit_proposal(proposal)
    ui_bridge.execute_workflow(plan.plan_id)

    pending = ui_bridge.list_pending_approvals()
    assert len(pending) == 1
    appr_id = pending[0].approval_id

    # UI issues rejection
    rejection_result = ui_bridge.ui_reject(appr_id, reason="Core graduation requirement cannot be dropped")
    assert rejection_result.final_state == WorkflowState.CANCELLED

    # Acceptance Criteria 4 Guarantee: ZERO tool invocations!
    assert detector.invocation_count == 0


def test_duplicate_approvals_rejected_and_never_execute_tool(integrated_setup):
    """
    Acceptance Criteria 4: Duplicate approvals never execute a tool a second time.
    """
    registry, detector, approval_service, ui_bridge = integrated_setup

    proposal = WorkflowProposal(
        session_id="sess-duplicate-104",
        source_utterance="One-time sensitive grant",
        intent="grant_access",
        title="One Time Grant",
        proposed_steps=[
            ProposalStep(
                step_id="step-grant",
                tool_name="side_effect_detector",
                description="Sensitive access grant",
                arguments={"target": "grant_lab_keys"},
                risk_level=RiskLevel.SENSITIVE,
            ),
        ],
    )

    plan = ui_bridge.submit_proposal(proposal)
    ui_bridge.execute_workflow(plan.plan_id)

    pending = ui_bridge.list_pending_approvals()
    assert len(pending) == 1
    appr_id = pending[0].approval_id

    # First approval succeeds
    res1 = ui_bridge.ui_approve(appr_id, approver="Lab Director")
    assert res1.final_state == WorkflowState.SUCCEEDED
    assert detector.invocation_count == 1

    # Second / duplicate approval attempt must be rejected by backend approval service
    with pytest.raises((ApprovalIntegrationError, ValueError)) as excinfo:
        ui_bridge.ui_approve(appr_id, approver="Impostor / Replay Attack")

    assert "Duplicate" in str(excinfo.value) or "already approved" in str(excinfo.value)

    # Tool invocation count must remain strictly 1
    assert detector.invocation_count == 1


def test_expired_approvals_never_execute_tool(integrated_setup):
    """
    Acceptance Criteria 4: Expired approvals never execute a tool.
    """
    registry, detector, approval_service, ui_bridge = integrated_setup

    proposal = WorkflowProposal(
        session_id="sess-expired-105",
        source_utterance="Sensitive grant with tight TTL",
        intent="tight_ttl_action",
        title="Expiring Action",
        proposed_steps=[
            ProposalStep(
                step_id="step-tight",
                tool_name="side_effect_detector",
                description="Tight TTL action",
                arguments={"target": "temporary_access"},
                risk_level=RiskLevel.SENSITIVE,
            ),
        ],
    )

    plan = ui_bridge.submit_proposal(proposal)
    ui_bridge.execute_workflow(plan.plan_id)

    pending = ui_bridge.list_pending_approvals()
    assert len(pending) == 1
    appr_id = pending[0].approval_id

    # Fast-forward time to simulate TTL expiration
    req = approval_service.get_request(appr_id)
    # Manually backdate the created_at & expires_at to simulate expiry
    approval_service._store[appr_id].expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)

    # Now attempt to approve an expired request
    with pytest.raises((ApprovalIntegrationError, ValueError)) as excinfo:
        ui_bridge.ui_approve(appr_id, approver="Late Admin")

    assert "expired" in str(excinfo.value).lower()

    # Tool invocation count MUST be 0!
    assert detector.invocation_count == 0

