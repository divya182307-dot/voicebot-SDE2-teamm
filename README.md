# Academia AI Voice Co-Pilot — SDE Internship

**Team:** SDE 2  
**Workstream:** W4 — Agentic Workflow Engine (Weeks 1, 2 & 3 / Days 1–21)  
**Contributor:** Karthik N M  
**Email:** karthiknm8050@gmail.com  
**Branch:** `main` & `team/sde-2-voicebot`  
**Project Folder:** `projects/sde-2-voicebot/`  
**Repository:** [https://github.com/KARTHIK-NM/SDE](https://github.com/KARTHIK-NM/SDE)  

---

## 🎯 Executive Summary

This repository delivers the **complete, unified Agentic Workflow Engine** for the **Academia AI Voice Co-Pilot**, combining all deliverables across **Week 1**, **Week 2**, and **Week 3**:

- **Week 1 (Days 1–7):** Typed schemas, 7-state deterministic lifecycle state machine, harmless in-memory mock tools (`knowledge_search`, `course_schedule`), and human-in-the-loop approval gating.
- **Week 2 (Days 8–14):** Plan validator (dependencies & cycle detection via Kahn's algorithm / 3-color DFS), allow-listed tool registry with argument type and permission scope enforcement, approval logic with TTL expiry, safe executor (timeouts, bounded retries strictly for idempotent operations, non-idempotent protection, and cancellation).
- **Week 3 (Days 15–21):** Checkpoint and resume with failed-step recovery (skips completed steps on resume), idempotency keys preventing duplicate tool runs, step-level audit trail with duration and credential masking, real-time typed progress events, reasoning proposal ingestion (`WorkflowProposal`), backend approval state service, and UI integration bridge with duplicate and expired approval protection (**115 automated tests passing**).

---

## 📁 Unified Project Structure

```
.
├── projects/
│   └── sde-2-voicebot/
│       ├── src/
│       │   └── workflow/
│       │       ├── schemas.py              # Single source of truth for workflow models
│       │       ├── state_machine.py        # 7-state lifecycle controller with audit history
│       │       ├── validator.py            # PlanValidator: cycles, deps, tools, scopes
│       │       ├── tools.py                # Allow-listed registry & mock tools
│       │       ├── executor.py             # Safe executor: timeouts, retries, cancellation
│       │       └── README.md               # Detailed workflow architecture guide
│       ├── schemas.py                      # Pydantic schemas interface
│       ├── plan_validator.py               # Dependency & cycle validation engine
│       ├── tool_registry.py                # Strict allow-list & permission scope registry
│       ├── approval_manager.py             # Human-in-the-loop approval & TTL expiry manager
│       ├── safe_executor.py                # Safe executor with timeouts & idempotent retries
│       ├── mock_tools.py                   # Harmless in-memory mock tools
│       ├── demo.py                         # Live interactive Week 2 demonstration
│       ├── demo_week3.py                   # Live interactive Week 3 demonstration (5 Scenarios)
│       ├── requirements.txt                # Project dependencies
│       ├── README.md                       # Voicebot module documentation
│       └── tests/                          # 115 passing unit, policy & integration tests
│           ├── conftest.py
│           ├── test_workflow_schemas_and_sm.py
│           ├── test_invalid_plans_and_transitions.py
│           ├── test_mock_tools_and_executor.py
│           ├── test_week2_policy_and_safe_executor.py
│           ├── test_plan_validator.py
│           ├── test_tool_registry.py
│           ├── test_approval_manager.py
│           ├── test_safe_executor.py
│           ├── test_demo.py
│           ├── test_week3_checkpoint_and_resume.py
│           ├── test_week3_audit_and_events.py
│           ├── test_week3_reasoning_and_ui_integration.py
│           └── test_week3_end_to_end_integration.py
├── requirements.txt                        # Global requirements
├── README.md                               # This documentation
└── .gitignore
```

---

## 🚀 Quickstart & Commands

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Run All Automated Tests (115 Tests Passing)

```bash
cd projects/sde-2-voicebot
python -m pytest tests/ -v
```

### 3. Run Week 3 Live Demonstration (5 Scenarios)

```bash
cd projects/sde-2-voicebot
python demo_week3.py
```

### 4. Run Week 2 Live Demonstration

```bash
cd projects/sde-2-voicebot
python demo.py
```

---

## 🛡️ Key Safety Invariants Enforced

| Safety Invariant | Implementation Mechanism | Test Verification |
| :--- | :--- | :--- |
| **Cycle & Missing Dep Prevention** | `PlanValidator` uses DFS & Kahn's topological sort | `test_validator_rejects_cycles_with_clear_error`, `test_invalid_plan_direct_cycle` |
| **Allow-List Isolation** | `ToolRegistry` rejects unregistered tools and checks argument types | `test_unknown_tool_call_rejected`, `test_validator_rejects_unknown_tool` |
| **Permission Scope Enforcement** | Tools declare required scopes; calls are verified against granted scopes | `test_missing_scope_is_rejected`, `test_validator_enforces_permission_scopes` |
| **HITL Approval with Expiry** | Consequential actions require explicit approval; expired/rejected approvals guarantee 0 execution | `test_approval_rejection_guarantees_no_execution_and_audit_event`, `test_expired_approval_cannot_be_approved` |
| **Timeouts & Bounded Retries** | Wall-clock step limits; retries strictly limited to idempotent calls | `test_slow_tool_times_out`, `test_non_idempotent_tool_not_retried` |
| **Safe Cooperative Cancellation** | `threading.Event` checks halt subsequent steps immediately | `test_cancellation_before_first_step`, `test_cancellation_between_steps` |
