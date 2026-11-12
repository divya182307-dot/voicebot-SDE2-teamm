"""
mock_tools.py — Harmless mock tool implementations.
Rules:
  • No external network calls.
  • No real file system writes.
  • No OS / shell commands.
  • Return deterministic fake data so tests are stable.
"""
from __future__ import annotations

import time
from typing import Any, Dict

# ──────────────────────────────────────────────────────────────────────────────
# Tool function type alias
# ──────────────────────────────────────────────────────────────────────────────
ToolFn = "Callable[[Dict[str, Any]], Any]"


def mock_file_search(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Simulate searching for files by name pattern.  Read-only, no I/O."""
    pattern = arguments.get("pattern", "*")
    return {
        "matches": [
            f"mock/documents/{pattern}_report.txt",
            f"mock/documents/{pattern}_notes.md",
        ],
        "count": 2,
    }


def mock_file_read(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Simulate reading a file. Returns fake content, no real disk access."""
    path = arguments.get("path", "unknown")
    return {
        "path": path,
        "content": f"[MOCK CONTENT of {path}]\nLine 1\nLine 2\nLine 3",
        "size_bytes": 42,
    }


def mock_web_search(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Simulate a web search. No network access."""
    query = arguments.get("query", "")
    return {
        "query": query,
        "results": [
            {"title": f"Mock result 1 for '{query}'", "url": "https://mock.example/1"},
            {"title": f"Mock result 2 for '{query}'", "url": "https://mock.example/2"},
        ],
    }


def mock_summarize(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Simulate a text-summarisation tool.  Pure compute, no I/O."""
    text = arguments.get("text", "")
    word_count = len(text.split())
    return {
        "summary": f"[MOCK SUMMARY: {word_count} words condensed to one sentence.]",
        "original_word_count": word_count,
    }


def mock_calculator(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate a simple arithmetic expression string safely."""
    expression = str(arguments.get("expression", "0"))
    # Only allow digits, spaces and basic operators — NO eval on user strings.
    allowed = set("0123456789 +-*/().")
    if not all(c in allowed for c in expression):
        return {"error": "Expression contains disallowed characters."}
    try:
        result = eval(expression, {"__builtins__": {}})  # noqa: S307 – guarded above
        return {"expression": expression, "result": result}
    except Exception as exc:
        return {"error": str(exc)}


def mock_slow_tool(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Intentionally slow tool used to test timeout enforcement."""
    delay = float(arguments.get("delay_seconds", 5.0))
    time.sleep(delay)
    return {"slept_for": delay}


def mock_flaky_tool(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fails on the first N calls, then succeeds.
    Uses a mutable default to track call count across invocations.
    Idempotent — safe to retry.
    """
    if not hasattr(mock_flaky_tool, "_calls"):
        mock_flaky_tool._calls = 0  # type: ignore[attr-defined]
    mock_flaky_tool._calls += 1  # type: ignore[attr-defined]
    fail_times = int(arguments.get("fail_times", 1))
    if mock_flaky_tool._calls <= fail_times:  # type: ignore[attr-defined]
        raise RuntimeError(
            f"Transient failure #{mock_flaky_tool._calls} (simulated)"  # type: ignore[attr-defined]
        )
    count = mock_flaky_tool._calls  # type: ignore[attr-defined]
    mock_flaky_tool._calls = 0      # reset for next test run
    return {"succeeded_on_attempt": count}


# ──────────────────────────────────────────────────────────────────────────────
# Dispatch table — maps tool name → function
# ──────────────────────────────────────────────────────────────────────────────
MOCK_TOOL_FUNCTIONS: Dict[str, Any] = {
    "file_search": mock_file_search,
    "file_read": mock_file_read,
    "web_search": mock_web_search,
    "summarize": mock_summarize,
    "calculator": mock_calculator,
    "slow_tool": mock_slow_tool,
    "flaky_tool": mock_flaky_tool,
}

