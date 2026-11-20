"""
conftest.py — shared pytest fixtures for the whole test suite.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from schemas import (
    PermissionScope,
    Plan,
    PlanStep,
    RiskLevel,
    ToolArgSpec,
    ToolCall,
    ToolDefinition,
)
from tool_registry import ToolRegistry
from approval_manager import ApprovalManager


# ──────────────────────────────────────────────────────────────────────────────
# Shared tool definitions
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def file_search_tool() -> ToolDefinition:
    return ToolDefinition(
        name="file_search",
        description="Search for files by pattern.",
        risk_level=RiskLevel.LOW,
        required_scopes=[PermissionScope.READ_FILES],
        args=[ToolArgSpec(name="pattern", type="str", required=True)],
        idempotent=True,
    )


@pytest.fixture()
def file_read_tool() -> ToolDefinition:
    return ToolDefinition(
        name="file_read",
        description="Read a file and return its content.",
        risk_level=RiskLevel.LOW,
        required_scopes=[PermissionScope.READ_FILES],
        args=[ToolArgSpec(name="path", type="str", required=True)],
        idempotent=True,
    )


@pytest.fixture()
def summarize_tool() -> ToolDefinition:
    return ToolDefinition(
        name="summarize",
        description="Summarize a piece of text.",
        risk_level=RiskLevel.INFORMATIONAL,
        required_scopes=[PermissionScope.COMPUTE],
        args=[ToolArgSpec(name="text", type="str", required=True)],
        idempotent=True,
    )


@pytest.fixture()
def web_search_tool() -> ToolDefinition:
    return ToolDefinition(
        name="web_search",
        description="Search the web (mock).",
        risk_level=RiskLevel.LOW,
        required_scopes=[PermissionScope.SEARCH],
        args=[ToolArgSpec(name="query", type="str", required=True)],
        idempotent=True,
    )


@pytest.fixture()
def calculator_tool() -> ToolDefinition:
    return ToolDefinition(
        name="calculator",
        description="Evaluate a simple arithmetic expression.",
        risk_level=RiskLevel.INFORMATIONAL,
        required_scopes=[PermissionScope.COMPUTE],
        args=[ToolArgSpec(name="expression", type="str", required=True)],
        idempotent=True,
    )


@pytest.fixture()
def slow_tool() -> ToolDefinition:
    return ToolDefinition(
        name="slow_tool",
        description="Intentionally slow — used to test timeouts.",
        risk_level=RiskLevel.LOW,
        required_scopes=[PermissionScope.COMPUTE],
        args=[ToolArgSpec(name="delay_seconds", type="float", required=False)],
        idempotent=False,
    )


@pytest.fixture()
def flaky_tool() -> ToolDefinition:
    return ToolDefinition(
        name="flaky_tool",
        description="Fails the first N times — used to test retries.",
        risk_level=RiskLevel.LOW,
        required_scopes=[PermissionScope.COMPUTE],
        args=[ToolArgSpec(name="fail_times", type="int", required=False)],
        idempotent=True,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Pre-built registry with all mock tools registered
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def registry(
    file_search_tool,
    file_read_tool,
    summarize_tool,
    web_search_tool,
    calculator_tool,
    slow_tool,
    flaky_tool,
) -> ToolRegistry:
    reg = ToolRegistry()
    for t in [file_search_tool, file_read_tool, summarize_tool,
              web_search_tool, calculator_tool, slow_tool, flaky_tool]:
        reg.register(t)
    return reg


@pytest.fixture()
def approval_manager() -> ApprovalManager:
    return ApprovalManager(default_ttl_seconds=300)


# ──────────────────────────────────────────────────────────────────────────────
# Helper factories
# ──────────────────────────────────────────────────────────────────────────────

def make_plan(
    steps,
    plan_id="plan-001",
    session_id="sess-001",
    granted_scopes=None,
) -> Plan:
    if granted_scopes is None:
        granted_scopes = [
            PermissionScope.READ_FILES,
            PermissionScope.COMPUTE,
            PermissionScope.SEARCH,
        ]
    return Plan(
        plan_id=plan_id,
        session_id=session_id,
        steps=steps,
        granted_scopes=granted_scopes,
    )


def simple_step(step_id, tool_name, args=None, depends_on=None) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        tool_call=ToolCall(tool_name=tool_name, arguments=args or {}),
        depends_on=depends_on or [],
    )

