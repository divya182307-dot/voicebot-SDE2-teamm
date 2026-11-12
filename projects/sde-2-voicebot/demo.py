"""
Live Demonstration Script for W4 Agentic Workflow Engine (Week 2 Upgrade).
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M

Demonstrates:
  1. Harmless Automated Workflow: Runs automatically to SUCCEEDED.
  2. Consequential Workflow with Approval: Pauses at AWAITING_APPROVAL, human approves, runs to SUCCEEDED.
  3. Consequential Workflow with Rejection: Halts at AWAITING_APPROVAL, human rejects, guarantees NO tool execution, transitions to CANCELLED.
  4. Consequential Workflow with Expiry: Request TTL expires, guarantees NO tool execution, transitions to CANCELLED.
  5. Plan Validator: Detects cycles, missing dependencies, or unknown tools before execution.
"""

import json
from datetime import datetime, timedelta, timezone
from src.workflow.schemas import (
    RiskLevel,
    WorkflowPlan,
    WorkflowStep,
)
from src.workflow.executor import WorkflowExecutor
from src.workflow.validator import PlanValidator, PlanValidationError


def print_separator(title: str):
    print("\n" + "=" * 80)
    print(f" {title.upper()} ")
    print("=" * 80)


def demo_harmless_workflow():
    print_separator("Scenario 1: Harmless Automated Workflow (Week 2 Safe Execution)")
    print("Objective: Read-only course search followed by harmless course schedule lookup.")
    print("Expected behavior: Runs through to SUCCEEDED without pausing for approval.\n")

    step1 = WorkflowStep(
        step_id="step-01",
        tool_name="knowledge_search",
        arguments={"query": "cs101 schedule", "max_results": 2},
        description="Search syllabus and course information for CS101",
        risk_level=RiskLevel.INFORMATIONAL,
    )
    step2 = WorkflowStep(
        step_id="step-02",
        tool_name="course_schedule",
        arguments={
            "course_code": "CS101",
            "term": "Fall 2026",
        },
        description="Lookup classroom and lecture timetable for CS101",
        depends_on=["step-01"],
        risk_level=RiskLevel.INFORMATIONAL,
    )

    plan = WorkflowPlan(
        session_id="sess-demo-01",
        correlation_id="corr-demo-01",
        title="Student Inquiry: CS101 Lecture Times",
        steps=[step1, step2],
    )

    executor = WorkflowExecutor(plan)
    print(f"Initial State: {executor.current_state.value}")

    result = executor.run()

    print(f"\nExecution Finished!")
    print(f"Final State: {result.final_state.value}")
    print("\nStep Results:")
    for step_id, res in result.step_results.items():
        print(f"  [{step_id}] -> {json.dumps(res, indent=4)}")

    print("\nState Machine Audit History:")
    for event in executor.state_machine.history:
        print(f"  [{event.timestamp.strftime('%H:%M:%S')}] {event.from_state.value} -> {event.to_state.value} ({event.reason})")


def demo_consequential_workflow_approved():
    print_separator("Scenario 2: Consequential Workflow (Approval Granted)")
    print("Objective: Query policy and request access to restricted examination schedule (SENSITIVE action).")
    print("Expected behavior: Executor pauses in AWAITING_APPROVAL; resumes and SUCCEEDS upon approval.\n")

    step1 = WorkflowStep(
        step_id="step-01",
        tool_name="knowledge_search",
        arguments={"query": "exam policy"},
        description="Query university exam policy",
        risk_level=RiskLevel.INFORMATIONAL,
    )
    step2 = WorkflowStep(
        step_id="step-02",
        tool_name="course_schedule",
        arguments={"course_code": "CS101", "term": "Fall 2026"},
        description="Access restricted examination timetable and proctor allocations",
        risk_level=RiskLevel.SENSITIVE,  # Consequential!
        depends_on=["step-01"],
    )

    plan = WorkflowPlan(
        session_id="sess-demo-02",
        correlation_id="corr-demo-02",
        title="Restricted Examination Schedule Access",
        steps=[step1, step2],
    )

    executor = WorkflowExecutor(plan)
    print(f"Starting workflow. Initial State: {executor.current_state.value}")

    executor.run()

    print(f"\nState after initial run(): {executor.current_state.value}")
    assert executor.current_state.value == "awaiting_approval"
    print(f"Pending approval requests: {len(executor.pending_approvals)}")

    approval_id = list(executor.pending_approvals.keys())[0]
    appr_req = executor.pending_approvals[approval_id]
    print(f"\n[APPROVAL REQUEST CREATED]")
    print(f"  Approval ID:     {appr_req.approval_id}")
    print(f"  Step ID:         {appr_req.step_id}")
    print(f"  Tool Name:       {appr_req.tool_name}")
    print(f"  Risk Level:      {appr_req.risk_level.value}")
    print(f"  TTL (seconds):   {appr_req.ttl_seconds}")
    print(f"  Action Summary:  {appr_req.action_summary}")

    print("\n--> Human Supervisor Action: APPROVING request...")
    result = executor.approve_request(approval_id, approver="Prof. Sharma (Academic Dean)", resume=True)

    print(f"\nExecution Finished!")
    print(f"Final State: {result.final_state.value}")
    print("\nStep Results:")
    for step_id, res in result.step_results.items():
        print(f"  [{step_id}] -> {json.dumps(res, indent=4)}")

    print("\nState Machine Audit History:")
    for event in executor.state_machine.history:
        print(f"  [{event.timestamp.strftime('%H:%M:%S')}] {event.from_state.value} -> {event.to_state.value} ({event.reason})")


def demo_consequential_workflow_rejected():
    print_separator("Scenario 3: Consequential Workflow (Approval Rejected)")
    print("Objective: Attempt unauthorized schedule override (DESTRUCTIVE action).")
    print("Expected behavior: Executor pauses in AWAITING_APPROVAL; rejects action, guarantees 0 execution, transitions to CANCELLED.\n")

    step1 = WorkflowStep(
        step_id="step-01",
        tool_name="course_schedule",
        arguments={"course_code": "CS101", "term": "Fall 2026"},
        description="Override room booking and instructor schedule directly without council review",
        risk_level=RiskLevel.DESTRUCTIVE,  # Consequential!
    )

    plan = WorkflowPlan(
        session_id="sess-demo-03",
        correlation_id="corr-demo-03",
        title="Unauthorized Schedule Override",
        steps=[step1],
    )

    executor = WorkflowExecutor(plan)
    executor.run()

    print(f"State after run(): {executor.current_state.value}")
    approval_id = list(executor.pending_approvals.keys())[0]
    appr_req = executor.pending_approvals[approval_id]
    print(f"\n[APPROVAL REQUEST CREATED]")
    print(f"  Approval ID:    {appr_req.approval_id}")
    print(f"  Action Summary: {appr_req.action_summary}")

    print("\n--> Human Supervisor Action: REJECTING request...")
    result = executor.reject_request(approval_id, reason="Schedule modifications require academic council sign-off.")

    print(f"\nExecution Finished!")
    print(f"Final State: {result.final_state.value}")
    print(f"Plan Step Status: {plan.steps[0].status.value}")
    print(f"Step Error Message: {plan.steps[0].error_message}")

    print("\nState Machine Audit History:")
    for event in executor.state_machine.history:
        print(f"  [{event.timestamp.strftime('%H:%M:%S')}] {event.from_state.value} -> {event.to_state.value} ({event.reason})")


def demo_consequential_workflow_expired():
    print_separator("Scenario 4: Consequential Workflow (Approval TTL Expiration)")
    print("Objective: Request approval with TTL. Time expires before supervisor responds.")
    print("Expected behavior: Approval expires, tool execution is strictly prevented, transitions to CANCELLED.\n")

    step1 = WorkflowStep(
        step_id="step-01",
        tool_name="course_schedule",
        arguments={"course_code": "CS101", "term": "Fall 2026"},
        description="Request proctor key access for finals",
        risk_level=RiskLevel.SENSITIVE,
    )

    plan = WorkflowPlan(
        session_id="sess-demo-04",
        correlation_id="corr-demo-04",
        title="Time-limited Proctor Key Access",
        steps=[step1],
    )

    executor = WorkflowExecutor(plan, default_approval_ttl_seconds=1.0)
    executor.run()

    approval_id = list(executor.pending_approvals.keys())[0]
    appr_req = executor.pending_approvals[approval_id]
    print(f"[APPROVAL CREATED] ID: {appr_req.approval_id}, Status: {appr_req.status.value}")

    print("Simulating TTL expiration (time elapsed > TTL)...")
    appr_req.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)

    result = executor.expire_request(approval_id, reason="Approval window expired after 300s TTL")

    print(f"\nExecution Finished!")
    print(f"Final State: {result.final_state.value}")
    print(f"Plan Step Status: {plan.steps[0].status.value}")
    print(f"Approval Status: {appr_req.status.value}")

    print("\nState Machine Audit History:")
    for event in executor.state_machine.history:
        print(f"  [{event.timestamp.strftime('%H:%M:%S')}] {event.from_state.value} -> {event.to_state.value} ({event.reason})")


def demo_plan_validator():
    print_separator("Scenario 5: Plan Validator (Cycle Detection & Allow-List Enforcement)")
    print("Objective: Validate plans with cycles or unknown tools before execution.")
    print("Expected behavior: PlanValidator rejects unsafe plans with descriptive PlanValidationError.\n")

    step_a = WorkflowStep(step_id="a", tool_name="knowledge_search", arguments={"query": "q"}, description="A", depends_on=["b"])
    step_b = WorkflowStep(step_id="b", tool_name="course_schedule", arguments={"course_code": "CS101"}, description="B", depends_on=["a"])
    cyclic_plan = WorkflowPlan.model_construct(
        session_id="sess-cyc",
        correlation_id="corr-cyc",
        title="Cyclic Plan",
        steps=[step_a, step_b],
    )

    validator = PlanValidator()
    try:
        validator.validate_dependencies_and_cycles(cyclic_plan)
    except PlanValidationError as e:
        print(f"[CAUGHT EXPECTED ERROR] {e}")


if __name__ == "__main__":
    print("Starting Week 2 Agentic Workflow Live Execution Demonstration...\n")
    demo_harmless_workflow()
    demo_consequential_workflow_approved()
    demo_consequential_workflow_rejected()
    demo_consequential_workflow_expired()
    demo_plan_validator()
    print_separator("Week 2 Demo Completed Successfully")
