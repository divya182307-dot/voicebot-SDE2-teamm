"""
Workflow State Machine for Academiaai AI Voicebot.
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M

Day 1-2 Deliverable:
State machine governing the lifecycle transitions of a WorkflowPlan
according to PRD Section 8 and Section 18.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from pydantic import BaseModel, Field

from src.workflow.schemas import WorkflowPlan, WorkflowState


class InvalidStateTransitionError(Exception):
    """Raised when an illegal workflow state transition is attempted."""
    def __init__(self, from_state: WorkflowState, to_state: WorkflowState, reason: Optional[str] = None):
        msg = f"Cannot transition workflow from '{from_state.value}' to '{to_state.value}'"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)
        self.from_state = from_state
        self.to_state = to_state
        self.reason = reason


class StateTransitionEvent(BaseModel):
    """Audit record for a state transition."""
    from_state: WorkflowState
    to_state: WorkflowState
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reason: Optional[str] = None


class WorkflowStateMachine:
    """
    Finite State Machine managing transitions for a WorkflowPlan.

    Allowed transitions:
      - DRAFT -> AWAITING_APPROVAL, RUNNING, CANCELLED
      - AWAITING_APPROVAL -> RUNNING, CANCELLED, FAILED
      - RUNNING -> PAUSED, AWAITING_APPROVAL, SUCCEEDED, FAILED, CANCELLED
      - PAUSED -> RUNNING, CANCELLED
      - Terminal states: SUCCEEDED, FAILED, CANCELLED (no outgoing transitions)
    """

    ALLOWED_TRANSITIONS: Dict[WorkflowState, Set[WorkflowState]] = {
        WorkflowState.DRAFT: {
            WorkflowState.AWAITING_APPROVAL,
            WorkflowState.RUNNING,
            WorkflowState.CANCELLED,
        },
        WorkflowState.AWAITING_APPROVAL: {
            WorkflowState.RUNNING,
            WorkflowState.CANCELLED,
            WorkflowState.FAILED,
        },
        WorkflowState.RUNNING: {
            WorkflowState.PAUSED,
            WorkflowState.AWAITING_APPROVAL,
            WorkflowState.SUCCEEDED,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        },
        WorkflowState.PAUSED: {
            WorkflowState.RUNNING,
            WorkflowState.CANCELLED,
        },
        # Terminal states
        WorkflowState.SUCCEEDED: set(),
        WorkflowState.FAILED: set(),
        WorkflowState.CANCELLED: set(),
    }

    def __init__(self, plan: WorkflowPlan):
        self.plan = plan
        self.history: List[StateTransitionEvent] = []

    @property
    def current_state(self) -> WorkflowState:
        return self.plan.state

    def is_terminal(self) -> bool:
        """Checks if current state is terminal (no further transitions allowed)."""
        return len(self.ALLOWED_TRANSITIONS.get(self.current_state, set())) == 0

    def can_transition(self, target_state: WorkflowState) -> bool:
        """Determines if a transition to target_state is valid from current state."""
        allowed = self.ALLOWED_TRANSITIONS.get(self.current_state, set())
        return target_state in allowed

    def transition(self, target_state: WorkflowState, reason: Optional[str] = None) -> WorkflowPlan:
        """
        Transitions the workflow to target_state.
        Updates plan.state and plan.updated_at, and logs the event to audit history.
        Raises InvalidStateTransitionError if transition is not permitted.
        """
        if not self.can_transition(target_state):
            raise InvalidStateTransitionError(
                from_state=self.current_state,
                to_state=target_state,
                reason=reason or f"Transition not allowed by state machine rules"
            )

        event = StateTransitionEvent(
            from_state=self.current_state,
            to_state=target_state,
            reason=reason,
        )
        self.history.append(event)

        # Update the plan
        self.plan.state = target_state
        self.plan.updated_at = event.timestamp
        return self.plan

    def check_initial_readiness(self) -> WorkflowState:
        """
        Evaluates a DRAFT plan: if any step requires approval, transitions to AWAITING_APPROVAL.
        Otherwise, transitions directly to RUNNING.
        """
        if self.current_state != WorkflowState.DRAFT:
            raise InvalidStateTransitionError(
                from_state=self.current_state,
                to_state=WorkflowState.RUNNING,
                reason="Initial readiness check can only be run on DRAFT plans"
            )

        needs_approval = any(step.requires_approval for step in self.plan.steps)
        target = WorkflowState.AWAITING_APPROVAL if needs_approval else WorkflowState.RUNNING
        reason = "Plan requires approval for consequential steps" if needs_approval else "All steps approved/informational; ready to execute"
        return self.transition(target, reason=reason).state
