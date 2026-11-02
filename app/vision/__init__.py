"""
Vision and Screen Understanding Package.
Provides:
- ScreenCaptureManager & SyntheticScenario (Synthetic Frames)
- OptInCaptureAdapter, CaptureConfig, Rate & Size limits (Opt-In Capture Adapter)
- BaseVisionAdapter, DeterministicVisionAdapter, OCRResult, VisionAnalysisResult (OCR/Vision Adapter Interface)
"""

from app.vision.synthetic_frames import (
    DEFAULT_FIXED_TIMESTAMP,
    DEFAULT_FIXED_UID,
    ScreenCaptureDisabledException,
    ScreenCaptureManager,
    SyntheticScenario,
)
from app.vision.capture_adapter import (
    BaseCaptureProvider,
    CaptureConfig,
    CaptureNotAuthorizedException,
    CaptureSizeLimitExceededException,
    OptInCaptureAdapter,
    SamplingLimitExceededException,
    SyntheticCaptureProvider,
)
from app.vision.vision_adapter import (
    BaseVisionAdapter,
    DeterministicVisionAdapter,
    OCRResult,
    RuleBasedSensitiveDataScanner,
    VisionAnalysisResult,
)

__all__ = [
    # Synthetic frames
    "ScreenCaptureManager",
    "ScreenCaptureDisabledException",
    "SyntheticScenario",
    "DEFAULT_FIXED_TIMESTAMP",
    "DEFAULT_FIXED_UID",
    # Opt-in Capture Adapter
    "OptInCaptureAdapter",
    "CaptureConfig",
    "BaseCaptureProvider",
    "SyntheticCaptureProvider",
    "CaptureNotAuthorizedException",
    "SamplingLimitExceededException",
    "CaptureSizeLimitExceededException",
    # OCR & Vision Adapter Interface
    "BaseVisionAdapter",
    "DeterministicVisionAdapter",
    "OCRResult",
    "VisionAnalysisResult",
    "RuleBasedSensitiveDataScanner",
]
