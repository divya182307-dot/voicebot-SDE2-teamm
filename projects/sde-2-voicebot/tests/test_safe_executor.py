"""
test_safe_executor.py — D12-13 policy tests for SafeExecutor.
"""
import threading
import time
import pytest

from approval_manager import ApprovalManager
from safe_executor import SafeExecutor, ExecutorConfig
from schemas import ExecutionStatus, PermissionScope, RiskLevel
from tests.conftest import make_plan, simple_step
import mock_tools


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def manager() -> ApprovalManager:
    return ApprovalManager(default_ttl_seconds=300)


@pytest.fixture()
def fast_config() -> ExecutorConfig:
    cfg = ExecutorConfig()
    cfg.step_timeout_seconds = 5.0
    cfg.max_retries = 3
    cfg.retry_delay_seconds = 0.05
    return cfg


@pytest.fixture()
def executor(registry, manager, fast_config) -> SafeExecutor:
    return SafeExecutor(registry=registry, approval_manager=manager, config=fast_config)


def _approved(manager: ApprovalManager, plan_id: str) -> str:
    req = manager.create(plan_id, RiskLevel.LOW)
    manager.approve(req.approval_id)
    return req.approval_id


def _rejected(manager: ApprovalManager, plan_id: str) -> str:
    req = manager.create(plan_id, RiskLevel.LOW)
    manager.reject(req.approval_id)
    return req.approval_id


def _expired(manager: ApprovalManager, plan_id: str) -> str:
    req = manager.create(plan_id, RiskLevel.LOW, ttl_seconds=0)
    time.sleep(0.05)
    return req.approval_id


# ──────────────────────────────────────────────────────────────────────────────
# Approved execution
# ──────────────────────────────────────────────────────────────────────────────

def test_approved_plan_completes(executor, manager):
    plan = make_plan([
        simple_step("s1", "file_search", {"pattern": "report"}),
    ])
    aid = _approved(manager, plan.plan_id)
    record = executor.run(plan, aid)
    assert record.status == ExecutionStatus.COMPLETED
    assert len(record.step_results) == 1
    assert record.step_results[0].status == ExecutionStatus.COMPLETED


def test_approved_multi_step_plan_runs_in_order(executor, manager):
    plan = make_plan([
        simple_step("s1", "file_search", {"pattern": "report"}),
        simple_step("s2", "summarize", {"text": "hello world"}, depends_on=["s1"]),
    ])
    aid = _approved(manager, plan.plan_id)
    record = executor.run(plan, aid)
    assert record.status == ExecutionStatus.COMPLETED
    ids = [r.step_id for r in record.step_results]
    assert ids.index("s1") < ids.index("s2")


def test_step_result_output_is_populated(executor, manager):
    plan = make_plan([simple_step("s1", "calculator", {"expression": "2+2"})])
    aid = _approved(manager, plan.plan_id)
    record = executor.run(plan, aid)
    assert record.step_results[0].output["result"] == 4


# ──────────────────────────────────────────────────────────────────────────────
# Blocked execution: rejected / expired — guarantee no tool invoked
# ──────────────────────────────────────────────────────────────────────────────

def test_rejected_approval_blocks_execution(executor, manager):
    plan = make_plan([simple_step("s1", "file_search", {"pattern": "x"})])
    aid = _rejected(manager, plan.plan_id)
    record = executor.run(plan, aid)
    assert record.status == ExecutionStatus.CANCELLED
    assert record.step_results == []         # no tool was invoked
    assert "rejected" in record.audit_note.lower()


def test_expired_approval_blocks_execution(executor, manager):
    plan = make_plan([simple_step("s1", "file_search", {"pattern": "x"})])
    aid = _expired(manager, plan.plan_id)
    record = executor.run(plan, aid)
    assert record.status == ExecutionStatus.CANCELLED
    assert record.step_results == []
    assert "expired" in record.audit_note.lower()


def test_no_tool_side_effects_when_blocked(executor, manager):
    """Verify mock_tools are truly not called when execution is blocked."""
    call_count = {"n": 0}
    original = mock_tools.MOCK_TOOL_FUNCTIONS["file_search"]
    mock_tools.MOCK_TOOL_FUNCTIONS["file_search"] = lambda args: (
        call_count.__setitem__("n", call_count["n"] + 1) or original(args)
    )
    try:
        plan = make_plan([simple_step("s1", "file_search", {"pattern": "x"})])
        aid = _rejected(manager, plan.plan_id)
        executor.run(plan, aid)
        assert call_count["n"] == 0, "Tool was called despite rejection"
    finally:
        mock_tools.MOCK_TOOL_FUNCTIONS["file_search"] = original


# ──────────────────────────────────────────────────────────────────────────────
# Timeout
# ──────────────────────────────────────────────────────────────────────────────

def test_slow_tool_times_out(registry, manager):
    cfg = ExecutorConfig()
    cfg.step_timeout_seconds = 0.2    # very short
    cfg.max_retries = 0
    cfg.retry_delay_seconds = 0.0
    exe = SafeExecutor(registry=registry, approval_manager=manager, config=cfg)

    plan = make_plan([simple_step("s1", "slow_tool", {"delay_seconds": 5.0})])
    aid = _approved(manager, plan.plan_id)
    record = exe.run(plan, aid)
    assert record.status == ExecutionStatus.FAILED
    sr = record.step_results[0]
    assert sr.status == ExecutionStatus.TIMED_OUT


# ──────────────────────────────────────────────────────────────────────────────
# Retries (idempotent only)
# ──────────────────────────────────────────────────────────────────────────────

def test_idempotent_flaky_tool_retried_and_succeeds(registry, manager):
    # Reset counter
    if hasattr(mock_tools.mock_flaky_tool, "_calls"):
        mock_tools.mock_flaky_tool._calls = 0

    cfg = ExecutorConfig()
    cfg.max_retries = 3
    cfg.retry_delay_seconds = 0.01
    cfg.step_timeout_seconds = 5.0
    exe = SafeExecutor(registry=registry, approval_manager=manager, config=cfg)

    plan = make_plan([simple_step("s1", "flaky_tool", {"fail_times": 2})])
    aid = _approved(manager, plan.plan_id)
    record = exe.run(plan, aid)
    assert record.status == ExecutionStatus.COMPLETED
    assert record.step_results[0].attempts >= 3   # failed twice, succeeded on 3rd


def test_non_idempotent_tool_not_retried(registry, manager):
    """slow_tool is non-idempotent; after one failure/timeout it should not retry."""
    cfg = ExecutorConfig()
    cfg.step_timeout_seconds = 0.1
    cfg.max_retries = 5              # would retry 5 times if idempotent
    cfg.retry_delay_seconds = 0.0
    exe = SafeExecutor(registry=registry, approval_manager=manager, config=cfg)

    plan = make_plan([simple_step("s1", "slow_tool", {"delay_seconds": 5.0})])
    aid = _approved(manager, plan.plan_id)
    record = exe.run(plan, aid)
    sr = record.step_results[0]
    assert sr.attempts == 1     # only one attempt because slow_tool is not idempotent


# ──────────────────────────────────────────────────────────────────────────────
# Cancellation
# ──────────────────────────────────────────────────────────────────────────────

def test_cancellation_before_first_step(executor, manager):
    cancel = threading.Event()
    cancel.set()   # cancel before run
    plan = make_plan([simple_step("s1", "file_search", {"pattern": "x"})])
    aid = _approved(manager, plan.plan_id)
    record = executor.run(plan, aid, cancel_event=cancel)
    assert record.status == ExecutionStatus.CANCELLED
    assert record.step_results == []


def test_cancellation_between_steps(registry, manager):
    """Cancel after s1 completes; s2 must not run."""
    cancel = threading.Event()

    cfg = ExecutorConfig()
    cfg.step_timeout_seconds = 5.0
    cfg.max_retries = 0
    cfg.retry_delay_seconds = 0.0
    exe = SafeExecutor(registry=registry, approval_manager=manager, config=cfg)

    original_search = mock_tools.MOCK_TOOL_FUNCTIONS["file_search"]

    def cancelling_search(args):
        result = original_search(args)
        cancel.set()   # simulate cancellation after s1 runs
        return result

    mock_tools.MOCK_TOOL_FUNCTIONS["file_search"] = cancelling_search
    try:
        plan = make_plan([
            simple_step("s1", "file_search", {"pattern": "x"}),
            simple_step("s2", "summarize", {"text": "y"}, depends_on=["s1"]),
        ])
        aid = _approved(manager, plan.plan_id)
        record = exe.run(plan, aid, cancel_event=cancel)
        executed_ids = [r.step_id for r in record.step_results]
        assert "s1" in executed_ids
        assert "s2" not in executed_ids
        assert record.status == ExecutionStatus.CANCELLED
    finally:
        mock_tools.MOCK_TOOL_FUNCTIONS["file_search"] = original_search


# ──────────────────────────────────────────────────────────────────────────────
# Audit record
# ──────────────────────────────────────────────────────────────────────────────

def test_execution_record_has_timestamps(executor, manager):
    plan = make_plan([simple_step("s1", "calculator", {"expression": "3*3"})])
    aid = _approved(manager, plan.plan_id)
    record = executor.run(plan, aid)
    assert record.started_at is not None
    assert record.finished_at is not None
    assert record.finished_at >= record.started_at

