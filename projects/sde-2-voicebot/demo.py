"""
Live Demonstration Script for W4 Agentic Workflow Engine.
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M

Demonstrates:
  1. Harmless Workflow: Runs automatically to SUCCEEDED.
  2. Consequential Workflow with Approval: Pauses at AWAITING_APPROVAL, grants approval, and runs to SUCCEEDED.
  3. Consequential Workflow with Rejection: Halts and transitions safely to CANCELLED.
"""

import json
from datetime import datetime
from src.workflow.schemas import (
    RiskLevel,
    WorkflowPlan,
    WorkflowStep,
)
from src.workflow.executor import WorkflowExecutor


def print_separator(title: str):
    print("\n" + "=" * 80)
    print(f" {title.upper()} ")
    print("=" * 80)


def demo_harmless_workflow():
    print_separator("Scenario 1: Harmless Automated Workflow")
    print("Objective: Read-only course search followed by harmless notification dispatch.")
    print("Expected behavior: Runs through to SUCCEEDED without pausing for approval.\n")

    step1 = WorkflowStep(
        step_id="step-01",
        tool_name="knowledge_search",
        arguments={"query": "cs101 schedule", "max_results": 2},
        description="Search syllabus and lecture timing for CS101",
        risk_level=RiskLevel.INFORMATIONAL,
    )
    step2 = WorkflowStep(
        step_id="step-02",
        tool_name="send_notification",
        arguments={
            "recipient": "karthik.nm@university.edu",
            "message": "CS101 lectures are on Mon & Wed at 10 AM.",
            "channel": "email",
        },
        description="Send lecture schedule email to student",
        depends_on=["step-01"],
        risk_level=RiskLevel.LOW_RISK,
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
    print("Objective: Look up student fee status and clear financial hold (SENSITIVE action).")
    print("Expected behavior: Executor pauses in AWAITING_APPROVAL; resumes and SUCCEEDS upon approval.\n")

    step1 = WorkflowStep(
        step_id="step-01",
        tool_name="knowledge_search",
        arguments={"query": "tuition payment"},
        description="Query tuition fee status",
        risk_level=RiskLevel.INFORMATIONAL,
    )
    step2 = WorkflowStep(
        step_id="step-02",
        tool_name="update_student_record",
        arguments={"student_id": "STU-5542", "field": "financial_hold", "new_value": "CLEARED"},
        description="Clear tuition hold in Student Information System",
        risk_level=RiskLevel.SENSITIVE,  # Consequential!
        depends_on=["step-01"],
    )

    plan = WorkflowPlan(
        session_id="sess-demo-02",
        correlation_id="corr-demo-02",
        title="Clear Student Financial Hold",
        steps=[step1, step2],
    )

    executor = WorkflowExecutor(plan)
    print(f"Starting workflow. Initial State: {executor.current_state.value}")

    # Run step 1; step 2 will trigger AWAITING_APPROVAL
    interim_result = executor.run()

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
    print(f"  Action Summary:  {appr_req.action_summary}")
    print(f"  Target Resource: {appr_req.target_resources}")

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
    print("Objective: Attempt to modify final exam grade (DESTRUCTIVE action).")
    print("Expected behavior: Executor pauses in AWAITING_APPROVAL; rejects action and transitions to CANCELLED.\n")

    step1 = WorkflowStep(
        step_id="step-01",
        tool_name="update_student_record",
        arguments={"student_id": "STU-9999", "field": "grade_cs101", "new_value": "A+"},
        description="Override semester grade directly without faculty board review",
        risk_level=RiskLevel.DESTRUCTIVE,  # Consequential!
    )

    plan = WorkflowPlan(
        session_id="sess-demo-03",
        correlation_id="corr-demo-03",
        title="Unauthorized Grade Override",
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
    result = executor.reject_request(approval_id, reason="Grade modifications require academic council sign-off.")

    print(f"\nExecution Finished!")
    print(f"Final State: {result.final_state.value}")
    print(f"Plan Step Status: {plan.steps[0].status.value}")
    print(f"Step Error Message: {plan.steps[0].error_message}")

    print("\nState Machine Audit History:")
    for event in executor.state_machine.history:
        print(f"  [{event.timestamp.strftime('%H:%M:%S')}] {event.from_state.value} -> {event.to_state.value} ({event.reason})")


if __name__ == "__main__":
    print("Starting Day 7 Agentic Workflow Live Execution Demonstration...\n")
    demo_harmless_workflow()
    demo_consequential_workflow_approved()
    demo_consequential_workflow_rejected()
    print_separator("Demo Completed Successfully")
