"""
Week 3 Day 21 Team Gate: Complete End-to-End Integration Test.
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M

Day 21 Team Gate:
A session flows through:
  1. Audio/Utterance transcription simulation
  2. Reasoning proposal generation (WorkflowProposal)
  3. Workflow policy & DAG validation (PlanValidator)
  4. Step execution with checkpointing and idempotency keys
  5. Approval gate via backend approval state
  6. UI decision (approve / reject)
  7. Resuming from checkpoint without re-executing completed steps
  8. Step-level audit logging and progress events streaming
"""

from typing import List
import pytest

from src.workflow.integration import BackendApprovalService, WorkflowUIBridge
from src.workflow.schemas import (
    ProgressEvent,
    ProgressEventType,
    ProposalStep,
    RiskLevel,
    StepStatus,
    WorkflowProposal,
    WorkflowState,
)
from src.workflow.tools import MockCourseScheduleTool, MockKnowledgeSearchTool, ToolRegistry


def test_full_session_flow_through_gate():
    """
    Day 21 Team Gate Integration Test:
    Simulates:
      Student voice transcription ->
      Reasoning engine WorkflowProposal ->
      Workflow policy validation ->
      Step 1 & 2 execution with checkpoints ->
      Approval gate on Step 3 (Sensitive) ->
      Backend approval state store ->
      UI approval ->
      Resume from checkpoint (no re-execution of steps 1 & 2) ->
      Full audit trail and event stream verification.
    """
    # 1. Setup allowable harmless tools and infrastructure
    registry = ToolRegistry()
    registry.register(MockKnowledgeSearchTool())
    registry.register(MockCourseScheduleTool())

    ui_bridge = WorkflowUIBridge(registry=registry)

    # 2. Subscribe to real-time progress events
    captured_events: List[ProgressEvent] = []
    ui_bridge.subscribe_events(lambda ev: captured_events.append(ev))

    # 3. Simulated Transcription -> Reasoning produces WorkflowProposal
    proposal = WorkflowProposal(
        session_id="sess-voice-gate-2026",
        correlation_id="corr-gate-42",
        source_utterance="Hi, I want to review the CS101 syllabus, see my timetable, and request permission for the restricted proctored final.",
        intent="academic_exam_scheduling",
        confidence=0.99,
        title="Student End-to-End Inquiry & Exam Schedule Request",
        proposed_steps=[
            # Step 1: Harmless FAQ search
            ProposalStep(
                step_id="step-transcribe-faq",
                tool_name="knowledge_search",
                description="Search syllabus FAQ for CS101",
                arguments={"query": "cs101"},
            ),
            # Step 2: Harmless course schedule
            ProposalStep(
                step_id="step-transcribe-schedule",
                tool_name="course_schedule",
                description="Query standard class timings",
                arguments={"course_code": "CS101"},
                depends_on=["step-transcribe-faq"],
            ),
            # Step 3: Sensitive exam proctor request (consequential)
            ProposalStep(
                step_id="step-transcribe-proctor",
                tool_name="course_schedule",
                description="Request restricted exam room & proctor details",
                arguments={"course_code": "CS101"},
                risk_level=RiskLevel.SENSITIVE,
                depends_on=["step-transcribe-schedule"],
            ),
        ],
    )

    # 4. Ingest and policy-validate proposal into WorkflowPlan
    plan = ui_bridge.submit_proposal(proposal)
    assert plan is not None
    assert len(plan.steps) == 3

    # 5. First execution attempt: executes step 1 & 2, then pauses at step 3
    initial_result = ui_bridge.execute_workflow(plan.plan_id)
    assert initial_result is None  # Paused in AWAITING_APPROVAL

    # Verify Step 1 & 2 SUCCEEDED; Step 3 AWAITING_APPROVAL
    assert plan.steps[0].status == StepStatus.SUCCEEDED
    assert plan.steps[1].status == StepStatus.SUCCEEDED
    assert plan.steps[2].status == StepStatus.AWAITING_APPROVAL

    # Verify checkpoints were created
    checkpoints = ui_bridge.get_checkpoints(plan.plan_id)
    assert len(checkpoints) >= 2
    latest_cp = checkpoints[-1]
    assert "step-transcribe-faq" in latest_cp.completed_step_ids
    assert "step-transcribe-schedule" in latest_cp.completed_step_ids

    # 6. Backend approval state verification
    pending = ui_bridge.list_pending_approvals(session_id="sess-voice-gate-2026")
    assert len(pending) == 1
    appr_req = pending[0]
    assert appr_req.step_id == "step-transcribe-proctor"
    assert appr_req.risk_level == RiskLevel.SENSITIVE

    # 7. UI acts: Approves the pending request
    final_result = ui_bridge.ui_approve(appr_req.approval_id, approver="Prof. Turing (Department Chair)")
    assert final_result is not None
    assert final_result.final_state == WorkflowState.SUCCEEDED

    # Verify all 3 steps SUCCEEDED
    assert all(s.status == StepStatus.SUCCEEDED for s in plan.steps)

    # 8. Step-level audit trail verification
    audit_trail = ui_bridge.get_audit_trail(plan.plan_id)
    assert len(audit_trail) == 3
    for record in audit_trail:
        assert record.status == StepStatus.SUCCEEDED
        assert record.duration_ms >= 0.0
        assert record.idempotency_key is not None

    # 9. Verify progress event stream contains all milestones
    event_types = [e.event_type for e in captured_events]
    assert ProgressEventType.WORKFLOW_STARTED in event_types
    assert ProgressEventType.STEP_STARTED in event_types
    assert ProgressEventType.STEP_COMPLETED in event_types
    assert ProgressEventType.APPROVAL_REQUESTED in event_types
    assert ProgressEventType.APPROVAL_GRANTED in event_types
    assert ProgressEventType.WORKFLOW_COMPLETED in event_types

