"""
Step-Level Audit Trail and Progress Events System for Academiaai Voicebot.
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M

Days 17-18 Deliverable:
Features:
1. Immutable step-level audit trail recording every step invocation with timing, inputs, outputs, errors.
2. Real-time typed progress event emission (ProgressEventType) for UI dashboards and live streaming.
3. Listener subscription model for live event streaming to UI/backend consumers.
"""

from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from src.workflow.schemas import (
    ProgressEvent,
    ProgressEventType,
    StepAuditRecord,
    StepStatus,
)


class StepAuditLogger:
    """
    Immutable, append-only logger for step-level audit records.
    Captures duration_ms, arguments, results, and idempotency tracking.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: List[StepAuditRecord] = []

    def record_step(
        self,
        plan_id: str,
        step_id: str,
        tool_name: str,
        status: StepStatus,
        arguments: Dict[str, Any],
        started_at: datetime,
        completed_at: Optional[datetime] = None,
        result: Optional[Any] = None,
        error_message: Optional[str] = None,
        attempts: int = 1,
        duration_ms: Optional[float] = None,
        idempotency_key: Optional[str] = None,
    ) -> StepAuditRecord:
        """Appends an immutable audit record for a completed or failed step execution."""
        ended = completed_at or datetime.now(timezone.utc)
        if duration_ms is None:
            calc_duration = max(0.0, (ended - started_at).total_seconds() * 1000.0)
        else:
            calc_duration = duration_ms

        # Sanitize sensitive arguments
        sanitized_args = {}
        for k, v in arguments.items():
            if any(term in k.lower() for term in ("token", "password", "secret", "auth")):
                sanitized_args[k] = "******"
            else:
                sanitized_args[k] = v

        record = StepAuditRecord(
            audit_id=f"audit-{uuid4().hex[:10]}",
            plan_id=plan_id,
            step_id=step_id,
            tool_name=tool_name,
            status=status,
            arguments=sanitized_args,
            result=copy.deepcopy(result),
            error_message=error_message,
            attempts=attempts,
            duration_ms=round(calc_duration, 2),
            idempotency_key=idempotency_key,
            started_at=started_at,
            completed_at=ended,
        )

        with self._lock:
            self._records.append(record)

        return record

    def get_trail(self, plan_id: Optional[str] = None) -> List[StepAuditRecord]:
        """Returns the audit trail, optionally filtered by plan_id."""
        with self._lock:
            if plan_id:
                records = [r for r in self._records if r.plan_id == plan_id]
            else:
                records = list(self._records)
            return copy.deepcopy(records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


class ProgressEventEmitter:
    """
    Real-time progress event dispatcher with listener subscriptions.
    Enables UI components, websockets, and background tasks to observe workflow milestones.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._listeners: List[Callable[[ProgressEvent], None]] = []
        self._event_history: List[ProgressEvent] = []

    def subscribe(self, listener: Callable[[ProgressEvent], None]) -> None:
        """Registers a callback listener for all progress events."""
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[ProgressEvent], None]) -> None:
        """Removes a registered callback listener."""
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def emit(
        self,
        event_type: ProgressEventType,
        plan_id: str,
        message: str,
        step_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> ProgressEvent:
        """Emits a new typed progress event to all active listeners."""
        event = ProgressEvent(
            event_id=f"evt-{uuid4().hex[:8]}",
            event_type=event_type,
            plan_id=plan_id,
            step_id=step_id,
            timestamp=datetime.now(timezone.utc),
            message=message,
            data=dict(data or {}),
        )

        with self._lock:
            self._event_history.append(event)
            listeners_snapshot = list(self._listeners)

        for listener in listeners_snapshot:
            try:
                listener(event)
            except Exception:
                # Listener errors should not interrupt core workflow engine
                pass

        return event

    def get_history(self, plan_id: Optional[str] = None) -> List[ProgressEvent]:
        """Returns event history, optionally filtered by plan_id."""
        with self._lock:
            if plan_id:
                events = [e for e in self._event_history if e.plan_id == plan_id]
            else:
                events = list(self._event_history)
            return copy.deepcopy(events)

    def clear(self) -> None:
        with self._lock:
            self._event_history.clear()
            self._listeners.clear()
