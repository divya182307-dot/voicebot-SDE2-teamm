"""
test_approval_manager.py — D10-11 policy tests for ApprovalManager.
"""
import time
import pytest
from approval_manager import ApprovalManager, ApprovalError
from schemas import ApprovalStatus, ExecutionStatus, RiskLevel


@pytest.fixture()
def manager() -> ApprovalManager:
    return ApprovalManager(default_ttl_seconds=300)


# ──────────────────────────────────────────────────────────────────────────────
# Create
# ──────────────────────────────────────────────────────────────────────────────

def test_create_returns_pending(manager):
    req = manager.create("plan-1", RiskLevel.SENSITIVE, reason="Move files")
    assert req.status == ApprovalStatus.PENDING
    assert req.plan_id == "plan-1"
    assert req.approval_id


def test_create_sets_expiry(manager):
    req = manager.create("plan-1", RiskLevel.HIGH, ttl_seconds=60)
    assert req.expires_at is not None


# ──────────────────────────────────────────────────────────────────────────────
# Approve
# ──────────────────────────────────────────────────────────────────────────────

def test_approve_pending_succeeds(manager):
    req = manager.create("plan-2", RiskLevel.SENSITIVE)
    approved = manager.approve(req.approval_id, decided_by="alice")
    assert approved.status == ApprovalStatus.APPROVED
    assert approved.decided_by == "alice"
    assert approved.decided_at is not None


def test_approve_twice_raises(manager):
    req = manager.create("plan-3", RiskLevel.SENSITIVE)
    manager.approve(req.approval_id)
    with pytest.raises(ApprovalError, match="already in state"):
        manager.approve(req.approval_id)


def test_approve_rejected_raises(manager):
    req = manager.create("plan-4", RiskLevel.SENSITIVE)
    manager.reject(req.approval_id)
    with pytest.raises(ApprovalError, match="already in state"):
        manager.approve(req.approval_id)


# ──────────────────────────────────────────────────────────────────────────────
# Reject
# ──────────────────────────────────────────────────────────────────────────────

def test_reject_pending_succeeds(manager):
    req = manager.create("plan-5", RiskLevel.HIGH)
    rejected = manager.reject(req.approval_id, decided_by="bob")
    assert rejected.status == ApprovalStatus.REJECTED
    assert rejected.decided_by == "bob"


def test_reject_twice_raises(manager):
    req = manager.create("plan-6", RiskLevel.HIGH)
    manager.reject(req.approval_id)
    with pytest.raises(ApprovalError, match="already in state"):
        manager.reject(req.approval_id)


def test_is_approved_returns_false_after_rejection(manager):
    req = manager.create("plan-7", RiskLevel.HIGH)
    manager.reject(req.approval_id)
    assert not manager.is_approved(req.approval_id)


def test_is_approved_returns_true_after_approval(manager):
    req = manager.create("plan-8", RiskLevel.LOW)
    manager.approve(req.approval_id)
    assert manager.is_approved(req.approval_id)


# ──────────────────────────────────────────────────────────────────────────────
# Expiry
# ──────────────────────────────────────────────────────────────────────────────

def test_expired_approval_cannot_be_approved(manager):
    req = manager.create("plan-9", RiskLevel.HIGH, ttl_seconds=0)
    time.sleep(0.05)   # ensure expiry
    with pytest.raises(ApprovalError, match="expired"):
        manager.approve(req.approval_id)


def test_expired_status_auto_detected(manager):
    req = manager.create("plan-10", RiskLevel.HIGH, ttl_seconds=0)
    time.sleep(0.05)
    status = manager.get_status(req.approval_id)
    assert status == ApprovalStatus.EXPIRED


def test_is_approved_returns_false_when_expired(manager):
    req = manager.create("plan-11", RiskLevel.HIGH, ttl_seconds=0)
    time.sleep(0.05)
    assert not manager.is_approved(req.approval_id)


# ──────────────────────────────────────────────────────────────────────────────
# Unknown approval ID
# ──────────────────────────────────────────────────────────────────────────────

def test_unknown_approval_id_raises(manager):
    with pytest.raises(ApprovalError, match="Unknown approval_id"):
        manager.approve("does-not-exist")


# ──────────────────────────────────────────────────────────────────────────────
# Safe audit record — blocked execution
# ──────────────────────────────────────────────────────────────────────────────

def test_safe_audit_record_on_rejection(manager):
    req = manager.create("plan-12", RiskLevel.HIGH)
    manager.reject(req.approval_id)
    record = manager.make_safe_audit_record(req.approval_id, "plan-12")
    assert record.status == ExecutionStatus.CANCELLED
    assert "rejected" in record.audit_note.lower()
    assert record.step_results == []   # no tool was invoked


def test_safe_audit_record_on_expiry(manager):
    req = manager.create("plan-13", RiskLevel.HIGH, ttl_seconds=0)
    time.sleep(0.05)
    record = manager.make_safe_audit_record(req.approval_id, "plan-13")
    assert record.status == ExecutionStatus.CANCELLED
    assert "expired" in record.audit_note.lower()


# ──────────────────────────────────────────────────────────────────────────────
# Audit log
# ──────────────────────────────────────────────────────────────────────────────

def test_audit_log_records_actions(manager):
    req = manager.create("plan-14", RiskLevel.SENSITIVE)
    manager.approve(req.approval_id, decided_by="carol")
    log = manager.audit_log
    assert any("CREATED" in entry for entry in log)
    assert any("APPROVED" in entry for entry in log)

