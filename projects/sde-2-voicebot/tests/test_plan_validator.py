"""
test_plan_validator.py — D8-9 policy tests for PlanValidator.
"""
import pytest
from plan_validator import PlanValidator
from tests.conftest import make_plan, simple_step


@pytest.fixture()
def validator() -> PlanValidator:
    return PlanValidator()


# ──────────────────────────────────────────────────────────────────────────────
# Valid plans
# ──────────────────────────────────────────────────────────────────────────────

def test_single_step_plan_is_valid(validator):
    plan = make_plan([simple_step("s1", "file_search", {"pattern": "report"})])
    result = validator.validate(plan)
    assert result.valid
    assert result.errors == []


def test_linear_dependency_chain_is_valid(validator):
    # s1 → s2 → s3
    steps = [
        simple_step("s1", "file_search", {"pattern": "report"}),
        simple_step("s2", "file_read", {"path": "/mock/f.txt"}, depends_on=["s1"]),
        simple_step("s3", "summarize", {"text": "hello"}, depends_on=["s2"]),
    ]
    result = validator.validate(make_plan(steps))
    assert result.valid


def test_diamond_dependency_is_valid(validator):
    # s1 → s2, s1 → s3, s2 + s3 → s4
    steps = [
        simple_step("s1", "file_search", {"pattern": "x"}),
        simple_step("s2", "file_read", {"path": "a"}, depends_on=["s1"]),
        simple_step("s3", "summarize", {"text": "b"}, depends_on=["s1"]),
        simple_step("s4", "calculator", {"expression": "1+1"}, depends_on=["s2", "s3"]),
    ]
    result = validator.validate(make_plan(steps))
    assert result.valid


def test_empty_plan_is_valid(validator):
    result = validator.validate(make_plan([]))
    assert result.valid


# ──────────────────────────────────────────────────────────────────────────────
# Cycle detection
# ──────────────────────────────────────────────────────────────────────────────

def test_self_loop_is_rejected(validator):
    steps = [simple_step("s1", "file_search", {"pattern": "x"}, depends_on=["s1"])]
    result = validator.validate(make_plan(steps))
    assert not result.valid
    assert any("Cycle" in e for e in result.errors)


def test_two_step_cycle_is_rejected(validator):
    steps = [
        simple_step("s1", "file_search", {"pattern": "x"}, depends_on=["s2"]),
        simple_step("s2", "summarize", {"text": "y"}, depends_on=["s1"]),
    ]
    result = validator.validate(make_plan(steps))
    assert not result.valid
    assert any("Cycle" in e for e in result.errors)


def test_three_step_cycle_is_rejected(validator):
    steps = [
        simple_step("s1", "file_search", {"pattern": "x"}, depends_on=["s3"]),
        simple_step("s2", "summarize", {"text": "y"}, depends_on=["s1"]),
        simple_step("s3", "calculator", {"expression": "1"}, depends_on=["s2"]),
    ]
    result = validator.validate(make_plan(steps))
    assert not result.valid
    assert any("Cycle" in e for e in result.errors)


# ──────────────────────────────────────────────────────────────────────────────
# Missing dependencies
# ──────────────────────────────────────────────────────────────────────────────

def test_missing_dependency_is_rejected(validator):
    steps = [
        simple_step("s1", "file_read", {"path": "/f"}, depends_on=["nonexistent"])
    ]
    result = validator.validate(make_plan(steps))
    assert not result.valid
    assert any("nonexistent" in e for e in result.errors)


def test_multiple_missing_dependencies_all_reported(validator):
    steps = [
        simple_step("s1", "file_search", {"pattern": "x"}, depends_on=["ghost1", "ghost2"])
    ]
    result = validator.validate(make_plan(steps))
    assert not result.valid
    assert any("ghost1" in e for e in result.errors)
    assert any("ghost2" in e for e in result.errors)


# ──────────────────────────────────────────────────────────────────────────────
# Duplicate step IDs
# ──────────────────────────────────────────────────────────────────────────────

def test_duplicate_step_id_is_rejected(validator):
    steps = [
        simple_step("s1", "file_search", {"pattern": "x"}),
        simple_step("s1", "summarize", {"text": "y"}),
    ]
    result = validator.validate(make_plan(steps))
    assert not result.valid
    assert any("Duplicate" in e and "s1" in e for e in result.errors)


# ──────────────────────────────────────────────────────────────────────────────
# Error messages are descriptive
# ──────────────────────────────────────────────────────────────────────────────

def test_error_messages_are_non_empty(validator):
    steps = [simple_step("s1", "file_search", {"pattern": "x"}, depends_on=["missing"])]
    result = validator.validate(make_plan(steps))
    assert not result.valid
    for err in result.errors:
        assert len(err.strip()) > 0

