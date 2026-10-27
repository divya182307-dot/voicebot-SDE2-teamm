"""
End-to-End Integration Test for Day 2:
Connects all three components into a complete pipeline:
1. Synthetic Frame Capture (with privacy enforcement)
2. Versioned Prompt Formatting (trusted/untrusted separation)
3. Deterministic Mock Reasoning (consistent reproducible output & safety gates)
"""

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

from app.schemas.common import InputModality, RiskLevel
from app.schemas.reasoning import ReasoningRequest
from app.vision.synthetic_frames import (
    ScreenCaptureDisabledException,
    ScreenCaptureManager,
    SyntheticScenario,
)
from app.prompts.registry import default_prompt_registry
from app.reasoning.mock_engine import DeterministicMockReasoningEngine


def test_complete_day2_end_to_end_pipeline():
    """
    Validates the full workflow:
    Capture Manager (privacy) -> Versioned Prompt Template -> Mock Reasoning Engine.
    """
    # -------------------------------------------------------------
    # Step 1: Enforce Privacy Default (Screen capture disabled)
    # -------------------------------------------------------------
    cap_mgr = ScreenCaptureManager()
    assert cap_mgr.is_capture_enabled is False

    with pytest.raises(ScreenCaptureDisabledException):
        cap_mgr.capture_frame(SyntheticScenario.CODE_EDITOR_ERROR)

    # -------------------------------------------------------------
    # Step 2: Authorize Capture and Generate Synthetic Frame
    # -------------------------------------------------------------
    with cap_mgr.authorized_session():
        assert cap_mgr.is_capture_enabled is True
        screen_frame = cap_mgr.capture_frame(SyntheticScenario.CODE_EDITOR_ERROR)

    assert cap_mgr.is_capture_enabled is False  # Restored automatically
    assert screen_frame.application_name == "VS Code"
    assert "ZeroDivisionError" in screen_frame.ocr_text

    # -------------------------------------------------------------
    # Step 3: Render Versioned Prompt with Security Guardrails
    # -------------------------------------------------------------
    prompt_template = default_prompt_registry.get("multimodal_co_pilot", "1.1.0")
    user_query = "Why is this code throwing an exception?"

    rendered_prompt = prompt_template.render(
        user_query=user_query,
        screen_context_summary=f"App: {screen_frame.application_name}, OCR: {screen_frame.ocr_text}",
    )

    # Verify strict isolation
    assert "BEGIN TRUSTED SYSTEM INSTRUCTIONS" in rendered_prompt.system_instruction
    assert "<untrusted_user_input>" in rendered_prompt.user_payload
    assert user_query in rendered_prompt.user_payload
    assert "<untrusted_screen_context>" in rendered_prompt.user_payload

    # -------------------------------------------------------------
    # Step 4: Execute Deterministic Mock Reasoning
    # -------------------------------------------------------------
    engine = DeterministicMockReasoningEngine()
    request = ReasoningRequest(
        request_id="req-e2e-001",
        session_id="sess-e2e-001",
        user_query=user_query,
        modality=InputModality.VOICE,
        screen_context=screen_frame,
    )

    # Run reasoning twice to verify determinism
    res1 = engine.reason(request)
    res2 = engine.reason(request)

    assert res1.response_id == res2.response_id
    assert res1.user_intent == "explain_technical_error"
    assert res1.risk_level == RiskLevel.CATEGORY_A_INFORMATIONAL
    assert res1.requires_user_approval is False
    assert "ZeroDivisionError" in res1.response_text
    assert res1.confidence_score == res2.confidence_score
