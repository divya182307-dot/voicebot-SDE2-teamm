"""
Unit tests for Task 1: Synthetic frames with screen capture disabled by default.
Compatible with pytest and standard Python test runners.
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

from app.schemas.common import CaptureMode
from app.vision.synthetic_frames import (
    ScreenCaptureDisabledException,
    ScreenCaptureManager,
    SyntheticScenario,
)


def test_screen_capture_disabled_by_default():
    """Verify that screen capture is strictly disabled by default per privacy requirements."""
    mgr = ScreenCaptureManager()
    assert mgr.is_capture_enabled is False


def test_capture_raises_when_disabled():
    """Verify that attempting to capture when disabled raises ScreenCaptureDisabledException."""
    mgr = ScreenCaptureManager()
    with pytest.raises(ScreenCaptureDisabledException) as exc_info:
        mgr.capture_frame(SyntheticScenario.CODE_EDITOR_ERROR)
    assert "disabled by default" in str(exc_info.value)


def test_capture_fallback_when_disabled():
    """Verify that placeholder frame is returned when fallback is allowed."""
    mgr = ScreenCaptureManager()
    frame = mgr.capture_frame(SyntheticScenario.CODE_EDITOR_ERROR, allow_fallback_when_disabled=True)
    assert "[Capture Disabled]" in frame.window_title
    assert "SCREEN CAPTURE DISABLED BY DEFAULT" in frame.ocr_text
    assert frame.image_base64 is None
    assert frame.contains_sensitive_data is False


def test_explicit_enable_and_disable():
    """Verify explicit permission enable and disable lifecycle."""
    mgr = ScreenCaptureManager()
    assert mgr.is_capture_enabled is False

    mgr.enable_capture()
    assert mgr.is_capture_enabled is True

    frame = mgr.capture_frame(SyntheticScenario.CODE_EDITOR_ERROR)
    assert frame.application_name == "VS Code"
    assert "ZeroDivisionError" in frame.ocr_text

    mgr.disable_capture()
    assert mgr.is_capture_enabled is False
    with pytest.raises(ScreenCaptureDisabledException):
        mgr.capture_frame(SyntheticScenario.CODE_EDITOR_ERROR)


def test_authorized_session_context_manager():
    """Verify that authorized_session enables capture temporarily and restores disabled state."""
    mgr = ScreenCaptureManager()
    assert mgr.is_capture_enabled is False

    with mgr.authorized_session():
        assert mgr.is_capture_enabled is True
        frame = mgr.capture_frame(SyntheticScenario.RESEARCH_PAPER_PDF)
        assert frame.application_name == "Acrobat Reader"
        assert "Methodology" in frame.ocr_text

    # After exiting context, should automatically be disabled again
    assert mgr.is_capture_enabled is False


def test_all_synthetic_scenarios_generate_valid_screen_context():
    """Verify that each synthetic scenario produces valid schema instances."""
    mgr = ScreenCaptureManager(capture_enabled=True)

    scenarios = [
        SyntheticScenario.CODE_EDITOR_ERROR,
        SyntheticScenario.RESEARCH_PAPER_PDF,
        SyntheticScenario.SPREADSHEET_ANALYSIS,
        SyntheticScenario.FILE_EXPLORER,
        SyntheticScenario.REDACTED_PRIVACY,
    ]

    for sc in scenarios:
        frame = mgr.capture_frame(sc)
        assert frame.capture_id is not None
        assert frame.width > 0
        assert frame.height > 0
        assert frame.ocr_confidence is not None
        assert 0.0 <= frame.ocr_confidence <= 1.0

        if sc == SyntheticScenario.REDACTED_PRIVACY:
            assert frame.contains_sensitive_data is True
            assert "[REDACTED_SECRET]" in frame.ocr_text


def test_create_custom_synthetic_frame():
    """Verify creation of custom synthetic frames."""
    frame = ScreenCaptureManager.create_custom_synthetic_frame(
        application_name="Custom IDE",
        window_title="test.py",
        ocr_text="print('Hello World')",
        width=1280,
        height=720,
        capture_mode=CaptureMode.ACTIVE_WINDOW,
    )
    assert frame.application_name == "Custom IDE"
    assert frame.width == 1280
    assert frame.height == 720
    assert frame.ocr_text == "print('Hello World')"
