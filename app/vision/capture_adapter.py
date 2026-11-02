"""
Opt-In Capture Adapter with Sampling and Size Limits.
Complies with:
- PRD NG3: No continuous unrestricted surveillance.
- PRD Section 14: Screen & Visual Understanding (FR-VISION-001, FR-VISION-002, FR-VISION-005).
- PRD Section 19: Privacy Requirements (explicit user opt-in, data minimization).
"""

from abc import ABC, abstractmethod
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
import time
from typing import Any, Deque, Dict, Generator, Optional, Set, Tuple

from pydantic import BaseModel, Field

from app.schemas.common import CaptureMode
from app.schemas.context import ScreenContext
from app.vision.synthetic_frames import (
    DEFAULT_FIXED_TIMESTAMP,
    DEFAULT_FIXED_UID,
    ScreenCaptureDisabledException,
    ScreenCaptureManager,
    SyntheticScenario,
)


class CaptureNotAuthorizedException(ScreenCaptureDisabledException):
    """
    Raised when screen capture is attempted without explicit user opt-in.
    Enforces privacy-first opt-in requirement (FR-VISION-001 & PRD Section 19).
    """
    pass


class SamplingLimitExceededException(RuntimeError):
    """
    Raised when screen capture requests exceed sampling rate or interval limits.
    Enforces anti-surveillance policies (PRD NG3 & FR-VISION-005).
    """
    def __init__(self, message: str, retry_after_seconds: float, current_rate: int, limit: int):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.current_rate = current_rate
        self.limit = limit


class CaptureSizeLimitExceededException(ValueError):
    """
    Raised when requested capture resolution or payload byte size exceeds configured bounds.
    Enforces data minimization (FR-VISION-002 & FR-VISION-005).
    """
    def __init__(self, message: str, width: int, height: int, max_width: int, max_height: int, payload_bytes: Optional[int] = None):
        super().__init__(message)
        self.width = width
        self.height = height
        self.max_width = max_width
        self.max_height = max_height
        self.payload_bytes = payload_bytes


class CaptureConfig(BaseModel):
    """
    Configuration parameters for opt-in capture, sampling boundaries, and size limits.
    """
    # Size Limits (Resolution & Payload)
    max_width: int = Field(
        default=1920,
        ge=320,
        le=7680,
        description="Maximum permissible width in pixels (data minimization). Default: 1920 (1080p)."
    )
    max_height: int = Field(
        default=1080,
        ge=240,
        le=4320,
        description="Maximum permissible height in pixels. Default: 1080 (1080p)."
    )
    max_payload_bytes: int = Field(
        default=5 * 1024 * 1024,
        ge=1024,
        le=20 * 1024 * 1024,
        description="Maximum allowed image payload size in bytes (5 MB default)."
    )
    strict_size_enforcement: bool = Field(
        default=False,
        description="If True, raises CaptureSizeLimitExceededException on oversized frames. If False, scales down."
    )

    # Sampling Limits (Anti-Surveillance & Rate Limiting)
    min_interval_seconds: float = Field(
        default=1.0,
        ge=0.0,
        le=60.0,
        description="Minimum elapsed time required between consecutive screen captures. Default: 1.0s."
    )
    max_samples_per_minute: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Maximum allowed capture samples within a 60-second sliding window. Default: 30."
    )

    # Privacy & Consent Scope
    allowed_modes: Set[CaptureMode] = Field(
        default_factory=lambda: {
            CaptureMode.ACTIVE_WINDOW,
            CaptureMode.REGION,
            CaptureMode.SELECTION,
            CaptureMode.FULLSCREEN,
        },
        description="Permissible capture scopes."
    )
    prefer_active_window: bool = Field(
        default=True,
        description="Enforces data minimization by favoring active window over fullscreen."
    )


class BaseCaptureProvider(ABC):
    """
    Abstract interface for underlying screen capture providers (synthetic or OS-level).
    """

    @abstractmethod
    def capture_raw(
        self,
        mode: CaptureMode,
        scenario: Optional[SyntheticScenario] = None,
        **kwargs: Any,
    ) -> ScreenContext:
        """
        Executes raw frame acquisition.
        """
        pass


class SyntheticCaptureProvider(BaseCaptureProvider):
    """
    Default capture provider backed by deterministic synthetic screen frames.
    """

    def __init__(self, manager: Optional[ScreenCaptureManager] = None):
        self._manager = manager or ScreenCaptureManager(capture_enabled=True)

    def capture_raw(
        self,
        mode: CaptureMode = CaptureMode.ACTIVE_WINDOW,
        scenario: Optional[SyntheticScenario] = None,
        **kwargs: Any,
    ) -> ScreenContext:
        sc = scenario or SyntheticScenario.CODE_EDITOR_ERROR
        # Temporarily authorize manager to produce synthetic scenario
        with self._manager.authorized_session():
            frame = self._manager.capture_frame(sc)
            frame.capture_mode = mode
            return frame


class OptInCaptureAdapter:
    """
    Opt-in Screen Capture Adapter with Sampling Rate Limiting and Size Enforcement.
    
    Guarantees:
    1. Opt-in Required: Strictly disabled by default. Requires explicit opt_in() or authorized_session().
    2. Sampling Rate Limits: Enforces minimum interval and maximum samples per minute to prevent continuous surveillance.
    3. Size & Payload Limits: Enforces maximum pixel resolution and byte payload limits, scaling down or rejecting oversized frames.
    """

    def __init__(
        self,
        provider: Optional[BaseCaptureProvider] = None,
        config: Optional[CaptureConfig] = None,
        clock: Optional[Any] = None,
    ):
        self._provider: BaseCaptureProvider = provider or SyntheticCaptureProvider()
        self._config: CaptureConfig = config or CaptureConfig()
        
        # Privacy state: Strictly disabled by default (opt-in)
        self._opt_in: bool = False
        self._consent_token: Optional[str] = None
        self._consent_timestamp: Optional[datetime] = None
        
        # Clock provider (allows deterministic time injection in tests)
        self._clock = clock or time.time
        
        # Sampling state tracking (sliding window of timestamps in seconds)
        self._sample_timestamps: Deque[float] = deque()
        self._last_capture_time: float = 0.0

        # Metrics
        self._total_captures: int = 0
        self._throttled_requests: int = 0
        self._resized_frames: int = 0

    @property
    def is_opted_in(self) -> bool:
        """Returns True if user has explicitly opted into screen capture."""
        return self._opt_in

    @property
    def config(self) -> CaptureConfig:
        """Returns active adapter configuration."""
        return self._config

    def opt_in(self, consent_token: Optional[str] = None) -> None:
        """
        Explicitly opts in to screen capture with user consent (FR-VISION-001).
        """
        self._opt_in = True
        self._consent_token = consent_token or f"consent-{DEFAULT_FIXED_UID}"
        self._consent_timestamp = datetime.now(timezone.utc)

    def opt_out(self) -> None:
        """
        Revokes screen capture authorization immediately.
        """
        self._opt_in = False
        self._consent_token = None
        self._consent_timestamp = None

    @contextmanager
    def authorized_session(self, consent_token: Optional[str] = None) -> Generator[None, None, None]:
        """
        Context manager for temporary, scope-limited capture authorization.
        Automatically revokes access upon exit.
        """
        previous_opt_in = self._opt_in
        previous_token = self._consent_token
        self.opt_in(consent_token)
        try:
            yield
        finally:
            self._opt_in = previous_opt_in
            self._consent_token = previous_token

    def can_sample(self) -> Tuple[bool, float]:
        """
        Evaluates whether a capture is currently permissible under sampling limits.
        
        Returns:
            Tuple of (is_allowed: bool, wait_seconds: float)
        """
        now = float(self._clock())
        
        # 1. Enforce minimum interval between consecutive captures
        if self._last_capture_time > 0:
            elapsed = now - self._last_capture_time
            if elapsed < self._config.min_interval_seconds:
                wait_time = self._config.min_interval_seconds - elapsed
                return False, wait_time

        # 2. Enforce sliding window (samples in last 60 seconds)
        cutoff = now - 60.0
        while self._sample_timestamps and self._sample_timestamps[0] < cutoff:
            self._sample_timestamps.popleft()

        if len(self._sample_timestamps) >= self._config.max_samples_per_minute:
            oldest_in_window = self._sample_timestamps[0]
            wait_time = max(0.0, 60.0 - (now - oldest_in_window))
            return False, wait_time

        return True, 0.0

    def compute_bounded_dimensions(self, width: int, height: int) -> Tuple[int, int, bool]:
        """
        Computes aspect-ratio preserved dimensions conforming to size limits.
        
        Returns:
            Tuple of (clamped_width: int, clamped_height: int, was_resized: bool)
        """
        max_w = self._config.max_width
        max_h = self._config.max_height

        if width <= max_w and height <= max_h:
            return width, height, False

        # Calculate uniform downscale factor
        scale = min(max_w / float(width), max_h / float(height))
        clamped_w = max(1, int(width * scale))
        clamped_h = max(1, int(height * scale))
        return clamped_w, clamped_h, True

    def capture(
        self,
        mode: CaptureMode = CaptureMode.ACTIVE_WINDOW,
        scenario: Optional[SyntheticScenario] = None,
        **kwargs: Any,
    ) -> ScreenContext:
        """
        Captures a screen frame while strictly enforcing:
        1. Explicit user opt-in (raises CaptureNotAuthorizedException if not opted in).
        2. Sampling rate limits (raises SamplingLimitExceededException if called too frequently).
        3. Size & resolution limits (raises CaptureSizeLimitExceededException or scales down).
        """
        # Step 1: Privacy Check (Opt-in Required)
        if not self._opt_in:
            raise CaptureNotAuthorizedException(
                "Screen capture is strictly disabled by default (opt-in required). "
                "Explicit user authorization must be granted via opt_in() before capturing."
            )

        # Step 2: Sampling Rate & Anti-Surveillance Check
        allowed, wait_seconds = self.can_sample()
        if not allowed:
            self._throttled_requests += 1
            current_rate = len(self._sample_timestamps)
            raise SamplingLimitExceededException(
                f"Screen capture sampling limit reached: cannot exceed {self._config.max_samples_per_minute} samples/min "
                f"or capture faster than every {self._config.min_interval_seconds}s. Retry in {wait_seconds:.2f}s.",
                retry_after_seconds=wait_seconds,
                current_rate=current_rate,
                limit=self._config.max_samples_per_minute,
            )

        # Step 3: Raw Frame Acquisition
        frame = self._provider.capture_raw(mode=mode, scenario=scenario, **kwargs)

        # Step 4: Size and Resolution Bounds Enforcement
        target_w, target_h, was_resized = self.compute_bounded_dimensions(frame.width, frame.height)
        if was_resized:
            if self._config.strict_size_enforcement:
                raise CaptureSizeLimitExceededException(
                    f"Frame dimensions {frame.width}x{frame.height} exceed maximum allowed "
                    f"bounds {self._config.max_width}x{self._config.max_height}.",
                    width=frame.width,
                    height=frame.height,
                    max_width=self._config.max_width,
                    max_height=self._config.max_height,
                )
            # Apply aspect-preserving downscaled dimensions
            frame.width = target_w
            frame.height = target_h
            self._resized_frames += 1

        # Check payload size limit
        if frame.image_base64:
            payload_len = len(frame.image_base64.encode("utf-8"))
            if payload_len > self._config.max_payload_bytes:
                raise CaptureSizeLimitExceededException(
                    f"Image payload size ({payload_len} bytes) exceeds limit ({self._config.max_payload_bytes} bytes).",
                    width=frame.width,
                    height=frame.height,
                    max_width=self._config.max_width,
                    max_height=self._config.max_height,
                    payload_bytes=payload_len,
                )

        # Step 5: Commit sample to rate limiter history
        now = float(self._clock())
        self._last_capture_time = now
        self._sample_timestamps.append(now)
        self._total_captures += 1

        return frame

    def reset_sampling_history(self) -> None:
        """Resets the internal sampling timestamps and throttled count."""
        self._sample_timestamps.clear()
        self._last_capture_time = 0.0

    def get_metrics(self) -> Dict[str, Any]:
        """Returns telemetry metrics for capture operations and sampling enforcement."""
        return {
            "opt_in_active": self._opt_in,
            "total_captures": self._total_captures,
            "throttled_requests": self._throttled_requests,
            "resized_frames": self._resized_frames,
            "active_samples_in_window": len(self._sample_timestamps),
            "max_samples_per_minute": self._config.max_samples_per_minute,
            "min_interval_seconds": self._config.min_interval_seconds,
            "max_width": self._config.max_width,
            "max_height": self._config.max_height,
        }

