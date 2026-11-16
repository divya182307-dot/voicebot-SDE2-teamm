"""
Unit tests for Malformed LLM Outputs and Error Handling in Structured Validation.
Covers:
- Truncated and broken JSON syntax.
- Unquoted or single-quoted invalid JSON.
- Non-JSON conversational chatter, apologies, and XML/HTML output.
- Missing mandatory schema attributes in ReasoningResult and custom models.
- Out-of-bounds numeric constraints (confidence score, processing time).
- Invalid Enum literals (RiskLevel, ExecutionStatus).
- Conversational preamble/postamble isolation.
- Multi-attempt self-correction recovery and exhausted retry failure telemetry.
"""

import json
from typing import List, Optional

try:
    import pytest
except ImportError:
    class _PytestCompat:
        class raises:
            def __init__(self, expected_exc):
                self.expected_exc = expected_exc
                self.value = None
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                if exc_type is None:
                    raise AssertionError(f"Expected exception {self.expected_exc.__name__} not raised.")
                if not issubclass(exc_type, self.expected_exc):
                    return False
                self.value = exc_val
                return True
        @staticmethod
        def fixture(fn):
            return fn
    pytest = _PytestCompat()

from pydantic import BaseModel, Field

from app.schemas.common import ExecutionStatus, RiskLevel
from app.schemas.reasoning import ActionStep, ReasoningResult
from app.llm.client_adapter import (
    LLMClientAdapter,
    LLMClientConfig,
    MockDeterministicLLMProvider,
    StructuredOutputParser,
    StructuredOutputValidationException,
)


class StrictTestSchema(BaseModel):
    operation: str = Field(min_length=1, max_length=50)
    score: float = Field(ge=0.0, le=1.0)
    tags: List[str] = Field(default_factory=list)


def noop_sleeper(seconds: float):
    pass


# =========================================================================
# Syntax & Structural Malformation Tests
# =========================================================================

def test_malformed_json_truncated():
    """Verify that truncated/cut-off JSON syntax is detected and rejected."""
    truncated = '{"operation": "analyze_error", "score": 0.95, "tags": ["code", '
    model, err = StructuredOutputParser.parse_and_validate(truncated, StrictTestSchema)
    assert model is None
    assert err is not None
    assert "JSONDecodeError" in err


def test_malformed_json_missing_braces():
    """Verify that missing opening or closing curly braces fail parsing."""
    raw = '"operation": "analyze_error", "score": 0.95'
    model, err = StructuredOutputParser.parse_and_validate(raw, StrictTestSchema)
    assert model is None
    assert err is not None


def test_malformed_json_unquoted_keys():
    """Verify that JavaScript-style unquoted keys fail standard JSON validation."""
    raw = '{operation: "analyze_error", score: 0.95}'
    model, err = StructuredOutputParser.parse_and_validate(raw, StrictTestSchema)
    assert model is None
    assert err is not None
    assert "JSONDecodeError" in err


def test_malformed_non_json_conversational_refusal():
    """Verify that pure conversational text or model refusal is caught."""
    refusal = "I apologize, but I cannot fulfill this request as I am an AI language model."
    model, err = StructuredOutputParser.parse_and_validate(refusal, StrictTestSchema)
    assert model is None
    assert err is not None


def test_malformed_html_xml_payload():
    """Verify that XML/HTML formatted output instead of JSON fails gracefully."""
    xml_output = "<response><operation>search</operation><score>0.9</score></response>"
    model, err = StructuredOutputParser.parse_and_validate(xml_output, StrictTestSchema)
    assert model is None
    assert err is not None


# =========================================================================
# Conversational Preamble Isolation Tests
# =========================================================================

def test_conversational_preamble_and_postamble_isolation():
    """Verify parser extracts JSON embedded within chatty conversational text."""
    chatty = """
    Certainly! I reviewed your code and calculated the confidence scores.
    Here is the structured JSON object:
    ```json
    {
      "operation": "refactor_function",
      "score": 0.92,
      "tags": ["performance", "clean_code"]
    }
    ```
    I hope this helps! Feel free to ask more questions.
    """
    model, err = StructuredOutputParser.parse_and_validate(chatty, StrictTestSchema)
    assert err is None
    assert model is not None
    assert model.operation == "refactor_function"
    assert model.score == 0.92
    assert len(model.tags) == 2


# =========================================================================
# Domain Schema Violation Tests (ReasoningResult)
# =========================================================================

def test_malformed_reasoning_result_missing_mandatory_fields():
    """Verify rejection when ReasoningResult is missing mandatory attributes."""
    # Missing request_id, session_id, response_text, status
    incomplete = {
        "response_id": "resp-incomplete-001",
        "user_intent": "explain_error",
    }
    model, err = StructuredOutputParser.parse_and_validate(json.dumps(incomplete), ReasoningResult)
    assert model is None
    assert err is not None
    assert "request_id" in err or "session_id" in err or "response_text" in err


def test_malformed_reasoning_result_out_of_bounds_confidence():
    """Verify confidence_score > 1.0 or < 0.0 is caught by schema validators."""
    invalid_data = {
        "response_id": "resp-001",
        "request_id": "req-001",
        "session_id": "sess-001",
        "user_intent": "explain_error",
        "response_text": "Error explanation text",
        "reasoning_summary": "Analyzed traceback",
        "tool_call_required": False,
        "risk_level": "category_a_informational",
        "requires_user_approval": False,
        "confidence_score": 1.45,  # Invalid: must be <= 1.0
        "processing_time_ms": 15.0,
        "status": "success",
    }
    model, err = StructuredOutputParser.parse_and_validate(json.dumps(invalid_data), ReasoningResult)
    assert model is None
    assert err is not None
    assert "confidence_score" in err


def test_malformed_reasoning_result_negative_latency():
    """Verify processing_time_ms < 0.0 is rejected."""
    invalid_data = {
        "response_id": "resp-001",
        "request_id": "req-001",
        "session_id": "sess-001",
        "user_intent": "explain_error",
        "response_text": "Valid text",
        "reasoning_summary": "Summary",
        "tool_call_required": False,
        "risk_level": "category_a_informational",
        "requires_user_approval": False,
        "confidence_score": 0.95,
        "processing_time_ms": -100.0,  # Invalid: cannot be negative
        "status": "success",
    }
    model, err = StructuredOutputParser.parse_and_validate(json.dumps(invalid_data), ReasoningResult)
    assert model is None
    assert err is not None
    assert "processing_time_ms" in err


def test_malformed_reasoning_result_invalid_enum_literals():
    """Verify invalid Enum string values for RiskLevel and ExecutionStatus fail."""
    invalid_data = {
        "response_id": "resp-001",
        "request_id": "req-001",
        "session_id": "sess-001",
        "user_intent": "explain_error",
        "response_text": "Valid text",
        "reasoning_summary": "Summary",
        "tool_call_required": False,
        "risk_level": "ultra_hazardous",  # Invalid enum
        "requires_user_approval": False,
        "confidence_score": 0.95,
        "processing_time_ms": 10.0,
        "status": "partially_completed",  # Invalid enum
    }
    model, err = StructuredOutputParser.parse_and_validate(json.dumps(invalid_data), ReasoningResult)
    assert model is None
    assert err is not None
    assert "risk_level" in err or "status" in err


def test_malformed_action_steps_in_action_plan():
    """Verify non-sequential or malformed ActionStep items in action_plan are rejected."""
    invalid_data = {
        "response_id": "resp-001",
        "request_id": "req-001",
        "session_id": "sess-001",
        "user_intent": "delete_files",
        "response_text": "Deleting files",
        "reasoning_summary": "Summary",
        "tool_call_required": True,
        "risk_level": "category_d_high_risk_destructive",
        "requires_user_approval": True,
        "approval_prompt": "Are you sure you want to delete these files?",
        "confidence_score": 0.95,
        "processing_time_ms": 10.0,
        "status": "needs_approval",
        "action_plan": [
            {
                "step_number": 1,
                "tool_name": "delete_file",
                "parameters": {"path": "/tmp/a"},
                "risk_level": "category_d_high_risk_destructive",
                "requires_approval": True,
                "description": "Delete step 1",
            },
            {
                "step_number": 3,  # Invalid: non-sequential jump from 1 to 3
                "tool_name": "delete_file",
                "parameters": {"path": "/tmp/b"},
                "risk_level": "category_d_high_risk_destructive",
                "requires_approval": True,
                "description": "Delete step 3",
            },
        ],
    }
    model, err = StructuredOutputParser.parse_and_validate(json.dumps(invalid_data), ReasoningResult)
    assert model is None
    assert err is not None
    assert "action_plan" in err or "step_number" in err


# =========================================================================
# LLM Adapter Retry & Recovery from Malformed Output
# =========================================================================

def test_llm_adapter_recovers_from_malformed_outputs():
    """
    Verify LLMClientAdapter encounters malformed outputs, triggers self-correction re-prompt,
    and successfully recovers when valid output is provided on subsequent attempt.
    """
    provider = MockDeterministicLLMProvider()
    # Attempt 1: Truncated JSON
    provider.queue_response('{"operation": "test", "score":')
    # Attempt 2: Missing fields
    provider.queue_response('{"operation": "test"}')
    # Attempt 3: Valid conforming JSON
    valid_data = '{"operation": "test", "score": 0.95, "tags": ["recovered"]}'
    provider.queue_response(f"```json\n{valid_data}\n```")

    config = LLMClientConfig(max_retries=3)
    client = LLMClientAdapter(provider=provider, config=config, sleeper=noop_sleeper)

    result = client.generate_structured("Execute task", response_model=StrictTestSchema)
    assert isinstance(result, StrictTestSchema)
    assert result.operation == "test"
    assert result.score == 0.95
    assert result.tags == ["recovered"]
    assert provider.call_count == 3
    assert client.get_metrics()["validation_failures"] == 2
    assert client.get_metrics()["retries_attempted"] == 2


def test_llm_adapter_exhausted_retries_raises_detailed_exception():
    """
    Verify that when all attempts produce malformed outputs,
    StructuredOutputValidationException contains complete error history and raw output.
    """
    provider = MockDeterministicLLMProvider()
    provider.queue_response("I cannot answer in JSON.")
    provider.queue_response("Still not JSON.")

    config = LLMClientConfig(max_retries=1)  # 2 attempts total
    client = LLMClientAdapter(provider=provider, config=config, sleeper=noop_sleeper)

    with pytest.raises(StructuredOutputValidationException) as exc_info:
        client.generate_structured("Execute task", response_model=StrictTestSchema)

    exc = exc_info.value
    assert exc.target_model == "StrictTestSchema"
    assert exc.attempts == 2
    assert "Still not JSON." in exc.raw_output
    assert len(exc.validation_errors) == 2
    assert client.get_metrics()["failed_requests"] == 1

