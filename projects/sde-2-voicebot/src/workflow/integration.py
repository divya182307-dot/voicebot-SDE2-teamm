"""
Reasoning Proposal, Backend Approval State & UI Integration Bridge.
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M

Days 19-20 Deliverable:
Features:
1. Ingests WorkflowProposals from Reasoning (W3), validates them with PlanValidator, and compiles WorkflowPlans.
2. BackendApprovalService managing multi-tenant approval state with atomic transitions, TTL expiry, and duplicate protection.
3. WorkflowUIBridge providing high-level UI endpoints for approval, rejection, failed-step retry, and live progress streaming.
4. Guaranteed zero-execution on duplicate, rejected, or expired approvals.
"""

from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from src.workflow.audit import ProgressEventEmitter, StepAuditLogger
from src.workflow.checkpoint import CheckpointManager, CheckpointStore
from src.workflow.idempotency import IdempotencyStore
from src.workflow.schemas import (
    ApprovalRequest,
    ApprovalStatus,
    ProgressEventType,
    RetryPolicy,
    RiskLevel,
    StepAuditRecord,
    StepStatus,
    WorkflowCheckpoint,
    WorkflowPlan,
    WorkflowProposal,
    WorkflowResult,
    WorkflowState,
    WorkflowStep,
)
from src.workflow.tools import ToolRegistry
from src.workflow.validator import PlanValidationError, PlanValidator


class ApprovalIntegrationError(Exception):
    """Raised when an approval state transition is illegal (e.g. duplicate or expired)."""


class BackendApprovalService:
    """
    Simulated thread-safe enterprise backend approval state store.
    Enforces atomic transitions, TTL expiry detection, and duplicate protection.
    """

    def __init__(self, default_ttl_seconds: float = 300.0) -> None:
        self._lock = threading.RLock()
        self._store: Dict[str, ApprovalRequest] = {}
        self.default_ttl = default_ttl_seconds

    def register_request(self, request: ApprovalRequest) -> str:
        with self._lock:
            if request.ttl_seconds is None:
                request.ttl_seconds = self.default_ttl
                request.calculate_expiration()
            self._store[request.approval_id] = copy.deepcopy(request)
            return request.approval_id

    def get_request(self, approval_id: str) -> Optional[ApprovalRequest]:
        with self._lock:
            req = self._store.get(approval_id)
            if not req:
                return None
            # Check expiry lazily
            if req.status == ApprovalStatus.PENDING and req.is_expired():
                req.status = ApprovalStatus.EXPIRED
                req.rejection_reason = "TTL expired before human decision"
            return copy.deepcopy(req)

    def list_pending(self, session_id: Optional[str] = None) -> List[ApprovalRequest]:
        with self._lock:
            pending = []
            for req in self._store.values():
                if req.status == ApprovalStatus.PENDING:
                    if req.is_expired():
                        req.status = ApprovalStatus.EXPIRED
                        req.rejection_reason = "TTL expired before human decision"
                    else:
                        if not session_id or req.session_id == session_id:
                            pending.append(copy.deepcopy(req))
            return pending

    def approve(self, approval_id: str, approver: str = "human_operator") -> ApprovalRequest:
        """
        Atomically approves a pending request.
        Raises ApprovalIntegrationError on duplicate, rejected, or expired attempts.
        """
        with self._lock:
            if approval_id not in self._store:
                raise KeyError(f"Approval request '{approval_id}' not found.")

            req = self._store[approval_id]

            if req.status == ApprovalStatus.APPROVED:
                raise ApprovalIntegrationError(
                    f"Duplicate approval rejected: Request '{approval_id}' is already approved."
                )

            if req.status == ApprovalStatus.REJECTED:
                raise ApprovalIntegrationError(
                    f"Illegal approval: Request '{approval_id}' was already rejected."
                )

            if req.is_expired() or req.status == ApprovalStatus.EXPIRED:
                req.status = ApprovalStatus.EXPIRED
                raise ApprovalIntegrationError(
                    f"Expired approval refused: Request '{approval_id}' has expired (TTL {req.ttl_seconds}s breached)."
                )

            req.status = ApprovalStatus.APPROVED
            req.decided_at = datetime.now(timezone.utc)
            req.decided_by = approver
            return copy.deepcopy(req)

    def reject(self, approval_id: str, reason: str = "Rejected by operator") -> ApprovalRequest:
        """
        Atomically rejects a pending request.
        """
        with self._lock:
            if approval_id not in self._store:
                raise KeyError(f"Approval request '{approval_id}' not found.")

            req = self._store[approval_id]

            if req.status == ApprovalStatus.REJECTED:
                raise ApprovalIntegrationError(
                    f"Duplicate rejection: Request '{approval_id}' is already rejected."
                )

            if req.status == ApprovalStatus.APPROVED:
                raise ApprovalIntegrationError(
                    f"Illegal rejection: Request '{approval_id}' was already approved."
                )

            req.status = ApprovalStatus.REJECTED
            req.decided_at = datetime.now(timezone.utc)
            req.rejection_reason = reason
            return copy.deepcopy(req)

    def check_expirations(self) -> List[str]:
        """Scans and marks all expired pending requests."""
        expired_ids = []
        with self._lock:
            for aid, req in self._store.items():
                if req.status == ApprovalStatus.PENDING and req.is_expired():
                    req.status = ApprovalStatus.EXPIRED
                    req.rejection_reason = "TTL expired before human decision"
                    expired_ids.append(aid)
        return expired_ids


class WorkflowProposalParser:
    """
    Translates high-level proposals generated by the Reasoning module (W3)
    into validated, executable WorkflowPlans.
    """

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        validator: Optional[PlanValidator] = None,
    ) -> None:
        self.registry = registry or ToolRegistry.get_default_registry()
        self.validator = validator or PlanValidator()

    def parse_and_validate(
        self,
        proposal: WorkflowProposal,
        caller_permissions: Optional[List[str]] = None,
    ) -> WorkflowPlan:
        """
        Transforms a WorkflowProposal into a validated WorkflowPlan.
        Enforces DAG integrity, tool allow-list, argument types, and permission scopes.
        """
        steps: List[WorkflowStep] = []
        for p_step in proposal.proposed_steps:
            step = WorkflowStep(
                step_id=p_step.step_id,
                tool_name=p_step.tool_name,
                arguments=dict(p_step.arguments),
                description=p_step.description,
                risk_level=p_step.risk_level,
                depends_on=list(p_step.depends_on),
                timeout_seconds=p_step.timeout_seconds,
                retry_policy=RetryPolicy(max_retries=2, backoff_seconds=0.01) if p_step.is_idempotent else None,
                is_idempotent=p_step.is_idempotent,
            )
            steps.append(step)

        plan = WorkflowPlan(
            plan_id=f"plan-{uuid4().hex[:8]}",
            session_id=proposal.session_id,
            correlation_id=proposal.correlation_id,
            title=proposal.title,
            steps=steps,
            metadata={
                "proposal_id": proposal.proposal_id,
                "source_utterance": proposal.source_utterance,
                "intent": proposal.intent,
                "confidence": proposal.confidence,
                **proposal.metadata,
            },
        )

        # Validate against PlanValidator
        validator = PlanValidator(
            registry=self.registry,
            granted_permissions=caller_permissions,
        )
        validator.validate_plan(plan)

        return plan


class WorkflowUIBridge:
    """
    High-level integration bridge for frontend/UI controllers.
    Provides clean UI endpoints for:
      • Ingesting proposals from reasoning
      • Approving / rejecting consequential actions
      • Retrying failed steps from checkpoints
      • Live-streaming progress events to UI listeners
      • Inspecting audit trails and checkpoints
    """

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        approval_service: Optional[BackendApprovalService] = None,
        checkpoint_store: Optional[CheckpointStore] = None,
        audit_logger: Optional[StepAuditLogger] = None,
        event_emitter: Optional[ProgressEventEmitter] = None,
    ) -> None:
        self.registry = registry or ToolRegistry.get_default_registry()
        self.approval_service = approval_service or BackendApprovalService()
        self.checkpoint_store = checkpoint_store or CheckpointStore()
        self.checkpoint_manager = CheckpointManager(self.checkpoint_store)
        self.audit_logger = audit_logger or StepAuditLogger()
        self.event_emitter = event_emitter or ProgressEventEmitter()
        self.proposal_parser = WorkflowProposalParser(self.registry)
        self.idempotency_store = IdempotencyStore()

        self._plans: Dict[str, WorkflowPlan] = {}
        self._executors: Dict[str, Any] = {}

    def submit_proposal(
        self,
        proposal: WorkflowProposal,
        caller_permissions: Optional[List[str]] = None,
    ) -> WorkflowPlan:
        """Parses and validates a reasoning proposal, storing it as an executable plan."""
        plan = self.proposal_parser.parse_and_validate(proposal, caller_permissions)
        self._plans[plan.plan_id] = plan
        return plan

    def get_plan(self, plan_id: str) -> Optional[WorkflowPlan]:
        return self._plans.get(plan_id)

    def execute_workflow(
        self,
        plan_id: str,
        caller_permissions: Optional[List[str]] = None,
    ) -> Optional[WorkflowResult]:
        """Launches or resumes execution of a validated plan."""
        from src.workflow.executor import WorkflowExecutor

        if plan_id not in self._plans:
            raise KeyError(f"Plan '{plan_id}' not found.")

        plan = self._plans[plan_id]

        if plan_id not in self._executors:
            executor = WorkflowExecutor(
                plan=plan,
                registry=self.registry,
                caller_permissions=caller_permissions,
                checkpoint_manager=self.checkpoint_manager,
                idempotency_store=self.idempotency_store,
                audit_logger=self.audit_logger,
                event_emitter=self.event_emitter,
                backend_approval_service=self.approval_service,
            )
            self._executors[plan_id] = executor
        else:
            executor = self._executors[plan_id]

        return executor.run()

    def list_pending_approvals(self, session_id: Optional[str] = None) -> List[ApprovalRequest]:
        """Returns all currently pending approval requests from the backend approval service."""
        return self.approval_service.list_pending(session_id)

    def ui_approve(
        self,
        approval_id: str,
        approver: str = "ui_supervisor",
        resume: bool = True,
    ) -> Optional[WorkflowResult]:
        """
        Processes an approval action from the UI.
        Delegates to BackendApprovalService and resumes the relevant executor.
        """
        # Atomically approve on backend service
        req = self.approval_service.approve(approval_id, approver=approver)

        executor = self._executors.get(req.plan_id)
        if not executor:
            raise KeyError(f"Executor for plan '{req.plan_id}' not found.")

        return executor.approve_request(approval_id, approver=approver, resume=resume)

    def ui_reject(
        self,
        approval_id: str,
        reason: str = "Rejected via UI supervisor action",
    ) -> WorkflowResult:
        """
        Processes a rejection action from the UI.
        Guarantees ZERO tool execution and cancels the workflow safely.
        """
        req = self.approval_service.reject(approval_id, reason=reason)

        executor = self._executors.get(req.plan_id)
        if not executor:
            raise KeyError(f"Executor for plan '{req.plan_id}' not found.")

        return executor.reject_request(approval_id, reason=reason)

    def ui_recover_failed_step(
        self,
        plan_id: str,
        step_id: str,
        updated_arguments: Optional[Dict[str, Any]] = None,
        resume: bool = True,
    ) -> Optional[WorkflowResult]:
        """
        Recovers a failed step from a checkpoint without re-running earlier steps.
        """
        executor = self._executors.get(plan_id)
        if not executor:
            raise KeyError(f"Executor for plan '{plan_id}' not found.")

        return executor.recover_failed_step(
            step_id=step_id,
            updated_arguments=updated_arguments,
            resume=resume,
        )

    def get_audit_trail(self, plan_id: Optional[str] = None) -> List[StepAuditRecord]:
        return self.audit_logger.get_trail(plan_id)

    def get_checkpoints(self, plan_id: str) -> List[WorkflowCheckpoint]:
        return self.checkpoint_store.list_checkpoints(plan_id)

    def subscribe_events(self, listener: Callable[[ProgressEvent], None]) -> None:
        self.event_emitter.subscribe(listener)

