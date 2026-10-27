# Workstream W4: Agentic Workflow — Days 1–2 Deliverables

**Author:** Karthik N M  
**Team:** SDE 2 (`projects/sde-2-voicebot/`)  
**Scope:** Days 1–2 of Week 1 Foundation & First Vertical Slice

---

## 1. Deliverable Summary

This module establishes the typed contracts and lifecycle state machine for the agentic execution engine:

* **[schemas.py](file:///c:/SDE%20intern/projects/sde-2-voicebot/src/workflow/schemas.py)**
  * `ToolSpec`: Schema definition for allow-listed tools (name, purpose, input/output schemas, permission requirements, risk classification, failure behavior).
  * `WorkflowStep`: Individual execution step with dependency tracking (`depends_on`), input arguments, risk level, and automatic enforcement of human approval for sensitive/destructive operations.
  * `WorkflowPlan`: Complete multi-step plan containing ordered steps, uniqueness validation for step IDs, cycle/dependency checks, and metadata.
  * `ApprovalRequest`: Human-in-the-loop audit object tracking pending, approved, rejected, and expired permissions for consequential actions.
  * `WorkflowResult`: Execution outcome report with step results, timing, terminal state, and redacted error diagnostics.
  * `WorkflowState`: Enum per PRD Section 8 (`draft`, `awaiting_approval`, `running`, `paused`, `succeeded`, `failed`, `cancelled`).
  * `RiskLevel`: Classification per PRD Section 18 (`informational`, `low_risk`, `sensitive`, `destructive`).

* **[state_machine.py](file:///c:/SDE%20intern/projects/sde-2-voicebot/src/workflow/state_machine.py)**
  * `WorkflowStateMachine`: Finite state machine enforcing valid state transitions.
  * `InvalidStateTransitionError`: Raised whenever an illegal transition is attempted.
  * `StateTransitionEvent`: Audit trail logging every transition with timestamps and reasons.
  * `check_initial_readiness`: Determines whether a draft plan can execute directly or must wait for user approval.

---

## 2. Test Verification

Run tests using pytest:
```bash
cd projects/sde-2-voicebot
$env:PYTHONPATH="."
python -m pytest tests -v
```

All 12 unit tests validate:
- Schema validation & invalid payload rejection.
- Consequential steps defaulting to `requires_approval = True`.
- Duplicate step IDs and invalid dependencies rejection.
- Happy-path and approval/rejection lifecycle transitions.
- Illegal transition protection.
