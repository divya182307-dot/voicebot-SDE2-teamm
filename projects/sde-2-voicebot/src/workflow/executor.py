"""
Workflow Executor for Academiaai AI Voicebot Agentic Workflow Engine.
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M

Day 3-4 Deliverable:
Orchestrates WorkflowPlan execution through state machine transitions.
Safety Guard: Consequential actions (SENSITIVE or DESTRUCTIVE risk level,
or steps marked requires_approval=True) strictly default to awaiting human approval.
Everything runs in safe mock mode.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4
from pydantic import BaseModel, Field

from src.workflow.schemas import (
    ApprovalRequest,
    ApprovalStatus,
    RiskLevel,
    StepStatus,
    ToolFailureBehavior,
    WorkflowPlan,
    WorkflowResult,
    WorkflowState,
    WorkflowStep,
)
from src.workflow.state_machine import WorkflowStateMachine
from src.workflow.tools import ToolRegistry


class ExecutionEvent(BaseModel):
    """Log record for an execution event within the workflow run."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    step_id: Optional[str] = None
    event_type: str
    message: str
    data: Optional[Dict[str, Any]] = None


class WorkflowExecutor:
    """
    Executes a WorkflowPlan using allow-listed tools from ToolRegistry,
    governed by the WorkflowStateMachine lifecycle rules.
    
    Safety Guarantee:
    Any step with SENSITIVE or DESTRUCTIVE risk level, or explicit requires_approval=True,
    will halt execution and transition the workflow to AWAITING_APPROVAL until explicitly approved.
    """

    def __init__(
        self,
        plan: WorkflowPlan,
        registry: Optional[ToolRegistry] = None,
        auto_approve_informational: bool = True,
    ):
        self.plan = plan
        self.registry = registry or ToolRegistry.get_default_registry()
        self.auto_approve_informational = auto_approve_informational
        self.state_machine = WorkflowStateMachine(self.plan)

        # Execution tracking
        self.step_results: Dict[str, Any] = {}
        self.pending_approvals: Dict[str, ApprovalRequest] = {}
        self.approved_step_ids: set[str] = set()
        self.events: List[ExecutionEvent] = []
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None

    @property
    def current_state(self) -> WorkflowState:
        return self.state_machine.current_state

    def _log_event(self, event_type: str, message: str, step_id: Optional[str] = None, data: Optional[Dict[str, Any]] = None) -> None:
        event = ExecutionEvent(
            step_id=step_id,
            event_type=event_type,
            message=message,
            data=data,
        )
        self.events.append(event)

    def is_step_consequential(self, step: WorkflowStep) -> bool:
        """
        Determines if a step is consequential and requires explicit approval.
        Enforces both step-level and tool-level risk assessments.
        """
        if step.requires_approval:
            return True
        if step.risk_level in (RiskLevel.SENSITIVE, RiskLevel.DESTRUCTIVE):
            return True
        if self.registry.has(step.tool_name):
            tool = self.registry.get(step.tool_name)
            if tool.is_consequential:
                return True
        return False

    def create_approval_request(self, step: WorkflowStep) -> ApprovalRequest:
        """Constructs an ApprovalRequest for a consequential step."""
        # Inspect target resources from arguments if present
        target_resources = []
        for key in ("path", "target", "student_id", "recipient", "resource"):
            if key in step.arguments:
                target_resources.append(str(step.arguments[key]))

        request = ApprovalRequest(
            approval_id=f"appr-{uuid4().hex[:8]}",
            session_id=self.plan.session_id,
            correlation_id=self.plan.correlation_id,
            plan_id=self.plan.plan_id,
            step_id=step.step_id,
            tool_name=step.tool_name,
            risk_level=step.risk_level,
            action_summary=f"Execution of '{step.tool_name}': {step.description}",
            target_resources=target_resources,
            status=ApprovalStatus.PENDING,
        )
        return request

    def approve_request(
        self,
        approval_id: str,
        approver: str = "human_operator",
        resume: bool = True,
    ) -> Optional[WorkflowResult]:
        """
        Grants approval for a pending consequential action.
        Transitions state from AWAITING_APPROVAL back to RUNNING and optionally resumes execution.
        """
        if approval_id not in self.pending_approvals:
            raise KeyError(f"Approval request '{approval_id}' not found among pending approvals.")

        request = self.pending_approvals.pop(approval_id)
        request.status = ApprovalStatus.APPROVED
        request.decided_at = datetime.now(timezone.utc)
        self.approved_step_ids.add(request.step_id)

        self._log_event(
            event_type="APPROVAL_GRANTED",
            message=f"Approval granted by {approver} for step {request.step_id} ({request.tool_name})",
            step_id=request.step_id,
            data={"approval_id": approval_id, "approver": approver},
        )

        # Transition back to RUNNING if no other pending approvals
        if len(self.pending_approvals) == 0 and self.current_state == WorkflowState.AWAITING_APPROVAL:
            self.state_machine.transition(
                WorkflowState.RUNNING,
                reason=f"Approval granted for step {request.step_id}",
            )

        if resume:
            return self.run()
        return None

    def reject_request(
        self,
        approval_id: str,
        reason: str = "Rejected by human supervisor",
    ) -> WorkflowResult:
        """
        Rejects a consequential step.
        Per safety PRD policy, rejection halts the workflow and transitions state machine to CANCELLED.
        """
        if approval_id not in self.pending_approvals:
            raise KeyError(f"Approval request '{approval_id}' not found among pending approvals.")

        request = self.pending_approvals.pop(approval_id)
        request.status = ApprovalStatus.REJECTED
        request.decided_at = datetime.now(timezone.utc)
        request.rejection_reason = reason

        # Find target step and cancel it
        for step in self.plan.steps:
            if step.step_id == request.step_id:
                step.status = StepStatus.CANCELLED
                step.error_message = f"Approval rejected: {reason}"
                break

        self._log_event(
            event_type="APPROVAL_REJECTED",
            message=f"Approval rejected for step {request.step_id}: {reason}",
            step_id=request.step_id,
            data={"approval_id": approval_id, "reason": reason},
        )

        # Transition state machine to CANCELLED
        if self.current_state != WorkflowState.CANCELLED:
            self.state_machine.transition(
                WorkflowState.CANCELLED,
                reason=f"Workflow cancelled due to rejection of approval request {approval_id}: {reason}",
            )

        self.completed_at = datetime.now(timezone.utc)
        return self._build_result()

    def pause(self, reason: str = "Paused by operator") -> None:
        """Pauses a currently RUNNING workflow."""
        if self.current_state != WorkflowState.RUNNING:
            raise ValueError(f"Cannot pause workflow in '{self.current_state.value}' state.")
        self.state_machine.transition(WorkflowState.PAUSED, reason=reason)
        self._log_event("WORKFLOW_PAUSED", f"Workflow paused: {reason}")

    def resume(self) -> Optional[WorkflowResult]:
        """Resumes a PAUSED workflow."""
        if self.current_state != WorkflowState.PAUSED:
            raise ValueError(f"Cannot resume workflow in '{self.current_state.value}' state.")
        self.state_machine.transition(WorkflowState.RUNNING, reason="Resuming paused workflow")
        self._log_event("WORKFLOW_RESUMED", "Workflow resumed")
        return self.run()

    def cancel(self, reason: str = "Cancelled by operator") -> WorkflowResult:
        """Cancels the workflow."""
        self.state_machine.transition(WorkflowState.CANCELLED, reason=reason)
        self._log_event("WORKFLOW_CANCELLED", f"Workflow cancelled: {reason}")
        self.completed_at = datetime.now(timezone.utc)
        return self._build_result()

    def run(self) -> Optional[WorkflowResult]:
        """
        Primary execution entry point.
        Executes plan steps sequentially, evaluating safety conditions,
        dependencies, and tool execution.
        
        Returns:
            WorkflowResult: If the workflow completes (SUCCEEDED, FAILED, or CANCELLED).
            None: If workflow enters AWAITING_APPROVAL and is waiting for external action.
        """
        if self.started_at is None:
            self.started_at = datetime.now(timezone.utc)

        # Transition initial DRAFT state
        if self.current_state == WorkflowState.DRAFT:
            self.state_machine.transition(
                WorkflowState.RUNNING,
                reason="Starting workflow execution in mock mode",
            )
            self._log_event("WORKFLOW_STARTED", "Workflow execution started in mock mode")

        # Main execution loop
        for step in self.plan.steps:
            # Skip already finished steps
            if step.status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED):
                continue

            # Verify dependencies
            deps_satisfied = True
            for dep_id in step.depends_on:
                dep_step = next((s for s in self.plan.steps if s.step_id == dep_id), None)
                if not dep_step or dep_step.status != StepStatus.SUCCEEDED:
                    deps_satisfied = False
                    break

            if not deps_satisfied:
                step.status = StepStatus.FAILED
                step.error_message = f"Unsatisfied dependency for step '{step.step_id}'"
                self.state_machine.transition(
                    WorkflowState.FAILED,
                    reason=f"Step '{step.step_id}' dependency failed",
                )
                self.completed_at = datetime.now(timezone.utc)
                return self._build_result(error_details={"failed_step": step.step_id, "error": step.error_message})

            # Check Consequential Action & Approval
            if self.is_step_consequential(step) and step.step_id not in self.approved_step_ids:
                step.status = StepStatus.AWAITING_APPROVAL
                approval_req = self.create_approval_request(step)
                self.pending_approvals[approval_req.approval_id] = approval_req

                if self.current_state != WorkflowState.AWAITING_APPROVAL:
                    self.state_machine.transition(
                        WorkflowState.AWAITING_APPROVAL,
                        reason=f"Consequential action in step '{step.step_id}' ({step.tool_name}) requires approval",
                    )
                self._log_event(
                    event_type="AWAITING_APPROVAL",
                    message=f"Step '{step.step_id}' ({step.tool_name}) paused awaiting human approval",
                    step_id=step.step_id,
                    data={"approval_id": approval_req.approval_id, "risk_level": step.risk_level.value},
                )
                # Halt execution loop until approval is granted
                return None

            # Tool Execution (Mock Mode)
            if not self.registry.has(step.tool_name):
                step.status = StepStatus.FAILED
                err = f"Tool '{step.tool_name}' not registered in tool registry"
                step.error_message = err
                self.state_machine.transition(WorkflowState.FAILED, reason=err)
                self.completed_at = datetime.now(timezone.utc)
                return self._build_result(error_details={"failed_step": step.step_id, "error": err})

            tool = self.registry.get(step.tool_name)
            step.status = StepStatus.RUNNING
            self._log_event("STEP_STARTED", f"Executing step '{step.step_id}' with tool '{step.tool_name}'", step_id=step.step_id)

            try:
                result = tool.execute(step.arguments)
                step.status = StepStatus.SUCCEEDED
                step.result = result
                self.step_results[step.step_id] = result
                self._log_event(
                    event_type="STEP_COMPLETED",
                    message=f"Step '{step.step_id}' finished successfully",
                    step_id=step.step_id,
                    data={"result_summary": str(result)[:100]},
                )
            except Exception as e:
                step.status = StepStatus.FAILED
                step.error_message = str(e)
                self._log_event("STEP_FAILED", f"Step '{step.step_id}' failed: {e}", step_id=step.step_id)

                if step.risk_level == RiskLevel.DESTRUCTIVE or not (hasattr(tool.spec, 'failure_behavior') and tool.spec.failure_behavior == ToolFailureBehavior.IGNORE_AND_CONTINUE):
                    self.state_machine.transition(
                        WorkflowState.FAILED,
                        reason=f"Step '{step.step_id}' failed with error: {str(e)}",
                    )
                    self.completed_at = datetime.now(timezone.utc)
                    return self._build_result(error_details={"failed_step": step.step_id, "error": str(e)})

        # All steps completed successfully
        if all(s.status == StepStatus.SUCCEEDED for s in self.plan.steps):
            if self.current_state == WorkflowState.RUNNING:
                self.state_machine.transition(
                    WorkflowState.SUCCEEDED,
                    reason="All workflow steps executed successfully",
                )
            self.completed_at = datetime.now(timezone.utc)
            self._log_event("WORKFLOW_COMPLETED", "Workflow reached SUCCEEDED terminal state")
            return self._build_result()

        return None

    def _build_result(self, error_details: Optional[Dict[str, Any]] = None) -> WorkflowResult:
        """Generates the final WorkflowResult report."""
        return WorkflowResult(
            plan_id=self.plan.plan_id,
            session_id=self.plan.session_id,
            correlation_id=self.plan.correlation_id,
            final_state=self.current_state,
            step_results=self.step_results,
            started_at=self.started_at or datetime.now(timezone.utc),
            completed_at=self.completed_at or datetime.now(timezone.utc),
            error_details=error_details,
        )
