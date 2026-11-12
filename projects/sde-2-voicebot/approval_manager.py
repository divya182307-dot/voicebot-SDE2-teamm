"""
approval_manager.py — D10-11
Manages the lifecycle of ApprovalRequests:
  • approve(id)  → marks APPROVED if still PENDING and not expired
  • reject(id)   → marks REJECTED; guarantees no execution proceeds
  • expire check → any PENDING approval past expires_at is treated as EXPIRED
  • All state changes are recorded in an in-memory audit log
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from schemas import (
    ApprovalRequest,
    ApprovalStatus,
    ExecutionRecord,
    ExecutionStatus,
    RiskLevel,
)


class ApprovalError(Exception):
    """Raised when an operation violates approval rules."""


class ApprovalManager:
    """
    In-memory approval store.
    In production this would persist to a database; for the MVP mock
    layer an in-process dict is sufficient and keeps tests deterministic.
    """

    DEFAULT_TTL_SECONDS = 300  # 5 minutes

    def __init__(self, default_ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._store: Dict[str, ApprovalRequest] = {}
        self._audit: List[str] = []          # simple append-only audit log
        self._ttl = default_ttl_seconds

    # ------------------------------------------------------------------ public

    def create(
        self,
        plan_id: str,
        risk_level: RiskLevel,
        reason: str = "",
        ttl_seconds: Optional[int] = None,
    ) -> ApprovalRequest:
        """Create a new PENDING approval request for a plan."""
        now = datetime.now(timezone.utc)
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl
        req = ApprovalRequest(
            approval_id=str(uuid.uuid4()),
            plan_id=plan_id,
            risk_level=risk_level,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl),
            status=ApprovalStatus.PENDING,
            reason=reason,
        )
        self._store[req.approval_id] = req
        self._log(f"CREATED approval={req.approval_id} plan={plan_id} risk={risk_level.value}")
        return req

    def approve(self, approval_id: str, decided_by: str = "user") -> ApprovalRequest:
        """Approve a PENDING, non-expired request."""
        req = self._get_or_raise(approval_id)
        self._raise_if_not_pending(req)
        self._raise_if_expired(req)
        req.status = ApprovalStatus.APPROVED
        req.decided_at = datetime.now(timezone.utc)
        req.decided_by = decided_by
        self._log(f"APPROVED approval={approval_id} by={decided_by}")
        return req

    def reject(self, approval_id: str, decided_by: str = "user") -> ApprovalRequest:
        """Reject a PENDING request.  Rejection always blocks execution."""
        req = self._get_or_raise(approval_id)
        self._raise_if_not_pending(req)
        # NOTE: expiry check intentionally skipped — we allow explicit rejection
        #       even of already-expired requests for auditability.
        req.status = ApprovalStatus.REJECTED
        req.decided_at = datetime.now(timezone.utc)
        req.decided_by = decided_by
        self._log(f"REJECTED approval={approval_id} by={decided_by}")
        return req

    def get_status(self, approval_id: str) -> ApprovalStatus:
        """Return current status, auto-expiring PENDING requests past their TTL."""
        req = self._get_or_raise(approval_id)
        if req.status == ApprovalStatus.PENDING and self._is_expired(req):
            req.status = ApprovalStatus.EXPIRED
            self._log(f"EXPIRED approval={approval_id}")
        return req.status

    def is_approved(self, approval_id: str) -> bool:
        """True iff the request is in APPROVED state and not expired."""
        return self.get_status(approval_id) == ApprovalStatus.APPROVED

    def make_safe_audit_record(
        self,
        approval_id: str,
        plan_id: str,
        execution_id: Optional[str] = None,
    ) -> ExecutionRecord:
        """
        Produce an ExecutionRecord that records a safe no-op when execution
        was blocked by rejection or expiry.  No tool is ever invoked.
        """
        status = self.get_status(approval_id)
        note = (
            f"approval={approval_id} status={status.value}; "
            "execution blocked — no tool was invoked."
        )
        record = ExecutionRecord(
            execution_id=execution_id or str(uuid.uuid4()),
            plan_id=plan_id,
            approval_id=approval_id,
            status=ExecutionStatus.CANCELLED,
            audit_note=note,
        )
        self._log(f"SAFE_AUDIT_RECORD execution={record.execution_id} {note}")
        return record

    @property
    def audit_log(self) -> List[str]:
        return list(self._audit)

    # ------------------------------------------------------------------ private

    def _get_or_raise(self, approval_id: str) -> ApprovalRequest:
        req = self._store.get(approval_id)
        if req is None:
            raise ApprovalError(f"Unknown approval_id: '{approval_id}'")
        return req

    def _raise_if_not_pending(self, req: ApprovalRequest) -> None:
        if req.status != ApprovalStatus.PENDING:
            raise ApprovalError(
                f"Approval '{req.approval_id}' is already in state "
                f"'{req.status.value}'; cannot modify it."
            )

    def _raise_if_expired(self, req: ApprovalRequest) -> None:
        if self._is_expired(req):
            req.status = ApprovalStatus.EXPIRED
            self._log(f"EXPIRED approval={req.approval_id} (detected on approve attempt)")
            raise ApprovalError(
                f"Approval '{req.approval_id}' has expired; it cannot be approved."
            )

    @staticmethod
    def _is_expired(req: ApprovalRequest) -> bool:
        if req.expires_at is None:
            return False
        return datetime.now(timezone.utc) > req.expires_at

    def _log(self, message: str) -> None:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._audit.append(f"[{ts}] {message}")

