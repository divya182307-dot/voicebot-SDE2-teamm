"""
test_tool_registry.py — D8-9 policy tests for ToolRegistry.
"""
import pytest
from schemas import PermissionScope, ToolCall, ToolDefinition, ToolArgSpec, RiskLevel
from tool_registry import ToolRegistry
from tests.conftest import make_plan, simple_step


# ──────────────────────────────────────────────────────────────────────────────
# Registration
# ──────────────────────────────────────────────────────────────────────────────

def test_register_tool_makes_it_available(registry, file_search_tool):
    assert registry.is_registered("file_search")
    defn = registry.get("file_search")
    assert defn is not None
    assert defn.name == "file_search"


def test_duplicate_registration_raises(registry, file_search_tool):
    with pytest.raises(ValueError, match="already registered"):
        registry.register(file_search_tool)


def test_unknown_tool_is_not_registered(registry):
    assert not registry.is_registered("dangerous_shell_exec")
    assert registry.get("dangerous_shell_exec") is None


# ──────────────────────────────────────────────────────────────────────────────
# Unknown tool call is rejected
# ──────────────────────────────────────────────────────────────────────────────

def test_unknown_tool_call_rejected(registry):
    call = ToolCall(tool_name="not_in_registry", arguments={})
    result = registry.validate_call(call, granted_scopes=[PermissionScope.READ_FILES])
    assert not result.valid
    assert any("not in the allow-list" in e for e in result.errors)


# ──────────────────────────────────────────────────────────────────────────────
# Argument validation
# ──────────────────────────────────────────────────────────────────────────────

def test_valid_call_passes(registry):
    call = ToolCall(tool_name="file_search", arguments={"pattern": "report"})
    result = registry.validate_call(call, [PermissionScope.READ_FILES])
    assert result.valid


def test_missing_required_arg_rejected(registry):
    call = ToolCall(tool_name="file_search", arguments={})  # 'pattern' is required
    result = registry.validate_call(call, [PermissionScope.READ_FILES])
    assert not result.valid
    assert any("pattern" in e for e in result.errors)


def test_wrong_arg_type_rejected(registry):
    call = ToolCall(tool_name="file_search", arguments={"pattern": 123})  # must be str
    result = registry.validate_call(call, [PermissionScope.READ_FILES])
    assert not result.valid
    assert any("pattern" in e and "str" in e for e in result.errors)


def test_undeclared_arg_rejected(registry):
    call = ToolCall(
        tool_name="file_search",
        arguments={"pattern": "x", "secret_flag": True},  # 'secret_flag' not declared
    )
    result = registry.validate_call(call, [PermissionScope.READ_FILES])
    assert not result.valid
    assert any("secret_flag" in e for e in result.errors)


# ──────────────────────────────────────────────────────────────────────────────
# Permission scope enforcement
# ──────────────────────────────────────────────────────────────────────────────

def test_missing_scope_is_rejected(registry):
    call = ToolCall(tool_name="file_search", arguments={"pattern": "x"})
    # file_search requires READ_FILES but we grant nothing
    result = registry.validate_call(call, granted_scopes=[])
    assert not result.valid
    assert any("read_files" in e for e in result.errors)


def test_correct_scope_passes(registry):
    call = ToolCall(tool_name="file_search", arguments={"pattern": "x"})
    result = registry.validate_call(call, [PermissionScope.READ_FILES])
    assert result.valid


def test_extra_scopes_do_not_cause_failure(registry):
    call = ToolCall(tool_name="file_search", arguments={"pattern": "x"})
    result = registry.validate_call(
        call,
        [PermissionScope.READ_FILES, PermissionScope.COMPUTE, PermissionScope.SEARCH],
    )
    assert result.valid


# ──────────────────────────────────────────────────────────────────────────────
# Validate all steps in a plan
# ──────────────────────────────────────────────────────────────────────────────

def test_validate_plan_tools_all_valid(registry):
    plan = make_plan([
        simple_step("s1", "file_search", {"pattern": "report"}),
        simple_step("s2", "summarize", {"text": "hello"}),
    ])
    result = registry.validate_plan_tools(plan)
    assert result.valid


def test_validate_plan_tools_unknown_tool_reported(registry):
    plan = make_plan([
        simple_step("s1", "file_search", {"pattern": "x"}),
        simple_step("s2", "shadow_exec", {}),   # not in registry
    ])
    result = registry.validate_plan_tools(plan)
    assert not result.valid
    assert any("shadow_exec" in e for e in result.errors)

