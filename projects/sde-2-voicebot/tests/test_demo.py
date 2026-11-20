"""
test_demo.py — D14 demo: approved vs rejected plan end-to-end.

Run with:   pytest tests/test_demo.py -v -s
"""
import pytest
from approval_manager import ApprovalManager
from plan_validator import PlanValidator
from safe_executor import SafeExecutor, ExecutorConfig
from schemas import ExecutionStatus, PermissionScope, RiskLevel
from tests.conftest import make_plan, simple_step
import mock_tools


SEPARATOR = "=" * 60


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def run_pipeline(plan, approval_decision: str, registry, manager, executor):
    """
    Full pipeline:
      validate plan → validate tools → create approval → decide → execute
    Returns (execution_record, audit_log_entries).
    """
    print(f"\n{SEPARATOR}")
    print(f"PLAN ID : {plan.plan_id}")
    print(f"STEPS   : {[s.step_id for s in plan.steps]}")
    print(f"DECISION: {approval_decision.upper()}")
    print(SEPARATOR)

    # 1. Validate plan structure
    validator = PlanValidator()
    v_result = validator.validate(plan)
    print(f"[1] Plan validation: {'PASS' if v_result.valid else 'FAIL'}")
    if not v_result.valid:
        print(f"    Errors: {v_result.errors}")
        return None, manager.audit_log

    # 2. Validate tool calls
    t_result = registry.validate_plan_tools(plan)
    print(f"[2] Tool validation: {'PASS' if t_result.valid else 'FAIL'}")
    if not t_result.valid:
        print(f"    Errors: {t_result.errors}")
        return None, manager.audit_log

    # 3. Create approval request
    req = manager.create(
        plan_id=plan.plan_id,
        risk_level=RiskLevel.SENSITIVE,
        reason="Demo: file search + summarize",
    )
    print(f"[3] Approval created: {req.approval_id} (status={req.status.value})")

    # 4. User decision
    if approval_decision == "approve":
        manager.approve(req.approval_id, decided_by="demo_user")
        print(f"[4] User APPROVED the plan.")
    else:
        manager.reject(req.approval_id, decided_by="demo_user")
        print(f"[4] User REJECTED the plan.")

    # 5. Execute
    record = executor.run(plan, req.approval_id)
    print(f"[5] Execution status : {record.status.value}")
    print(f"    Audit note       : {record.audit_note or '(none)'}")
    for sr in record.step_results:
        print(f"    Step [{sr.step_id}]: {sr.status.value}  attempts={sr.attempts}")
        if sr.output:
            print(f"    Output: {sr.output}")
        if sr.error:
            print(f"    Error : {sr.error}")

    print(f"\nAudit log tail:")
    for entry in manager.audit_log[-4:]:
        print(f"  {entry}")
    print(SEPARATOR)

    return record, manager.audit_log


# ──────────────────────────────────────────────────────────────────────────────
# Demo tests
# ──────────────────────────────────────────────────────────────────────────────

def test_demo_approved_plan(registry):
    """
    Happy path: plan is validated, approved, and executes successfully.
    All steps complete; outputs are populated.
    """
    manager = ApprovalManager(default_ttl_seconds=300)
    cfg = ExecutorConfig()
    cfg.step_timeout_seconds = 10.0
    cfg.max_retries = 2
    cfg.retry_delay_seconds = 0.05
    executor = SafeExecutor(registry=registry, approval_manager=manager, config=cfg)

    plan = make_plan(
        plan_id="demo-approved-001",
        steps=[
            simple_step("s1", "file_search", {"pattern": "project_report"}),
            simple_step("s2", "file_read", {"path": "mock/documents/project_report_report.txt"}, depends_on=["s1"]),
            simple_step("s3", "summarize", {"text": "Mock file content here."}, depends_on=["s2"]),
        ],
    )

    record, _ = run_pipeline(plan, "approve", registry, manager, executor)

    assert record is not None
    assert record.status == ExecutionStatus.COMPLETED
    assert len(record.step_results) == 3
    for sr in record.step_results:
        assert sr.status == ExecutionStatus.COMPLETED
        assert sr.output is not None


def test_demo_rejected_plan_no_execution(registry):
    """
    Rejection path: plan is validated, but user rejects it.
    No tool is ever invoked; audit record confirms safe no-op.
    """
    tool_calls: list = []
    original = mock_tools.MOCK_TOOL_FUNCTIONS["file_search"]
    mock_tools.MOCK_TOOL_FUNCTIONS["file_search"] = lambda args: (
        tool_calls.append(args) or original(args)
    )

    try:
        manager = ApprovalManager(default_ttl_seconds=300)
        cfg = ExecutorConfig()
        executor = SafeExecutor(registry=registry, approval_manager=manager, config=cfg)

        plan = make_plan(
            plan_id="demo-rejected-001",
            steps=[
                simple_step("s1", "file_search", {"pattern": "confidential"}),
                simple_step("s2", "summarize", {"text": "secret"}, depends_on=["s1"]),
            ],
        )

        record, audit = run_pipeline(plan, "reject", registry, manager, executor)

        assert record is not None
        assert record.status == ExecutionStatus.CANCELLED
        assert record.step_results == []                 # ← no step ran
        assert tool_calls == []                          # ← no tool was called
        assert any("REJECTED" in e for e in audit)

    finally:
        mock_tools.MOCK_TOOL_FUNCTIONS["file_search"] = original


def test_demo_invalid_plan_rejected_before_approval(registry):
    """
    Validation path: plan has a cycle and is rejected at the validation
    stage — no approval request is even created.
    """
    manager = ApprovalManager(default_ttl_seconds=300)
    executor = SafeExecutor(registry=registry, approval_manager=manager)

    # Introduce a cycle: s1 → s2 → s1
    plan = make_plan(
        plan_id="demo-invalid-001",
        steps=[
            simple_step("s1", "file_search", {"pattern": "x"}, depends_on=["s2"]),
            simple_step("s2", "summarize", {"text": "y"}, depends_on=["s1"]),
        ],
    )

    print(f"\n{SEPARATOR}")
    print("DEMO: Invalid plan (cycle) — rejected before approval")
    print(SEPARATOR)

    validator = PlanValidator()
    result = validator.validate(plan)
    print(f"[1] Plan validation: {'PASS' if result.valid else 'FAIL'}")
    print(f"    Errors: {result.errors}")

    assert not result.valid
    assert any("Cycle" in e for e in result.errors)
    assert manager.audit_log == []   # no approval record created for invalid plan

