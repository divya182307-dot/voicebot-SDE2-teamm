"""
LLM Client Adapter with Timeout, Retry, and Structured-Output Validation.

Complies with:
- PRD Section 16 & SDD Section 5: Multimodal Reasoning & LLM Orchestration.
- PRD Section 18: Safety and Structured Response Contracts.
"""

from abc import ABC, abstractmethod
import concurrent.futures
import json
import logging
import random
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, TypeVar, Union

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger("voicebot.llm_client")

T = TypeVar("T", bound=BaseModel)


# =========================================================================
# Custom Exceptions
# =========================================================================

class LLMException(Exception):
    """Base exception for all LLM client errors."""
    pass


class LLMTimeoutException(LLMException):
    """Raised when an LLM provider request exceeds the configured timeout."""
    def __init__(self, message: str, timeout_seconds: float):
        super().__init__(message)
        self.timeout_seconds = timeout_seconds


class LLMTransientException(LLMException):
    """Raised for transient, retriable errors (5xx server errors, network drops, rate limits)."""
    def __init__(self, message: str, status_code: Optional[int] = None, retry_after: Optional[float] = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class LLMAuthenticationException(LLMException):
    """Raised for non-retriable authentication or credential errors (401/403)."""
    pass


class StructuredOutputValidationException(LLMException):
    """Raised when the LLM output fails schema validation after retries."""
    def __init__(self, message: str, raw_output: str, validation_errors: List[str], target_model: str, attempts: int):
        super().__init__(message)
        self.raw_output = raw_output
        self.validation_errors = validation_errors
        self.target_model = target_model
        self.attempts = attempts


# =========================================================================
# Configuration
# =========================================================================

class LLMClientConfig(BaseModel):
    """
    Configuration parameters for timeout, exponential backoff, and validation policies.
    """
    model_name: str = Field(default="gemini-1.5-pro", description="Identifier of the target model.")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0, description="Sampling temperature.")
    timeout_seconds: float = Field(default=10.0, ge=0.1, le=120.0, description="Per-request timeout ceiling.")
    max_retries: int = Field(default=3, ge=0, le=10, description="Maximum retry attempts on transient failures.")
    initial_backoff_seconds: float = Field(default=0.5, ge=0.01, description="Initial retry delay.")
    backoff_multiplier: float = Field(default=2.0, ge=1.0, description="Multiplier for exponential backoff.")
    max_backoff_seconds: float = Field(default=5.0, ge=0.1, description="Ceiling for retry delay.")
    jitter: bool = Field(default=True, description="Add random jitter to retry delays to avoid thundering herds.")


# =========================================================================
# Structured Output Parsing & Extraction
# =========================================================================

class StructuredOutputParser:
    """
    Extracts and validates JSON structures from LLM text generations.
    Handles Markdown code fences, conversational preambles, and schema validation.
    """

    @classmethod
    def extract_json_string(cls, text: str) -> str:
        """
        Strips markdown code fences (```json ... ```) or extracts JSON object substring.
        """
        stripped = text.strip()

        # Match ```json ... ``` or ``` ... ```
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped, re.IGNORECASE)
        if fence_match:
            return fence_match.group(1).strip()

        # If wrapped in curly braces {...}
        first_brace = stripped.find("{")
        last_brace = stripped.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            return stripped[first_brace:last_brace + 1].strip()

        # Fallback to trimmed text
        return stripped

    @classmethod
    def parse_and_validate(cls, raw_text: str, target_model: Type[T]) -> Tuple[Optional[T], Optional[str]]:
        """
        Attempts to parse JSON from raw_text and validate into target_model.
        
        Returns:
            Tuple of (validated_model_instance, error_message)
        """
        json_str = cls.extract_json_string(raw_text)
        try:
            parsed_data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            return None, f"JSONDecodeError: {str(exc)} at position {exc.pos}"

        if not isinstance(parsed_data, dict):
            return None, f"Expected a JSON object (dict), but parsed: {type(parsed_data).__name__}"

        try:
            instance = target_model.model_validate(parsed_data)
            return instance, None
        except ValidationError as val_err:
            error_details = []
            for err in val_err.errors():
                loc = ".".join(str(p) for p in err["loc"])
                msg = err["msg"]
                error_details.append(f"Field '{loc}': {msg}")
            return None, " | ".join(error_details)


# =========================================================================
# Provider Protocol and Deterministic Mock Implementation
# =========================================================================

class BaseLLMProvider(ABC):
    """
    Abstract interface for underlying model API providers (e.g. Gemini, OpenAI, Claude, or Mock).
    """

    @abstractmethod
    def generate(self, prompt: str, system_instruction: Optional[str] = None, timeout: Optional[float] = None) -> str:
        """
        Executes a single raw generation call to the model provider.
        """
        pass


class MockDeterministicLLMProvider(BaseLLMProvider):
    """
    Deterministic mock provider for unit testing, offline execution, and error simulation.
    Supports injecting programmed failures (timeouts, transient errors, invalid JSON)
    to thoroughly test retry and fallback handling.
    """

    def __init__(self, default_response: Optional[str] = None):
        self._default_response = default_response or "{}"
        self._response_queue: List[Union[str, Exception]] = []
        self._call_count: int = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    def queue_response(self, response_or_exception: Union[str, Exception]) -> "MockDeterministicLLMProvider":
        """Queues a sequence of programmed responses or exceptions."""
        self._response_queue.append(response_or_exception)
        return self

    def generate(self, prompt: str, system_instruction: Optional[str] = None, timeout: Optional[float] = None) -> str:
        self._call_count += 1

        if self._response_queue:
            item = self._response_queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        return self._default_response


# =========================================================================
# LLM Client Adapter
# =========================================================================

class LLMClientAdapter:
    """
    Resilient LLM Client Adapter providing:
    1. Per-request timeout enforcement via concurrent futures.
    2. Exponential backoff retry with jitter on transient failures.
    3. Structured output parsing and strict Pydantic model validation with self-correction retry.
    """

    def __init__(
        self,
        provider: Optional[BaseLLMProvider] = None,
        config: Optional[LLMClientConfig] = None,
        sleeper: Optional[Callable[[float], None]] = None,
    ):
        self._provider = provider or MockDeterministicLLMProvider()
        self._config = config or LLMClientConfig()
        self._sleeper = sleeper or time.sleep

        # Metrics & Telemetry
        self._metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "retries_attempted": 0,
            "timeouts_encountered": 0,
            "validation_failures": 0,
        }

    @property
    def config(self) -> LLMClientConfig:
        return self._config

    @property
    def provider(self) -> BaseLLMProvider:
        return self._provider

    def get_metrics(self) -> Dict[str, Any]:
        """Returns client reliability telemetry."""
        return dict(self._metrics)

    def _compute_backoff_delay(self, attempt: int) -> float:
        """
        Calculates exponential backoff delay with optional random jitter.
        """
        delay = self._config.initial_backoff_seconds * (self._config.backoff_multiplier ** attempt)
        delay = min(delay, self._config.max_backoff_seconds)
        if self._config.jitter:
            delay = delay * (0.5 + random.random() * 0.5)
        return round(delay, 4)

    def _invoke_with_timeout(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> str:
        """
        Invokes provider generation inside a thread pool to enforce strict timeout.
        """
        limit = timeout or self._config.timeout_seconds

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                self._provider.generate,
                prompt,
                system_instruction=system_instruction,
                timeout=limit,
            )
            try:
                return future.result(timeout=limit)
            except concurrent.futures.TimeoutError:
                self._metrics["timeouts_encountered"] += 1
                raise LLMTimeoutException(
                    f"LLM generation request timed out after {limit:.2f} seconds.",
                    timeout_seconds=limit,
                )

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> str:
        """
        Executes text generation with timeout enforcement and exponential backoff retry.
        Retries on LLMTimeoutException and LLMTransientException up to max_retries.
        """
        self._metrics["total_requests"] += 1
        max_attempts = self._config.max_retries + 1
        last_exception: Optional[Exception] = None

        for attempt in range(max_attempts):
            try:
                output = self._invoke_with_timeout(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    timeout=timeout,
                )
                self._metrics["successful_requests"] += 1
                return output

            except (LLMTimeoutException, LLMTransientException) as exc:
                last_exception = exc
                if attempt < self._config.max_retries:
                    self._metrics["retries_attempted"] += 1
                    delay = self._compute_backoff_delay(attempt)
                    logger.warning(
                        f"Transient error on LLM attempt {attempt + 1}/{max_attempts}: {exc}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                    self._sleeper(delay)
                else:
                    break

            except LLMAuthenticationException:
                # Permanent failure: Do not retry authentication errors
                self._metrics["failed_requests"] += 1
                raise

            except Exception as unhandled:
                self._metrics["failed_requests"] += 1
                raise LLMException(f"Unhandled LLM error: {unhandled}") from unhandled

        self._metrics["failed_requests"] += 1
        raise last_exception or LLMException("LLM request failed after retries.")

    def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system_instruction: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> T:
        """
        Generates structured response validated against a target Pydantic model.
        
        If parsing or validation fails, re-prompts the model with the validation error details
        up to max_retries before raising StructuredOutputValidationException.
        """
        current_prompt = prompt
        max_attempts = self._config.max_retries + 1
        all_validation_errors: List[str] = []
        last_raw_output: str = ""

        for attempt in range(max_attempts):
            raw_output = self.generate(
                prompt=current_prompt,
                system_instruction=system_instruction,
                timeout=timeout,
            )
            last_raw_output = raw_output

            # Parse and validate against target Pydantic schema
            instance, error_msg = StructuredOutputParser.parse_and_validate(raw_output, response_model)

            if instance is not None:
                return instance

            # Record validation failure
            self._metrics["validation_failures"] += 1
            all_validation_errors.append(error_msg or "Unknown validation error")

            if attempt < self._config.max_retries:
                self._metrics["retries_attempted"] += 1
                # Format correction prompt detailing the schema requirements
                current_prompt = (
                    f"{prompt}\n\n"
                    f"[SYSTEM CORRECTION REQUIRED]:\n"
                    f"Your previous response failed validation with error: {error_msg}\n"
                    f"Output MUST be valid JSON adhering strictly to {response_model.__name__} schema.\n"
                    f"Do not include conversational text or explanation outside the JSON object."
                )
                delay = self._compute_backoff_delay(attempt)
                self._sleeper(delay)

        self._metrics["failed_requests"] += 1
        raise StructuredOutputValidationException(
            f"Failed to produce valid structured output for {response_model.__name__} after {max_attempts} attempts: "
            f"{all_validation_errors[-1]}",
            raw_output=last_raw_output,
            validation_errors=all_validation_errors,
            target_model=response_model.__name__,
            attempts=max_attempts,
        )

