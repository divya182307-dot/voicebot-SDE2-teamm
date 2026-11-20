"""
safe_executor.py — D12-13
Executes a validated, approved Plan safely:
  • Per-step timeout (threading-based; works on all Python versions).
  • Bounded retries — ONLY for idempotent tools; non-idempotent tools are
    attempted exactly once.
  • Cancellation — caller sets a threading.Event; the executor checks it
    before each step and does not start new steps after it is set.
  • Produces a full ExecutionRecord with per-step StepResult entries.
  • Never executes if the approval is not in APPROVED state.
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from approval_manager import ApprovalManager, ApprovalError
from mock_tools import MOCK_TOOL_FUNCTIONS
from schemas import (
    ApprovalStatus,
    ExecutionRecord,
    ExecutionStatus,
    Plan,
    StepResult,
    ToolDefinition,
)
from tool_registry import ToolRegistry


class ExecutorConfig:
    step_timeout_seconds: float = 10.0    # wall-clock limit per step
    max_retries: int = 3                  # maximum retry attempts for idempotent tools
    retry_delay_seconds: float = 0.2     # back-off between retries


class SafeExecutor:
    """
    Executes a Plan step-by-step with safety guarantees.

    Usage:
        cancel_event = threading.Event()
        record = executor.run(plan, approval_id, cancel_event)
    """

    def __init__(
        self,
        registry: ToolRegistry,
        approval_manager: ApprovalManager,
        config: Optional[ExecutorConfig] = None,
    ) -> None:
        self._registry = registry
        self._approvals = approval_manager
        self._cfg = config or ExecutorConfig()

    # ------------------------------------------------------------------ public

    def run(
        self,
        plan: Plan,
        approval_id: str,
        cancel_event: Optional[threading.Event] = None,
    ) -> ExecutionRecord:
        """
        Execute the plan.  Returns an ExecutionRecord always — even when
        blocked by rejection/expiry/cancellation, the record documents
        what happened without any tool being called.
        """
        execution_id = str(uuid.uuid4())
        cancel_event = cancel_event or threading.Event()

        # ── Guard: approval must be APPROVED ────────────────────────────────
        status = self._approvals.get_status(approval_id)
        if status != ApprovalStatus.APPROVED:
            return self._approvals.make_safe_audit_record(
                approval_id=approval_id,
                plan_id=plan.plan_id,
                execution_id=execution_id,
            )

        # ── Build step order (topological sort, respecting depends_on) ───────
        ordered_step_ids = self._topological_order(plan)

        record = ExecutionRecord(
            execution_id=execution_id,
            plan_id=plan.plan_id,
            approval_id=approval_id,
            status=ExecutionStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )

        step_map = {s.step_id: s for s in plan.steps}
        step_outputs: Dict[str, Any] = {}   # step_id → output (for future chaining)

        for step_id in ordered_step_ids:
            # ── Cancellation check before each step ─────────────────────────
            if cancel_event.is_set():
                record.audit_note = "Cancelled by caller before step '{}'.".format(step_id)
                record.status = ExecutionStatus.CANCELLED
                record.finished_at = datetime.now(timezone.utc)
                return record

            step = step_map[step_id]
            tool_defn = self._registry.get(step.tool_call.tool_name)

            step_result = self._execute_step(
                step_id=step_id,
                tool_defn=tool_defn,
                arguments=step.tool_call.arguments,
                cancel_event=cancel_event,
            )
            record.step_results.append(step_result)

            if step_result.status == ExecutionStatus.CANCELLED:
                record.status = ExecutionStatus.CANCELLED
                record.audit_note = f"Cancelled during step '{step_id}'."
                record.finished_at = datetime.now(timezone.utc)
                return record

            if step_result.status in (ExecutionStatus.FAILED, ExecutionStatus.TIMED_OUT):
                record.status = ExecutionStatus.FAILED
                record.audit_note = (
                    f"Step '{step_id}' ended with status '{step_result.status.value}'; "
                    "execution aborted."
                )
                record.finished_at = datetime.now(timezone.utc)
                return record

            step_outputs[step_id] = step_result.output

        record.status = ExecutionStatus.COMPLETED
        record.finished_at = datetime.now(timezone.utc)
        return record

    # ------------------------------------------------------------------ private

    def _execute_step(
        self,
        step_id: str,
        tool_defn: Optional[ToolDefinition],
        arguments: Dict[str, Any],
        cancel_event: threading.Event,
    ) -> StepResult:
        """Run one tool call with timeout + bounded retries."""
        if tool_defn is None:
            return StepResult(
                step_id=step_id,
                status=ExecutionStatus.FAILED,
                error="Tool definition not found in registry.",
                attempts=0,
            )

        tool_fn = MOCK_TOOL_FUNCTIONS.get(tool_defn.name)
        if tool_fn is None:
            return StepResult(
                step_id=step_id,
                status=ExecutionStatus.FAILED,
                error=f"No mock implementation for tool '{tool_defn.name}'.",
                attempts=0,
            )

        max_attempts = (self._cfg.max_retries + 1) if tool_defn.idempotent else 1
        last_error: Optional[str] = None

        for attempt in range(1, max_attempts + 1):
            # Check cancellation between retries
            if cancel_event.is_set():
                return StepResult(
                    step_id=step_id,
                    status=ExecutionStatus.CANCELLED,
                    error="Cancelled between retries.",
                    attempts=attempt - 1,
                )

            try:
                output = self._run_with_timeout(tool_fn, arguments)
                return StepResult(
                    step_id=step_id,
                    status=ExecutionStatus.COMPLETED,
                    output=output,
                    attempts=attempt,
                )
            except FuturesTimeout:
                return StepResult(
                    step_id=step_id,
                    status=ExecutionStatus.TIMED_OUT,
                    error=(
                        f"Step timed out after {self._cfg.step_timeout_seconds}s "
                        f"(attempt {attempt})."
                    ),
                    attempts=attempt,
                )
            except Exception as exc:
                last_error = str(exc)
                if attempt < max_attempts:
                    time.sleep(self._cfg.retry_delay_seconds)
                # else fall through to failure

        return StepResult(
            step_id=step_id,
            status=ExecutionStatus.FAILED,
            error=f"All {max_attempts} attempt(s) failed. Last error: {last_error}",
            attempts=max_attempts,
        )

    def _run_with_timeout(self, fn: Any, arguments: Dict[str, Any]) -> Any:
        """Execute fn(arguments) in a thread; raise FuturesTimeout if it exceeds the limit."""
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(fn, arguments)
            return future.result(timeout=self._cfg.step_timeout_seconds)

    @staticmethod
    def _topological_order(plan: Plan) -> List[str]:
        """
        Return step IDs in dependency order using Kahn's algorithm.
        Assumes the plan has already been validated (no cycles, no missing deps).
        """
        from collections import defaultdict, deque

        in_degree: Dict[str, int] = {s.step_id: 0 for s in plan.steps}
        graph: Dict[str, List[str]] = defaultdict(list)

        for step in plan.steps:
            for dep in step.depends_on:
                graph[dep].append(step.step_id)
                in_degree[step.step_id] += 1

        queue: deque[str] = deque(sid for sid, deg in in_degree.items() if deg == 0)
        order: List[str] = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbour in graph[node]:
                in_degree[neighbour] -= 1
                if in_degree[neighbour] == 0:
                    queue.append(neighbour)
        return order

