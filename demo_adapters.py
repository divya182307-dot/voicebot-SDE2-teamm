"""
CLI Interactive Demonstration for Opt-In Capture Adapter and Vision/OCR Adapter.
Usage:
    python projects/sde-2-voicebot/demo_adapters.py
"""

import os
import sys
import time

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from app.schemas.common import CaptureMode
from app.schemas.context import ScreenContext
from app.vision import (
    BaseCaptureProvider,
    CaptureConfig,
    CaptureNotAuthorizedException,
    CaptureSizeLimitExceededException,
    DeterministicVisionAdapter,
    OptInCaptureAdapter,
    SamplingLimitExceededException,
    SyntheticScenario,
)


def banner(title: str):
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def main():
    banner("1. OPT-IN PRIVACY ENFORCEMENT DEMO")
    adapter = OptInCaptureAdapter(config=CaptureConfig(min_interval_seconds=1.0))
    print(f"[*] Initial Opt-in status: {adapter.is_opted_in} (STRICTLY DISABLED BY DEFAULT)")

    # Attempt capture while unauthorized
    print("\n[Step 1.1] Attempting capture without user consent:")
    try:
        adapter.capture()
    except CaptureNotAuthorizedException as e:
        print(f"  [X] BLOCKED: {e}")

    # Explicit user opt-in
    print("\n[Step 1.2] User explicitly opts in:")
    adapter.opt_in(consent_token="user-token-abc")
    print(f"  [OK] Opt-in Active: {adapter.is_opted_in}")
    frame = adapter.capture(scenario=SyntheticScenario.CODE_EDITOR_ERROR)
    print(f"  [OK] Captured Frame: {frame.capture_id} ({frame.application_name} - {frame.width}x{frame.height}px)")

    banner("2. SAMPLING RATE LIMITS (ANTI-SURVEILLANCE DEMO)")
    print("[Step 2.1] Attempting rapid back-to-back capture (within 1.0s limit):")
    try:
        adapter.capture(scenario=SyntheticScenario.CODE_EDITOR_ERROR)
    except SamplingLimitExceededException as e:
        print(f"  [X] THROTTLED: {e}")
        print(f"  [>] Retry after: {e.retry_after_seconds:.2f} seconds")

    banner("3. RESOLUTION & SIZE LIMITS (DATA MINIMIZATION DEMO)")
    # Provider returning 4K resolution (3840x2160)
    class HighResProvider(BaseCaptureProvider):
        def capture_raw(self, mode=CaptureMode.ACTIVE_WINDOW, scenario=None, **kwargs):
            return ScreenContext(
                capture_id="cap-4k-001",
                width=3840,
                height=2160,
                application_name="Design Tool",
                window_title="Canvas 4K",
                ocr_text="Large canvas text",
            )

    cfg = CaptureConfig(max_width=1920, max_height=1080, min_interval_seconds=0.0)
    resizing_adapter = OptInCaptureAdapter(provider=HighResProvider(), config=cfg)
    resizing_adapter.opt_in()
    
    downscaled = resizing_adapter.capture()
    print(f"[*] Original Frame Resolution: 3840x2160 (4K)")
    print(f"[*] Auto-Scaled Frame:         {downscaled.width}x{downscaled.height} (Aspect-ratio preserved <= 1920x1080)")

    banner("4. OCR & VISION ADAPTER (TEXT EXTRACTION & PII REDACTION)")
    vision = DeterministicVisionAdapter()
    test_input = (
        "ZeroDivisionError: division by zero on line 42 in calculate_average\n"
        "Config: API_KEY = 'sk-prod-998877665544332211' | User: admin@example.com"
    )
    print(f"[*] Raw Screen Text Input:\n    {test_input.replace(chr(10), chr(10) + '    ')}")

    analysis = vision.analyze_visuals(test_input)
    print(f"\n[Step 4.1] OCR Extraction:")
    print(f"  - Words: {analysis.ocr.word_count} | Lines: {analysis.ocr.line_count} | Confidence: {analysis.ocr.confidence}")
    print(f"\n[Step 4.2] Multimodal Visual Summary:")
    print(f"  - Summary: {analysis.visual_summary}")
    print(f"  - Detected UI Elements: {analysis.detected_elements}")
    print(f"\n[Step 4.3] Privacy & Sensitive Data Detection (PRD Section 19):")
    print(f"  - Contains Sensitive Data: {analysis.contains_sensitive_data}")
    print(f"  - Detected Categories:     {analysis.ocr.detected_pii_categories}")

    redacted = vision._scanner.redact(test_input)
    print(f"\n[Step 4.4] Redacted Safe Payload:\n    {redacted.replace(chr(10), chr(10) + '    ')}")

    banner("ALL CHECKS COMPLETED SUCCESSFULLY")


if __name__ == "__main__":
    main()

