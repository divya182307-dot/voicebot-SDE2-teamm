"""
Checkpoint & Resume Engine with Failed-Step Recovery for Academiaai Voicebot.
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M

Days 15-16 Deliverable:
Features:
1. Snapshot execution state at step boundaries into immutable WorkflowCheckpoint models.
2. Resume workflows from checkpoints without re-running already completed steps.
3. Failed-step recovery: pinpoint failed steps, apply corrective adjustments, and resume seamlessly.
4. Preserves and restores idempotency caches across execution boundaries.
"""

from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from src.workflow.schemas import (
    StepCheckpoint,
    StepStatus,
    WorkflowCheckpoint,
    WorkflowPlan,
    WorkflowState,
    WorkflowStep,
)


class CheckpointStore:
    """
    Thread-safe repository for workflow execution checkpoints.
    Supports in-memory persistence with fast retrieval by checkpoint ID or plan ID.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._checkpoints: Dict[str, WorkflowCheckpoint] = {}
        self._latest_by_plan: Dict[str, str] = {}

    def save(self, checkpoint: WorkflowCheckpoint) -> str:
        """Stores a checkpoint and updates the latest pointer for the plan."""
        with self._lock:
            self._checkpoints[checkpoint.checkpoint_id] = copy.deepcopy(checkpoint)
            self._latest_by_plan[checkpoint.plan_id] = checkpoint.checkpoint_id
            return checkpoint.checkpoint_id

    def get(self, checkpoint_id: str) -> Optional[WorkflowCheckpoint]:
        """Retrieves a checkpoint by its unique ID."""
        with self._lock:
            cp = self._checkpoints.get(checkpoint_id)
            return copy.deepcopy(cp) if cp else None

    def get_latest(self, plan_id: str) -> Optional[WorkflowCheckpoint]:
        """Retrieves the most recent checkpoint for a given plan."""
        with self._lock:
            cp_id = self._latest_by_plan.get(plan_id)
            if not cp_id:
                return None
            return self.get(cp_id)

    def list_checkpoints(self, plan_id: Optional[str] = None) -> List[WorkflowCheckpoint]:
        """Lists all checkpoints, optionally filtered by plan ID."""
        with self._lock:
            cps = list(self._checkpoints.values())
            if plan_id:
                cps = [c for c in cps if c.plan_id == plan_id]
            cps.sort(key=lambda c: c.created_at)
            return copy.deepcopy(cps)

    def clear(self) -> None:
        with self._lock:
            self._checkpoints.clear()
            self._latest_by_plan.clear()


class CheckpointManager:
    """
    High-level checkpoint controller for capturing and restoring workflow execution states.
    """

    def __init__(self, store: Optional[CheckpointStore] = None) -> None:
        self.store = store or CheckpointStore()

    def capture_checkpoint(
        self,
        plan: WorkflowPlan,
        workflow_state: WorkflowState,
        step_results: Dict[str, Any],
        idempotency_cache: Dict[str, Any],
        failed_step_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WorkflowCheckpoint:
        """
        Creates and stores a snapshot of the current workflow state.
        """
        completed_step_ids = [
            s.step_id for s in plan.steps if s.status == StepStatus.SUCCEEDED
        ]

        step_checkpoints: Dict[str, StepCheckpoint] = {}
        for s in plan.steps:
            step_checkpoints[s.step_id] = StepCheckpoint(
                step_id=s.step_id,
                tool_name=s.tool_name,
                status=s.status,
                result=s.result,
                error_message=s.error_message,
                idempotency_key=s.idempotency_key,
                completed_at=datetime.now(timezone.utc) if s.status == StepStatus.SUCCEEDED else None,
            )

        checkpoint = WorkflowCheckpoint(
            checkpoint_id=f"cp-{uuid4().hex[:10]}",
            plan_id=plan.plan_id,
            session_id=plan.session_id,
            correlation_id=plan.correlation_id,
            workflow_state=workflow_state,
            completed_step_ids=completed_step_ids,
            failed_step_id=failed_step_id,
            step_results=dict(step_results),
            step_checkpoints=step_checkpoints,
            idempotency_cache=dict(idempotency_cache),
            created_at=datetime.now(timezone.utc),
            metadata=dict(metadata or {}),
        )

        self.store.save(checkpoint)
        return checkpoint

    def apply_checkpoint_to_plan(
        self,
        checkpoint: WorkflowCheckpoint,
        plan: WorkflowPlan,
    ) -> None:
        """
        Restores plan step statuses and results from a checkpoint.
        Guarantees already completed steps retain their outputs and status.
        """
        step_map = {s.step_id: s for s in plan.steps}

        for step_id, step_cp in checkpoint.step_checkpoints.items():
            if step_id in step_map:
                step = step_map[step_id]
                step.status = step_cp.status
                step.result = step_cp.result
                step.error_message = step_cp.error_message
                step.idempotency_key = step_cp.idempotency_key

        plan.state = checkpoint.workflow_state

    def prepare_failed_step_recovery(
        self,
        plan: WorkflowPlan,
        step_id: str,
        updated_arguments: Optional[Dict[str, Any]] = None,
    ) -> WorkflowStep:
        """
        Prepares a previously failed step for re-execution without altering
        any previously completed steps.
        """
        target_step: Optional[WorkflowStep] = None
        for step in plan.steps:
            if step.step_id == step_id:
                target_step = step
                break

        if not target_step:
            raise KeyError(f"Step '{step_id}' not found in plan '{plan.plan_id}'")

        if target_step.status not in (StepStatus.FAILED, StepStatus.CANCELLED):
            raise ValueError(
                f"Cannot recover step '{step_id}' with status '{target_step.status.value}'. "
                "Only FAILED or CANCELLED steps can be recovered."
            )

        # Reset target step to PENDING
        target_step.status = StepStatus.PENDING
        target_step.error_message = None
        if updated_arguments is not None:
            target_step.arguments = dict(updated_arguments)

        # If downstream steps were cancelled due to this failure, reset them too
        for step in plan.steps:
            if step.status == StepStatus.CANCELLED and step_id in step.depends_on:
                step.status = StepStatus.PENDING
                step.error_message = None

        plan.state = WorkflowState.RUNNING
        return target_step

