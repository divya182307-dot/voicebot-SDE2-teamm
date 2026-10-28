"""
Synthetic Screen Frames & Capture Manager
Task 1: Create synthetic frames with screen capture disabled by default.

Complies with:
- PRD NG3: No continuous unrestricted surveillance
- PRD Section 14: Screen & Visual Understanding (FR-VISION-001..006)
- PRD Section 19: Privacy Requirements (explicit permissions, data minimization)
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Generator, Optional
import uuid

from app.schemas.common import BoundingBox, CaptureMode
from app.schemas.context import ScreenContext


class SyntheticScenario(str, Enum):
    """
    Standard pre-configured synthetic screen contexts matching PRD Personas & Use Cases.
    """
    CODE_EDITOR_ERROR = "code_editor_error"        # UC-02 / Persona 1 (Student Developer)
    RESEARCH_PAPER_PDF = "research_paper_pdf"      # UC-03 / Persona 2 (Research Student)
    SPREADSHEET_ANALYSIS = "spreadsheet_analysis"  # UC-04 (Tabular data / Trends)
    FILE_EXPLORER = "file_explorer"                # UC-06, UC-08 / Persona 3 (General User)
    REDACTED_PRIVACY = "redacted_privacy"          # Section 19 (PII / Sensitive Content)


class ScreenCaptureDisabledException(PermissionError):
    """
    Raised when screen capture is attempted while capture is disabled.
    Enforces privacy by default.
    """
    pass


class ScreenCaptureManager:
    """
    Manages screen capture authorization state and synthetic frame generation.
    CRITICAL: Screen capture is strictly DISABLED BY DEFAULT.
    """

    def __init__(self, capture_enabled: bool = False):
        # Explicitly disabled by default per privacy requirements
        self._capture_enabled: bool = capture_enabled

    @property
    def is_capture_enabled(self) -> bool:
        """Returns True if screen capture has been explicitly authorized."""
        return self._capture_enabled

    def enable_capture(self) -> None:
        """Explicitly enables screen capture following user consent (FR-VISION-001)."""
        self._capture_enabled = True

    def disable_capture(self) -> None:
        """Revokes screen capture authorization."""
        self._capture_enabled = False

    @contextmanager
    def authorized_session(self) -> Generator[None, None, None]:
        """
        Context manager for temporary, scope-limited capture authorization.
        Automatically revokes access upon exit.
        """
        previous_state = self._capture_enabled
        self._capture_enabled = True
        try:
            yield
        finally:
            self._capture_enabled = previous_state

    def capture_frame(
        self,
        scenario: SyntheticScenario = SyntheticScenario.CODE_EDITOR_ERROR,
        allow_fallback_when_disabled: bool = False,
    ) -> ScreenContext:
        """
        Captures or generates a synthetic screen frame.
        
        Args:
            scenario: Preset synthetic scenario to generate.
            allow_fallback_when_disabled: If True, returns a safe redacted placeholder frame
                                          instead of raising ScreenCaptureDisabledException.
        """
        if not self._capture_enabled:
            if allow_fallback_when_disabled:
                return self.get_disabled_placeholder_frame()
            raise ScreenCaptureDisabledException(
                "Screen capture is disabled by default. "
                "Explicit user authorization is required before capturing screen content."
            )

        return self.generate_synthetic_scenario(scenario)

    def get_disabled_placeholder_frame(self) -> ScreenContext:
        """
        Generates a non-intrusive placeholder frame when capture is disabled.
        Ensures no screen data is leaked when permissions are absent.
        """
        return ScreenContext(
            capture_id=f"cap-disabled-{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now(timezone.utc),
            capture_mode=CaptureMode.ACTIVE_WINDOW,
            application_name=None,
            window_title="[Capture Disabled]",
            width=1920,
            height=1080,
            dpi_scale=1.0,
            image_format="image/webp",
            image_base64=None,
            ocr_text="[SCREEN CAPTURE DISABLED BY DEFAULT - USER PERMISSION REQUIRED]",
            ocr_confidence=1.0,
            contains_sensitive_data=False,
        )

    @staticmethod
    def generate_synthetic_scenario(scenario: SyntheticScenario) -> ScreenContext:
        """
        Generates deterministic synthetic frames representing standard PRD scenarios.
        """
        now = datetime.now(timezone.utc)
        uid = uuid.uuid4().hex[:8]

        if scenario == SyntheticScenario.CODE_EDITOR_ERROR:
            # PRD UC-02: Persona 1 (VS Code runtime error)
            return ScreenContext(
                capture_id=f"cap-code-{uid}",
                timestamp=now,
                capture_mode=CaptureMode.ACTIVE_WINDOW,
                application_name="VS Code",
                window_title="calculator.py - Visual Studio Code",
                width=1920,
                height=1080,
                dpi_scale=1.0,
                bounding_box=BoundingBox(x_min=0, y_min=0, x_max=1920, y_max=1080),
                image_format="image/webp",
                image_base64=None,
                ocr_text=(
                    "def calculate_average(items):\n"
                    "    return sum(items) / len(items)\n\n"
                    "ZeroDivisionError: division by zero on line 2 in calculate_average"
                ),
                ocr_confidence=0.98,
                contains_sensitive_data=False,
            )

        elif scenario == SyntheticScenario.RESEARCH_PAPER_PDF:
            # PRD UC-03: Persona 2 (PDF reader research paper methodology)
            return ScreenContext(
                capture_id=f"cap-pdf-{uid}",
                timestamp=now,
                capture_mode=CaptureMode.REGION,
                application_name="Acrobat Reader",
                window_title="Deep_Residual_Learning.pdf - Adobe Acrobat Reader",
                width=1440,
                height=900,
                dpi_scale=1.25,
                bounding_box=BoundingBox(x_min=100, y_min=80, x_max=1340, y_max=850),
                image_format="image/webp",
                image_base64=None,
                ocr_text=(
                    "Section 3. Methodology: Deep Residual Learning Framework\n"
                    "Instead of hoping every few stacked layers directly fit a desired underlying mapping,\n"
                    "we explicitly let these layers fit a residual mapping. Formally, denoting H(x) as..."
                ),
                ocr_confidence=0.96,
                contains_sensitive_data=False,
            )

        elif scenario == SyntheticScenario.SPREADSHEET_ANALYSIS:
            # PRD UC-04: Tabular spreadsheet trends
            return ScreenContext(
                capture_id=f"cap-sheet-{uid}",
                timestamp=now,
                capture_mode=CaptureMode.ACTIVE_WINDOW,
                application_name="Microsoft Excel",
                window_title="Quarterly_Sales_2026.xlsx - Excel",
                width=1920,
                height=1080,
                dpi_scale=1.0,
                bounding_box=BoundingBox(x_min=0, y_min=0, x_max=1920, y_max=1080),
                image_format="image/webp",
                image_base64=None,
                ocr_text=(
                    "Region | Q1 Sales | Q2 Sales | Growth (%)\n"
                    "North  | $45,000  | $58,000  | +28.8%\n"
                    "South  | $32,000  | $29,000  | -9.3%\n"
                    "East   | $61,000  | $74,000  | +21.3%\n"
                    "West   | $50,000  | $63,000  | +26.0%"
                ),
                ocr_confidence=0.99,
                contains_sensitive_data=False,
            )

        elif scenario == SyntheticScenario.FILE_EXPLORER:
            # PRD UC-06 & UC-08: File Manager
            return ScreenContext(
                capture_id=f"cap-files-{uid}",
                timestamp=now,
                capture_mode=CaptureMode.ACTIVE_WINDOW,
                application_name="File Explorer",
                window_title="Downloads - File Explorer",
                width=1280,
                height=720,
                dpi_scale=1.0,
                image_format="image/webp",
                image_base64=None,
                ocr_text="Name: dataset_2026.csv | Date: Yesterday 4:04 PM | Type: CSV File | Size: 2.1 MB",
                ocr_confidence=0.95,
                contains_sensitive_data=False,
            )

        elif scenario == SyntheticScenario.REDACTED_PRIVACY:
            # PRD Section 19: Sensitive data detected
            return ScreenContext(
                capture_id=f"cap-redacted-{uid}",
                timestamp=now,
                capture_mode=CaptureMode.ACTIVE_WINDOW,
                application_name="Browser",
                window_title="Account Settings",
                width=1920,
                height=1080,
                dpi_scale=1.0,
                image_format="image/webp",
                image_base64=None,
                ocr_text="API_KEY = [REDACTED_SECRET] | User: admin@example.com",
                ocr_confidence=0.91,
                contains_sensitive_data=True,
            )

        raise ValueError(f"Unknown scenario: {scenario}")

    @staticmethod
    def create_custom_synthetic_frame(
        application_name: str,
        window_title: str,
        ocr_text: str,
        width: int = 1920,
        height: int = 1080,
        capture_mode: CaptureMode = CaptureMode.ACTIVE_WINDOW,
        ocr_confidence: float = 0.95,
        contains_sensitive_data: bool = False,
        bounding_box: Optional[BoundingBox] = None,
    ) -> ScreenContext:
        """
        Creates a custom synthetic frame with explicit attributes.
        """
        return ScreenContext(
            capture_id=f"cap-custom-{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now(timezone.utc),
            capture_mode=capture_mode,
            application_name=application_name,
            window_title=window_title,
            width=width,
            height=height,
            dpi_scale=1.0,
            bounding_box=bounding_box,
            image_format="image/webp",
            image_base64=None,
            ocr_text=ocr_text,
            ocr_confidence=ocr_confidence,
            contains_sensitive_data=contains_sensitive_data,
        )
