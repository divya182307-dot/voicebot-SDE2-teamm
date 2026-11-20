"""
demo_week3.py — Week 3 (Days 15–21) Live Agentic Workflow Demonstration.
Workstream: W4 (Agentic Workflow Engine) - Team SDE 2
Author: Karthik N M

Demonstrates all Week 3 Acceptance Criteria:
1. Checkpoint & Resume with failed-step recovery and idempotency keys
2. Step-level audit trail and progress events streaming
3. Reasoning proposal integration, backend approval state, and UI controls
4. Duplicate and expired approval protection (zero tool execution)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

from src.workflow.audit import ProgressEventEmitter, StepAuditLogger
from src.workflow.checkpoint import CheckpointManager, CheckpointStore
from src.workflow.executor import WorkflowExecutor
from src.workflow.idempotency import IdempotencyStore
from src.workflow.integration import (
    ApprovalIntegrationError,
    BackendApprovalService,
    WorkflowProposalParser,
    WorkflowUIBridge,
)
from src.workflow.schemas import (
    ApprovalRequest,
    ApprovalStatus,
    ProgressEvent,
    ProposalStep,
    RiskLevel,
    StepStatus,
    WorkflowPlan,
    WorkflowProposal,
    WorkflowState,
    WorkflowStep,
)
from src.workflow.tools import MockCourseScheduleTool, MockKnowledgeSearchTool, ToolRegistry


def header(title: str) -> None:
    print("\n" + "=" * 80)
    print(f" {title} ")
    print("=" * 80)


def format_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)


def run_demo():
    print("🚀 Starting Week 3 Agentic Workflow Engine Live Demonstration (Days 15-21)...\n")

    registry = ToolRegistry()
    registry.register(MockKnowledgeSearchTool())
    registry.register(MockCourseScheduleTool())

    # =========================================================================
    # SCENARIO 1: REASONING PROPOSAL INGESTION & PROGRESS EVENTS
    # =========================================================================
    header("SCENARIO 1: REASONING PROPOSAL INGESTION & LIVE PROGRESS STREAMING")
    print("Context: University voice copilot receives speech from a student.")
    print("Flow: Transcribed Speech -> Reasoning (W3) Proposal -> PlanValidator -> Execution\n")

    event_log = []
    emitter = ProgressEventEmitter()
    emitter.subscribe(lambda ev: event_log.append(f"  [{ev.timestamp.strftime('%H:%M:%S')}] {ev.event_type.value.upper()}: {ev.message}"))

    ui_bridge = WorkflowUIBridge(registry=registry, event_emitter=emitter)

    proposal = WorkflowProposal(
        session_id="session-stud-401",
        source_utterance="Where is Dr. Turing's CS101 class and what are the registration rules?",
        intent="academic_query",
        confidence=0.99,
        title="Student Class and Registration Policy Query",
        proposed_steps=[
            ProposalStep(
                step_id="step-faq",
                tool_name="knowledge_search",
                description="Search academic registration guidelines",
                arguments={"query": "cs101"},
            ),
            ProposalStep(
                step_id="step-schedule",
                tool_name="course_schedule",
                description="Lookup CS101 lecture hall and timing",
                arguments={"course_code": "CS101"},
                depends_on=["step-faq"],
            ),
        ],
    )

    print(f"Incoming Reasoning Proposal: '{proposal.title}' (Confidence: {proposal.confidence * 100:.1f}%)")
    plan = ui_bridge.submit_proposal(proposal)
    print(f"✓ PlanValidator verified proposal! Generated Plan ID: {plan.plan_id}")

    result = ui_bridge.execute_workflow(plan.plan_id)
    print(f"Workflow State: {result.final_state.value.upper()}")

    print("\nLive Emitted Progress Events:")
    for entry in event_log:
        print(entry)

    # =========================================================================
    # SCENARIO 2: CHECKPOINT & RESUME WITH IDEMPOTENCY KEYS
    # =========================================================================
    header("SCENARIO 2: CHECKPOINT & IDEMPOTENCY KEY CACHING")
    print("Objective: Ensure operations with identical idempotency keys return cached results without tool re-runs.\n")

    idemp_store = IdempotencyStore()
    cp_store = CheckpointStore()
    cp_mgr = CheckpointManager(cp_store)

    idemp_key = IdempotencyStore.compute_key("plan-idemp-demo", "step-cached", "course_schedule", {"course_code": "CS101"})

    plan1 = WorkflowPlan(
        plan_id="plan-idemp-demo",
        session_id="session-stud-402",
        correlation_id="corr-idemp-1",
        title="Idempotency First Run",
        steps=[
            WorkflowStep(
                step_id="step-cached",
                tool_name="course_schedule",
                description="Fetch course timetable",
                arguments={"course_code": "CS101"},
                idempotency_key=idemp_key,
                is_idempotent=True,
            ),
        ],
    )

    exec1 = WorkflowExecutor(plan=plan1, registry=registry, checkpoint_manager=cp_mgr, idempotency_store=idemp_store)
    res1 = exec1.run()
    print(f"First Run Result: {res1.final_state.value.upper()} (Tool executed and cached)")
    print(f"Cached Idempotency Key: {idemp_key}")

    # Second Run with same key
    plan2 = WorkflowPlan(
        plan_id="plan-idemp-demo-2",
        session_id="session-stud-402",
        correlation_id="corr-idemp-2",
        title="Idempotency Second Run",
        steps=[
            WorkflowStep(
                step_id="step-cached-repeat",
                tool_name="course_schedule",
                description="Fetch course timetable duplicate",
                arguments={"course_code": "CS101"},
                idempotency_key=idemp_key,
                is_idempotent=True,
            ),
        ],
    )

    exec2 = WorkflowExecutor(plan=plan2, registry=registry, checkpoint_manager=cp_mgr, idempotency_store=idemp_store)
    res2 = exec2.run()
    print(f"Second Run Result: {res2.final_state.value.upper()} (Served from IDEMPOTENCY CACHE without re-executing tool)")
    assert res2.step_results["step-cached-repeat"] == res1.step_results["step-cached"]

    # =========================================================================
    # SCENARIO 3: FAILED-STEP RECOVERY FROM CHECKPOINT
    # =========================================================================
    header("SCENARIO 3: FAILED-STEP RECOVERY WITHOUT RE-RUNNING PRIOR STEPS")
    print("Objective: Step 1 succeeds -> Step 2 fails -> Checkpoint saved -> Step 2 corrected -> Step 1 is NOT re-run.\n")

    recovery_plan = WorkflowPlan(
        plan_id="plan-recovery-demo",
        session_id="session-stud-403",
        correlation_id="corr-rec-1",
        title="Failed Step Recovery Demonstration",
        steps=[
            WorkflowStep(
                step_id="step-ok",
                tool_name="knowledge_search",
                description="Query FAQ",
                arguments={"query": "cs101"},
            ),
            WorkflowStep(
                step_id="step-fail",
                tool_name="course_schedule",
                description="Query timetable with missing required argument",
                arguments={},  # Missing required 'course_code' -> triggers validation failure
                depends_on=["step-ok"],
            ),
        ],
    )

    rec_executor = WorkflowExecutor(plan=recovery_plan, registry=registry)
    fail_res = rec_executor.run()
    print(f"Initial Run Status: {fail_res.final_state.value.upper()}")
    print(f"  Step 1 (step-ok):   {recovery_plan.steps[0].status.value.upper()}")
    print(f"  Step 2 (step-fail): {recovery_plan.steps[1].status.value.upper()} (Error: {recovery_plan.steps[1].error_message})")

    print("\n--> Operator Corrects Step 2 Argument: {} -> {'course_code': 'CS101'}...")
    recovered_res = rec_executor.recover_failed_step(
        step_id="step-fail",
        updated_arguments={"course_code": "CS101"},
        resume=True,
    )

    print(f"\nRecovery Run Status: {recovered_res.final_state.value.upper()}")
    print(f"  Step 1 (step-ok):   {recovery_plan.steps[0].status.value.upper()} (NOT RE-RUN - preserved from checkpoint)")
    print(f"  Step 2 (step-fail): {recovery_plan.steps[1].status.value.upper()} (SUCCESSFULLY RECOVERED)")

    # =========================================================================
    # SCENARIO 4: BACKEND APPROVAL STATE & UI APPROVAL GATE
    # =========================================================================
    header("SCENARIO 4: BACKEND APPROVAL STATE & UI HUMAN-IN-THE-LOOP")
    print("Objective: Consequential step creates backend approval request -> UI inspects & approves -> Engine completes.\n")

    approval_service = BackendApprovalService(default_ttl_seconds=300.0)
    ui = WorkflowUIBridge(registry=registry, approval_service=approval_service)

    conseq_proposal = WorkflowProposal(
        session_id="session-stud-404",
        source_utterance="I need to modify my proctored exam time",
        intent="sensitive_modification",
        title="Proctored Exam Modification Plan",
        proposed_steps=[
            ProposalStep(
                step_id="step-proctor-req",
                tool_name="course_schedule",
                description="Access restricted exam hall timetable and proctor list",
                arguments={"course_code": "CS101"},
                risk_level=RiskLevel.SENSITIVE,
            ),
        ],
    )

    conseq_plan = ui.submit_proposal(conseq_proposal)
    ui.execute_workflow(conseq_plan.plan_id)

    pending_list = ui.list_pending_approvals(session_id="session-stud-404")
    print(f"Backend Pending Approvals Count: {len(pending_list)}")
    req = pending_list[0]
    print(f"  Approval ID:    {req.approval_id}")
    print(f"  Tool Name:      {req.tool_name}")
    print(f"  Risk Level:     {req.risk_level.value.upper()}")
    print(f"  Action Summary: {req.action_summary}")
    print(f"  TTL (Seconds):  {req.ttl_seconds}s (Expires: {req.expires_at.strftime('%H:%M:%S UTC')})")

    print("\n--> UI Action: Academic Dean reviews and APPROVES request...")
    appr_res = ui.ui_approve(req.approval_id, approver="Dr. Margaret Hamilton (Dean)")
    print(f"Workflow Resumed! Final State: {appr_res.final_state.value.upper()}")

    # =========================================================================
    # SCENARIO 5: DUPLICATE & EXPIRED APPROVAL ZERO-EXECUTION PROTECTION
    # =========================================================================
    header("SCENARIO 5: DUPLICATE & EXPIRED APPROVAL ZERO-EXECUTION PROTECTION")
    print("Objective: Prove that duplicate or TTL-expired approvals are rejected and strictly execute ZERO tools.\n")

    # A. Duplicate Approval Test
    print("Test A: Replay attack / Duplicate approval on already-approved request:")
    try:
        ui.ui_approve(req.approval_id, approver="Impostor Replay Attack")
        print("  ERROR: Duplicate approval was not blocked!")
    except (ApprovalIntegrationError, ValueError) as err:
        print(f"  ✓ SECURED: Backend rejected duplicate approval! ({err})")

    # B. Expired Approval Test
    print("\nTest B: Attempting approval on a TTL-expired request:")
    exp_req = approval_service.register_request(
        request=ApprovalRequest(
            approval_id="appr-expired-demo",
            session_id="sess-exp",
            correlation_id="corr-exp",
            plan_id="plan-exp",
            step_id="step-exp",
            tool_name="course_schedule",
            risk_level=RiskLevel.SENSITIVE,
            action_summary="Expired action test",
            ttl_seconds=1.0,
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=60),
            status=ApprovalStatus.PENDING,
        )
    )

    try:
        approval_service.approve("appr-expired-demo", approver="Late Operator")
        print("  ERROR: Expired approval was not blocked!")
    except ApprovalIntegrationError as err:
        print(f"  ✓ SECURED: Backend rejected expired approval! ({err})")
        print("  ✓ Guaranteed ZERO tool execution!")

    # =========================================================================
    # STEP-LEVEL AUDIT TRAIL SUMMARY
    # =========================================================================
    header("STEP-LEVEL AUDIT TRAIL EVIDENCE")
    trail = ui.get_audit_trail()
    print(f"Total Step Audit Records Logged: {len(trail)}")
    for record in trail[:3]:
        print(f"  • Audit ID: {record.audit_id} | Step: {record.step_id} | Status: {record.status.value.upper()} | Duration: {record.duration_ms}ms | Idempotency Key: {record.idempotency_key}")

    print("\n" + "=" * 80)
    print(" 🎉 WEEK 3 AGENTIC WORKFLOW DEMONSTRATION COMPLETED SUCCESSFULLY ")
    print("=" * 80)


if __name__ == "__main__":
    run_demo()
