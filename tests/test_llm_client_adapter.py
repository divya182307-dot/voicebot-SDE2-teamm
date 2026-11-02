"""
Unit tests for LLM Client Adapter with Timeout, Retry, and Structured-Output Validation.
Compatible with pytest and standard standalone runners.
"""

import json
import time
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
from app.schemas.reasoning import ReasoningResult
from app.llm.client_adapter import (
    BaseLLMProvider,
    LLMAuthenticationException,
    LLMClientAdapter,
    LLMClientConfig,
    LLMTimeoutException,
    LLMTransientException,
    MockDeterministicLLMProvider,
    StructuredOutputParser,
    StructuredOutputValidationException,
)


class MockSlowProvider(BaseLLMProvider):
    """Simulates latency to trigger timeout enforcement."""
    def __init__(self, delay_seconds: float = 2.0, response: str = "Delayed response"):
        self.delay = delay_seconds
        self.response = response

    def generate(self, prompt: str, system_instruction: Optional[str] = None, timeout: Optional[float] = None) -> str:
        time.sleep(self.delay)
        return self.response


class SampleTargetSchema(BaseModel):
    intent: str
    confidence: float = Field(ge=0.0, le=1.0)
    items: List[str] = Field(default_factory=list)


# No-op sleeper for high-speed deterministic test execution
def fast_sleeper(seconds: float):
    pass


# =========================================================================
# Structured Output Parser Tests
# =========================================================================

def test_structured_output_parser_clean_json():
    """Verify parsing and validation of clean JSON strings."""
    raw = '{"intent": "search_code", "confidence": 0.98, "items": ["file1.py"]}'
    model, err = StructuredOutputParser.parse_and_validate(raw, SampleTargetSchema)
    assert err is None
    assert model is not None
    assert model.intent == "search_code"
    assert model.confidence == 0.98
    assert model.items == ["file1.py"]


def test_structured_output_parser_markdown_code_fences():
    """Verify extraction of JSON wrapped in markdown fences."""
    raw = """
    Here is the structured reasoning result:
    ```json
    {
      "intent": "analyze_error",
      "confidence": 0.95,
      "items": ["main.py", "traceback.log"]
    }
    ```
    Please confirm before proceeding.
    """
    model, err = StructuredOutputParser.parse_and_validate(raw, SampleTargetSchema)
    assert err is None
    assert model is not None
    assert model.intent == "analyze_error"
    assert model.confidence == 0.95


def test_structured_output_parser_invalid_schema():
    """Verify validation error detection when fields violate schema constraints."""
    raw = '{"intent": "test", "confidence": 1.5}'  # confidence > 1.0 violates constraint
    model, err = StructuredOutputParser.parse_and_validate(raw, SampleTargetSchema)
    assert model is None
    assert err is not None
    assert "confidence" in err


# =========================================================================
# LLM Client Adapter: Generation & Timeout Tests
# =========================================================================

def test_successful_text_generation():
    """Verify standard text generation."""
    provider = MockDeterministicLLMProvider(default_response="Deterministic assistant output")
    client = LLMClientAdapter(provider=provider, sleeper=fast_sleeper)

    res = client.generate("Hello world")
    assert res == "Deterministic assistant output"
    assert client.get_metrics()["successful_requests"] == 1


def test_timeout_raises_llm_timeout_exception():
    """Verify requests exceeding timeout threshold raise LLMTimeoutException."""
    slow_provider = MockSlowProvider(delay_seconds=0.5)
    config = LLMClientConfig(timeout_seconds=0.1, max_retries=0)
    client = LLMClientAdapter(provider=slow_provider, config=config, sleeper=fast_sleeper)

    with pytest.raises(LLMTimeoutException) as exc_info:
        client.generate("Trigger timeout")
    assert "timed out after 0.10 seconds" in str(exc_info.value)
    assert client.get_metrics()["timeouts_encountered"] == 1


# =========================================================================
# Retry & Backoff Tests
# =========================================================================

def test_transient_failure_retry_and_recovery():
    """Verify transient 5xx/network errors are retried and recover on success."""
    provider = MockDeterministicLLMProvider()
    # Attempt 1: Transient 503 error
    # Attempt 2: Transient network reset
    # Attempt 3: Success
    provider.queue_response(LLMTransientException("503 Service Unavailable", status_code=503))
    provider.queue_response(LLMTransientException("Connection reset by peer"))
    provider.queue_response("Recovered response text")

    config = LLMClientConfig(max_retries=3)
    client = LLMClientAdapter(provider=provider, config=config, sleeper=fast_sleeper)

    result = client.generate("Test prompt")
    assert result == "Recovered response text"
    assert provider.call_count == 3
    assert client.get_metrics()["retries_attempted"] == 2
    assert client.get_metrics()["successful_requests"] == 1


def test_max_retries_exhausted_raises_exception():
    """Verify that exceeding max_retries raises the underlying transient exception."""
    provider = MockDeterministicLLMProvider()
    provider.queue_response(LLMTransientException("Persistent Error 1"))
    provider.queue_response(LLMTransientException("Persistent Error 2"))
    provider.queue_response(LLMTransientException("Persistent Error 3"))

    config = LLMClientConfig(max_retries=2)  # Max 2 retries (total 3 attempts)
    client = LLMClientAdapter(provider=provider, config=config, sleeper=fast_sleeper)

    with pytest.raises(LLMTransientException) as exc_info:
        client.generate("Test prompt")
    assert "Persistent Error 3" in str(exc_info.value)
    assert client.get_metrics()["failed_requests"] == 1


def test_non_retriable_auth_error_no_retry():
    """Verify 401/403 authentication errors fail immediately without retrying."""
    provider = MockDeterministicLLMProvider()
    provider.queue_response(LLMAuthenticationException("401 Invalid API Key"))

    config = LLMClientConfig(max_retries=3)
    client = LLMClientAdapter(provider=provider, config=config, sleeper=fast_sleeper)

    with pytest.raises(LLMAuthenticationException):
        client.generate("Test prompt")
    assert provider.call_count == 1
    assert client.get_metrics()["retries_attempted"] == 0
    assert client.get_metrics()["failed_requests"] == 1


# =========================================================================
# Structured Output Validation Tests
# =========================================================================

def test_structured_output_validation_success():
    """Verify structured output generates validated Pydantic model instances."""
    json_payload = json.dumps({
        "intent": "document_lookup",
        "confidence": 0.96,
        "items": ["DeepResidualLearning.pdf"]
    })
    provider = MockDeterministicLLMProvider(default_response=json_payload)
    client = LLMClientAdapter(provider=provider, sleeper=fast_sleeper)

    model = client.generate_structured("Lookup PDF", response_model=SampleTargetSchema)
    assert isinstance(model, SampleTargetSchema)
    assert model.intent == "document_lookup"
    assert model.confidence == 0.96


def test_structured_output_validation_with_domain_reasoning_result():
    """Verify structured output validation using core voicebot ReasoningResult schema."""
    result_data = {
        "response_id": "resp-llm-100",
        "request_id": "req-client-01",
        "session_id": "sess-client-01",
        "user_intent": "explain_technical_error",
        "response_text": "The error was caused by dividing by zero on line 42.",
        "reasoning_summary": "Identified division by zero in average calculation.",
        "tool_call_required": False,
        "risk_level": RiskLevel.CATEGORY_A_INFORMATIONAL.value,
        "requires_user_approval": False,
        "confidence_score": 0.95,
        "processing_time_ms": 12.5,
        "status": ExecutionStatus.SUCCESS.value,
    }
    provider = MockDeterministicLLMProvider(default_response=f"```json\n{json.dumps(result_data)}\n```")
    client = LLMClientAdapter(provider=provider, sleeper=fast_sleeper)

    res: ReasoningResult = client.generate_structured("Explain error", response_model=ReasoningResult)
    assert isinstance(res, ReasoningResult)
    assert res.response_id == "resp-llm-100"
    assert res.risk_level == RiskLevel.CATEGORY_A_INFORMATIONAL
    assert res.requires_user_approval is False


def test_structured_output_validation_retry_and_recovery():
    """Verify that invalid schema outputs trigger correction retries and recover on valid output."""
    provider = MockDeterministicLLMProvider()
    # Attempt 1: Malformed JSON syntax
    provider.queue_response("{bad_json: missing_quotes}")
    # Attempt 2: Valid JSON but missing required fields
    provider.queue_response('{"wrong_key": 123}')
    # Attempt 3: Valid conforming schema
    valid_payload = '{"intent": "fix_code", "confidence": 0.99, "items": ["calculator.py"]}'
    provider.queue_response(valid_payload)

    config = LLMClientConfig(max_retries=3)
    client = LLMClientAdapter(provider=provider, config=config, sleeper=fast_sleeper)

    model = client.generate_structured("Fix bug", response_model=SampleTargetSchema)
    assert model.intent == "fix_code"
    assert model.confidence == 0.99
    assert provider.call_count == 3
    assert client.get_metrics()["validation_failures"] == 2
    assert client.get_metrics()["retries_attempted"] == 2


def test_structured_output_validation_exhausted_raises_exception():
    """Verify that persistent schema violations raise StructuredOutputValidationException."""
    provider = MockDeterministicLLMProvider()
    provider.queue_response('{"invalid": true}')
    provider.queue_response('{"invalid": true}')

    config = LLMClientConfig(max_retries=1)
    client = LLMClientAdapter(provider=provider, config=config, sleeper=fast_sleeper)

    with pytest.raises(StructuredOutputValidationException) as exc_info:
        client.generate_structured("Fix bug", response_model=SampleTargetSchema)

    assert "SampleTargetSchema" in str(exc_info.value)
    assert exc_info.value.target_model == "SampleTargetSchema"
    assert exc_info.value.attempts == 2

