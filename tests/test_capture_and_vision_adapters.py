"""
Unit tests for Opt-In Capture Adapter (Sampling & Size Limits) and OCR/Vision Adapter Interface.
Complies with:
- PRD NG3: No continuous unrestricted surveillance.
- PRD Section 14: Screen & Visual Understanding (FR-VISION-001..006).
- PRD Section 19: Privacy Requirements (explicit opt-in, data minimization).
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
from app.schemas.context import ScreenContext
from app.vision.capture_adapter import (
    BaseCaptureProvider,
    CaptureConfig,
    CaptureNotAuthorizedException,
    CaptureSizeLimitExceededException,
    OptInCaptureAdapter,
    SamplingLimitExceededException,
    SyntheticCaptureProvider,
)
from app.vision.synthetic_frames import SyntheticScenario
from app.vision.vision_adapter import (
    DeterministicVisionAdapter,
    OCRResult,
    RuleBasedSensitiveDataScanner,
    VisionAnalysisResult,
)


class MockClock:
    """Controllable virtual clock for deterministic sampling rate tests."""
    def __init__(self, start_time: float = 1000.0):
        self.current_time = start_time

    def __call__(self) -> float:
        return self.current_time

    def advance(self, seconds: float) -> None:
        self.current_time += seconds


class CustomFrameProvider(BaseCaptureProvider):
    """Custom provider generating frames with arbitrary dimensions or payloads."""
    def __init__(self, width: int = 3840, height: int = 2160, payload: str = None):
        self.width = width
        self.height = height
        self.payload = payload

    def capture_raw(self, mode: CaptureMode = CaptureMode.ACTIVE_WINDOW, scenario=None, **kwargs) -> ScreenContext:
        return ScreenContext(
            capture_id="cap-custom-001",
            width=self.width,
            height=self.height,
            capture_mode=mode,
            application_name="Test App",
            window_title="Test Window",
            ocr_text="Custom sample text",
            image_base64=self.payload,
        )


# =========================================================================
# Opt-In Capture Adapter Tests
# =========================================================================

def test_opt_in_required_by_default():
    """Verify capture adapter is strictly opt-in (disabled by default)."""
    adapter = OptInCaptureAdapter()
    assert adapter.is_opted_in is False

    with pytest.raises(CaptureNotAuthorizedException) as exc_info:
        adapter.capture()
    assert "opt-in required" in str(exc_info.value)


def test_opt_in_enables_capture():
    """Verify explicit opt_in() allows capturing frames."""
    adapter = OptInCaptureAdapter()
    adapter.opt_in(consent_token="user-consent-123")
    assert adapter.is_opted_in is True

    frame = adapter.capture(scenario=SyntheticScenario.CODE_EDITOR_ERROR)
    assert frame is not None
    assert frame.application_name == "VS Code"
    assert frame.width > 0


def test_opt_out_revokes_capture():
    """Verify opt_out() immediately revokes capture permissions."""
    adapter = OptInCaptureAdapter()
    adapter.opt_in()
    assert adapter.is_opted_in is True

    adapter.opt_out()
    assert adapter.is_opted_in is False
    with pytest.raises(CaptureNotAuthorizedException):
        adapter.capture()


def test_authorized_session_context_manager():
    """Verify authorized_session temporarily authorizes capture and auto-revokes."""
    adapter = OptInCaptureAdapter()
    assert adapter.is_opted_in is False

    with adapter.authorized_session():
        assert adapter.is_opted_in is True
        frame = adapter.capture(scenario=SyntheticScenario.SPREADSHEET_ANALYSIS)
        assert frame.application_name == "Microsoft Excel"

    # Must be disabled immediately upon leaving context
    assert adapter.is_opted_in is False
    with pytest.raises(CaptureNotAuthorizedException):
        adapter.capture()


def test_sampling_rate_limit_min_interval():
    """Verify minimum interval enforcement throttles rapid captures."""
    clock = MockClock(1000.0)
    config = CaptureConfig(min_interval_seconds=2.0)
    adapter = OptInCaptureAdapter(config=config, clock=clock)
    adapter.opt_in()

    # First capture succeeds at t=1000.0
    frame1 = adapter.capture()
    assert frame1 is not None

    # Immediate second capture at t=1000.5 fails (elapsed 0.5s < 2.0s required)
    clock.advance(0.5)
    with pytest.raises(SamplingLimitExceededException) as exc:
        adapter.capture()
    assert exc.value.retry_after_seconds > 0.0

    # Advance clock past interval (t=1002.1) -> capture succeeds
    clock.advance(1.6)
    frame2 = adapter.capture()
    assert frame2 is not None


def test_sampling_rate_limit_sliding_window():
    """Verify max samples per minute sliding window limit."""
    clock = MockClock(1000.0)
    config = CaptureConfig(min_interval_seconds=0.1, max_samples_per_minute=3)
    adapter = OptInCaptureAdapter(config=config, clock=clock)
    adapter.opt_in()

    # 3 samples within 30 seconds
    clock.advance(0.2); adapter.capture()
    clock.advance(0.2); adapter.capture()
    clock.advance(0.2); adapter.capture()

    # 4th sample within same minute must be rejected
    clock.advance(0.2)
    with pytest.raises(SamplingLimitExceededException) as exc:
        adapter.capture()
    assert exc.value.limit == 3

    # Advance 61 seconds so window slides past oldest sample
    clock.advance(60.1)
    frame = adapter.capture()
    assert frame is not None


def test_size_limits_scale_down_aspect_ratio():
    """Verify oversized frames are automatically scaled down to configured limits."""
    # 4K frame (3840x2160)
    provider = CustomFrameProvider(width=3840, height=2160)
    config = CaptureConfig(max_width=1920, max_height=1080, strict_size_enforcement=False)
    adapter = OptInCaptureAdapter(provider=provider, config=config)
    adapter.opt_in()

    frame = adapter.capture()
    assert frame.width == 1920
    assert frame.height == 1080
    assert adapter.get_metrics()["resized_frames"] == 1


def test_size_limits_strict_rejection():
    """Verify strict_size_enforcement raises exception on oversized dimensions."""
    provider = CustomFrameProvider(width=3840, height=2160)
    config = CaptureConfig(max_width=1920, max_height=1080, strict_size_enforcement=True)
    adapter = OptInCaptureAdapter(provider=provider, config=config)
    adapter.opt_in()

    with pytest.raises(CaptureSizeLimitExceededException) as exc:
        adapter.capture()
    assert exc.value.width == 3840
    assert exc.value.max_width == 1920


def test_size_limits_payload_bytes_exceeded():
    """Verify oversized base64 payload triggers size limit exception."""
    oversized_payload = "A" * (2 * 1024 * 1024)  # 2 MB string
    provider = CustomFrameProvider(width=800, height=600, payload=oversized_payload)
    config = CaptureConfig(max_payload_bytes=1 * 1024 * 1024)  # 1 MB limit
    adapter = OptInCaptureAdapter(provider=provider, config=config)
    adapter.opt_in()

    with pytest.raises(CaptureSizeLimitExceededException) as exc:
        adapter.capture()
    assert exc.value.payload_bytes is not None


def test_capture_adapter_metrics():
    """Verify adapter records metrics for total captures and throttled requests."""
    clock = MockClock(100.0)
    config = CaptureConfig(min_interval_seconds=1.0)
    adapter = OptInCaptureAdapter(config=config, clock=clock)
    adapter.opt_in()

    adapter.capture()
    try:
        adapter.capture()  # Throttled
    except SamplingLimitExceededException:
        pass

    metrics = adapter.get_metrics()
    assert metrics["total_captures"] == 1
    assert metrics["throttled_requests"] == 1
    assert metrics["opt_in_active"] is True


# =========================================================================
# OCR / Vision Adapter Interface Tests
# =========================================================================

def test_vision_adapter_extract_text():
    """Verify text, word count, line count, and confidence extraction."""
    adapter = DeterministicVisionAdapter()
    sample_text = "def calculate():\n    return 42"
    result: OCRResult = adapter.extract_text(sample_text)

    assert result.text == sample_text
    assert result.word_count == 4
    assert result.line_count == 2
    assert result.confidence >= 0.90
    assert result.contains_sensitive_data is False


def test_vision_adapter_analyze_visuals():
    """Verify semantic UI layout summary and UI widget classification."""
    adapter = DeterministicVisionAdapter()
    error_text = "ZeroDivisionError: division by zero in calculate_average"
    result: VisionAnalysisResult = adapter.analyze_visuals(error_text)

    assert "code_editor" in result.detected_elements
    assert "stack_trace" in result.detected_elements
    assert "exception" in result.visual_summary.lower() or "error" in result.visual_summary.lower()


def test_vision_adapter_detects_sensitive_data_and_pii():
    """Verify detection of API keys, credentials, and emails."""
    adapter = DeterministicVisionAdapter()
    sensitive_text = "api_key = 'sk-live-998877665544332211' user=admin@company.com"
    result = adapter.extract_text(sensitive_text)

    assert result.contains_sensitive_data is True
    assert "api_key" in result.detected_pii_categories or "email_address" in result.detected_pii_categories


def test_sensitive_data_scanner_redaction():
    """Verify sensitive data scanner masks credentials."""
    scanner = RuleBasedSensitiveDataScanner()
    raw = "My API_KEY = 'secret123456789' and user@example.com"
    redacted = scanner.redact(raw)

    assert "secret123456789" not in redacted
    assert "[REDACTED_" in redacted


def test_vision_adapter_process_screen_context():
    """Verify processing and enriching an active ScreenContext instance."""
    adapter = DeterministicVisionAdapter()
    context = ScreenContext(
        capture_id="cap-enrich-001",
        width=1920,
        height=1080,
        application_name="VS Code",
        window_title="main.py",
        ocr_text="ZeroDivisionError: division by zero",
    )

    enriched = adapter.process_screen_context(context)
    assert enriched.ocr_confidence is not None
    assert enriched.ocr_confidence >= 0.90
    assert enriched.ocr_text == "ZeroDivisionError: division by zero"
