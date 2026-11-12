"""
Workflow Executor for Academiaai AI Voicebot Agentic Workflow Engine.
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M

Week 1 (Days 3-4): Orchestrates WorkflowPlan execution through state machine transitions.
                   Safety Guard: Consequential actions strictly default to awaiting human approval.
Week 2 (Days 10-13): Safe execution with:
                   - Approval expiry logic (expired approval guarantees no tool execution + audit event)
                   - Approval rejection guarantees no tool execution + audit event
                   - Execution timeouts per step
                   - Bounded retries strictly for idempotent steps
                   - Immediate cancellation
                   - Permission scope checks
Everything runs in safe mock mode.
"""

import concurrent.futures
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set
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
    
    Week 2 Safety Guarantees:
    1. Consequential steps (SENSITIVE / DESTRUCTIVE) halt execution and await human approval.
    2. Rejection or expiry guarantees zero tool execution and writes a safe audit event.
    3. Timeouts are enforced per step.
    4. Retries are strictly bounded and only attempted for idempotent steps.
    5. Permission scopes are verified before execution.
    """

    def __init__(
        self,
        plan: WorkflowPlan,
        registry: Optional[ToolRegistry] = None,
        auto_approve_informational: bool = True,
        caller_permissions: Optional[Iterable[str]] = None,
        default_step_timeout: Optional[float] = None,
        default_approval_ttl_seconds: Optional[float] = 300.0,
    ):
        self.plan = plan
        self.registry = registry or ToolRegistry.get_default_registry()
        self.auto_approve_informational = auto_approve_informational
        self.caller_permissions: Optional[List[str]] = (
            list(caller_permissions) if caller_permissions is not None else None
        )
        self.default_step_timeout = default_step_timeout
        self.default_approval_ttl_seconds = default_approval_ttl_seconds
        self.state_machine = WorkflowStateMachine(self.plan)

        # Execution tracking
        self.step_results: Dict[str, Any] = {}
        self.pending_approvals: Dict[str, ApprovalRequest] = {}
        self.approved_step_ids: Set[str] = set()
        self.events: List[ExecutionEvent] = []
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None

    @property
    def current_state(self) -> WorkflowState:
        return self.state_machine.current_state

    def _log_event(
        self,
        event_type: str,
        message: str,
        step_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        event = ExecutionEvent(
            step_id=step_id,
            event_type=event_type,
            message=message,
            data=data,
        )
        self.events.append(event)

    def is_step_consequential(self, step: WorkflowStep) -> bool:
        """
        Determines if a step is consequential and requires explicit human approval.
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
        """Constructs an ApprovalRequest for a consequential step with TTL support."""
        target_resources = []
        for key in ("path", "target", "student_id", "recipient", "resource", "course_code"):
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
            ttl_seconds=self.default_approval_ttl_seconds,
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
        If the request has already expired, approval is refused, guaranteeing zero execution.
        """
        if approval_id not in self.pending_approvals:
            raise KeyError(f"Approval request '{approval_id}' not found among pending approvals.")

        request = self.pending_approvals[approval_id]

        # Check if request has expired
        if request.is_expired():
            return self.expire_request(approval_id, reason="Approval granted after request TTL expired")

        self.pending_approvals.pop(approval_id)
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
        Guarantees NO tool execution occurs and transitions workflow safely to CANCELLED.
        """
        if approval_id not in self.pending_approvals:
            raise KeyError(f"Approval request '{approval_id}' not found among pending approvals.")

        request = self.pending_approvals.pop(approval_id)
        request.status = ApprovalStatus.REJECTED
        request.decided_at = datetime.now(timezone.utc)
        request.rejection_reason = reason

        # Find target step and mark it CANCELLED
        for step in self.plan.steps:
            if step.step_id == request.step_id:
                step.status = StepStatus.CANCELLED
                step.error_message = f"Approval rejected: {reason}"
                break

        # Cancel any downstream pending steps to guarantee zero execution
        for step in self.plan.steps:
            if step.status == StepStatus.PENDING:
                step.status = StepStatus.CANCELLED

        self._log_event(
            event_type="APPROVAL_REJECTED",
            message=f"Approval rejected for step {request.step_id}: {reason}. Tool execution prevented.",
            step_id=request.step_id,
            data={"approval_id": approval_id, "reason": reason},
        )

        if self.current_state != WorkflowState.CANCELLED:
            self.state_machine.transition(
                WorkflowState.CANCELLED,
                reason=f"Workflow cancelled due to rejection of approval request {approval_id}: {reason}",
            )

        self.completed_at = datetime.now(timezone.utc)
        return self._build_result(error_details={"cancelled_by_rejection": approval_id, "reason": reason})

    def expire_request(
        self,
        approval_id: str,
        reason: str = "Approval request TTL expired without human decision",
    ) -> WorkflowResult:
        """
        Expires an approval request.
        Guarantees NO tool execution occurs and transitions workflow safely to CANCELLED.
        """
        if approval_id not in self.pending_approvals:
            raise KeyError(f"Approval request '{approval_id}' not found among pending approvals.")

        request = self.pending_approvals.pop(approval_id)
        request.status = ApprovalStatus.EXPIRED
        request.decided_at = datetime.now(timezone.utc)
        request.rejection_reason = reason

        for step in self.plan.steps:
            if step.step_id == request.step_id:
                step.status = StepStatus.CANCELLED
                step.error_message = f"Approval expired: {reason}"
                break

        for step in self.plan.steps:
            if step.status == StepStatus.PENDING:
                step.status = StepStatus.CANCELLED

        self._log_event(
            event_type="APPROVAL_EXPIRED",
            message=f"Approval request {approval_id} for step {request.step_id} expired. Tool execution strictly prevented.",
            step_id=request.step_id,
            data={"approval_id": approval_id, "reason": reason},
        )

        if self.current_state != WorkflowState.CANCELLED:
            self.state_machine.transition(
                WorkflowState.CANCELLED,
                reason=f"Workflow cancelled due to expiration of approval request {approval_id}: {reason}",
            )

        self.completed_at = datetime.now(timezone.utc)
        return self._build_result(error_details={"cancelled_by_expiry": approval_id, "reason": reason})

    def check_for_expired_approvals(self) -> Optional[WorkflowResult]:
        """
        Scans all pending approvals and expires any that have exceeded their TTL.
        """
        expired_ids = [
            appr_id for appr_id, req in self.pending_approvals.items()
            if req.is_expired()
        ]
        if expired_ids:
            return self.expire_request(expired_ids[0])
        return None

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
        """
        Cancels the workflow immediately. Guarantees no further tool executions occur.
        """
        # Cancel all non-completed steps
        for step in self.plan.steps:
            if step.status in (StepStatus.PENDING, StepStatus.AWAITING_APPROVAL, StepStatus.RUNNING):
                step.status = StepStatus.CANCELLED
                step.error_message = f"Cancelled: {reason}"

        self.pending_approvals.clear()

        if self.current_state != WorkflowState.CANCELLED:
            self.state_machine.transition(WorkflowState.CANCELLED, reason=reason)

        self._log_event("WORKFLOW_CANCELLED", f"Workflow cancelled: {reason}")
        self.completed_at = datetime.now(timezone.utc)
        return self._build_result(error_details={"cancellation_reason": reason})

    def _execute_step_with_timeout_and_retries(self, step: WorkflowStep, tool: Any) -> Any:
        """
        Executes a step enforcing:
        1. Step timeout
        2. Bounded retries strictly if is_idempotent is True
        """
        timeout = step.timeout_seconds if step.timeout_seconds is not None else self.default_step_timeout
        retry_policy = step.retry_policy

        def _invoke_tool():
            # Validate permissions before running
            if self.caller_permissions is not None:
                tool.check_permissions(self.caller_permissions)
            return tool.execute(step.arguments)

        def _invoke_with_timeout():
            if timeout is None:
                return _invoke_tool()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_invoke_tool)
                try:
                    return future.result(timeout=timeout)
                except concurrent.futures.TimeoutError as te:
                    raise TimeoutError(f"Step '{step.step_id}' execution timed out after {timeout} seconds") from te

        # Check if step execution succeeds or requires retry
        attempt = 0
        max_retries = (retry_policy.max_retries if retry_policy and step.is_idempotent else 0)

        while True:
            try:
                return _invoke_with_timeout()
            except Exception as e:
                attempt += 1
                # Check if retry is permitted
                can_retry = (
                    step.is_idempotent
                    and retry_policy is not None
                    and attempt <= max_retries
                )

                if not step.is_idempotent and retry_policy is not None:
                    self._log_event(
                        event_type="RETRY_SKIPPED",
                        message=f"Step '{step.step_id}' is non-idempotent; retries strictly prohibited.",
                        step_id=step.step_id,
                        data={"attempt": attempt, "error": str(e)},
                    )

                if can_retry:
                    self._log_event(
                        event_type="STEP_RETRY_ATTEMPT",
                        message=f"Step '{step.step_id}' failed: {e}. Retrying ({attempt}/{max_retries})...",
                        step_id=step.step_id,
                        data={"attempt": attempt, "max_retries": max_retries, "error": str(e)},
                    )
                    if retry_policy and retry_policy.backoff_seconds > 0:
                        time.sleep(retry_policy.backoff_seconds)
                else:
                    if retry_policy and step.is_idempotent and attempt > max_retries:
                        self._log_event(
                            event_type="RETRIES_EXHAUSTED",
                            message=f"Step '{step.step_id}' exhausted all {max_retries} retries.",
                            step_id=step.step_id,
                            data={"attempts": attempt, "error": str(e)},
                        )
                    raise

    def run(self) -> Optional[WorkflowResult]:
        """
        Primary execution entry point.
        Executes plan steps sequentially, evaluating safety conditions,
        dependencies, expiry, and tool execution.
        """
        if self.started_at is None:
            self.started_at = datetime.now(timezone.utc)

        # Check for expired pending approvals first
        expired_result = self.check_for_expired_approvals()
        if expired_result is not None:
            return expired_result

        # Transition initial DRAFT state
        if self.current_state == WorkflowState.DRAFT:
            self.state_machine.transition(
                WorkflowState.RUNNING,
                reason="Starting workflow execution in safe mock mode",
            )
            self._log_event("WORKFLOW_STARTED", "Workflow execution started in safe mock mode")

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
                    data={"approval_id": approval_req.approval_id, "risk_level": step.risk_level.value, "ttl_seconds": approval_req.ttl_seconds},
                )
                # Halt execution loop until approval is granted
                return None

            # Tool Execution (Mock Mode)
            if not self.registry.has(step.tool_name):
                step.status = StepStatus.FAILED
                err = f"Tool '{step.tool_name}' not registered in tool registry allow-list"
                step.error_message = err
                self.state_machine.transition(WorkflowState.FAILED, reason=err)
                self.completed_at = datetime.now(timezone.utc)
                return self._build_result(error_details={"failed_step": step.step_id, "error": err})

            tool = self.registry.get(step.tool_name)

            # Check permissions
            if self.caller_permissions is not None:
                try:
                    tool.check_permissions(self.caller_permissions)
                except PermissionError as pe:
                    step.status = StepStatus.FAILED
                    err = str(pe)
                    step.error_message = err
                    self._log_event("PERMISSION_DENIED", err, step_id=step.step_id)
                    self.state_machine.transition(WorkflowState.FAILED, reason=err)
                    self.completed_at = datetime.now(timezone.utc)
                    return self._build_result(error_details={"failed_step": step.step_id, "error": err})

            step.status = StepStatus.RUNNING
            self._log_event("STEP_STARTED", f"Executing step '{step.step_id}' with tool '{step.tool_name}'", step_id=step.step_id)

            try:
                result = self._execute_step_with_timeout_and_retries(step, tool)
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
