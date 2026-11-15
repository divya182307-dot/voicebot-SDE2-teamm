"""
OCR and Vision Adapter Interface.
Complies with:
- PRD Section 14: Screen & Visual Understanding (FR-VISION-003, FR-VISION-004, FR-VISION-006).
- PRD Section 19: Privacy Requirements (sensitive data / PII detection & masking).
"""

from abc import ABC, abstractmethod
import base64
import re
import time
from typing import Any, List, Optional, Tuple, Union

from pydantic import BaseModel, Field

from app.schemas.common import BoundingBox
from app.schemas.context import ScreenContext


class OCRResult(BaseModel):
    """
    Structured outcome of optical character recognition extraction (FR-VISION-003).
    """
    text: str = Field(default="", description="Extracted optical character recognition text.")
    confidence: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="Confidence score of text extraction [0.0, 1.0]."
    )
    word_count: int = Field(default=0, ge=0, description="Total number of words extracted.")
    line_count: int = Field(default=0, ge=0, description="Total number of lines.")
    language: Optional[str] = Field(default="en", description="Detected or primary language code.")
    bounding_boxes: List[BoundingBox] = Field(
        default_factory=list,
        description="Spatial coordinates for detected text blocks or words."
    )
    contains_sensitive_data: bool = Field(
        default=False,
        description="Flag indicating if credentials, API keys, or PII were detected."
    )
    detected_pii_categories: List[str] = Field(
        default_factory=list,
        description="Categories of sensitive data detected (e.g. ['api_key', 'email'])."
    )
    processing_time_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Elapsed extraction duration in milliseconds."
    )


class VisionAnalysisResult(BaseModel):
    """
    Holistic multimodal visual and layout understanding result (FR-VISION-004).
    """
    ocr: OCRResult = Field(..., description="Embedded OCR extraction result.")
    visual_summary: str = Field(
        ...,
        description="Semantic description of screen layout, widgets, and visible content."
    )
    detected_elements: List[str] = Field(
        default_factory=list,
        description="Classified UI widgets and regions (e.g. ['code_editor', 'stack_trace'])."
    )
    application_context: Optional[str] = Field(
        default=None,
        description="Host application identified from visual landmarks or metadata."
    )
    window_title: Optional[str] = Field(
        default=None,
        description="Window title recognized from visual header or context."
    )
    contains_sensitive_data: bool = Field(
        default=False,
        description="Overall sensitive data flag."
    )
    processing_time_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Total visual analysis processing time in milliseconds."
    )


class RuleBasedSensitiveDataScanner:
    """
    High-performance pattern-based scanner for secrets, credentials, and PII (PRD Section 19).
    """

    PATTERNS = {
        "api_key": re.compile(
            r"(?i)(?:api_key|secret|token|bearer|access_token|private_key|auth_token)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-\.]{8,}",
            re.IGNORECASE,
        ),
        "explicit_redaction_marker": re.compile(
            r"\[REDACTED_SECRET\]|\[REDACTED_PII\]",
            re.IGNORECASE,
        ),
        "email_address": re.compile(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
        ),
        "credit_card": re.compile(
            r"\b(?:\d{4}[-\s]?){3}\d{4}\b"
        ),
        "password_assignment": re.compile(
            r"(?i)(?:password|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\",]{4,}",
            re.IGNORECASE,
        ),
    }

    @classmethod
    def scan(cls, text: Optional[str]) -> Tuple[bool, List[str]]:
        """
        Scans text for sensitive patterns.
        
        Returns:
            Tuple of (contains_sensitive_data: bool, detected_categories: List[str])
        """
        if not text:
            return False, []

        detected = []
        for category, pattern in cls.PATTERNS.items():
            if pattern.search(text):
                detected.append(category)

        return len(detected) > 0, detected

    @classmethod
    def redact(cls, text: str) -> str:
        """
        Masks detected secrets with safe placeholders.
        """
        redacted = text
        for category, pattern in cls.PATTERNS.items():
            if category == "explicit_redaction_marker":
                continue
            redacted = pattern.sub(f"[REDACTED_{category.upper()}]", redacted)
        return redacted


class BaseVisionAdapter(ABC):
    """
    Abstract interface for OCR and visual understanding adapters (FR-VISION-003, FR-VISION-004).
    Enables swapping between deterministic mock vision, cloud vision APIs, or local OCR engines.
    """

    @abstractmethod
    def extract_text(self, image_input: Union[bytes, str, ScreenContext]) -> OCRResult:
        """
        Extracts textual content, confidence scores, and sensitive flags from image input.
        
        Args:
            image_input: Raw image bytes, base64-encoded image string, or a ScreenContext.
        """
        pass

    @abstractmethod
    def analyze_visuals(self, image_input: Union[bytes, str, ScreenContext]) -> VisionAnalysisResult:
        """
        Performs comprehensive visual understanding (OCR + visual summary + UI element classification).
        """
        pass

    @abstractmethod
    def process_screen_context(self, context: ScreenContext) -> ScreenContext:
        """
        Enriches an existing ScreenContext with OCR text, confidence, and privacy flags.
        """
        pass

    def is_available(self) -> bool:
        """
        Returns True if the vision adapter's backend engine is initialized and available.
        """
        return True


class DeterministicVisionAdapter(BaseVisionAdapter):
    """
    Deterministic Vision & OCR Adapter for high-speed testing and reproducible environments.
    
    Guarantees:
    - 100% Deterministic: Identical input always yields identical OCR and visual analysis.
    - Privacy Enforcement: Scans extracted text with RuleBasedSensitiveDataScanner for Section 19 compliance.
    - Schema Compliant: Returns fully validated OCRResult, VisionAnalysisResult, and ScreenContext instances.
    """

    def __init__(self, scanner: Optional[RuleBasedSensitiveDataScanner] = None):
        self._scanner = scanner or RuleBasedSensitiveDataScanner()

    def _resolve_raw_text(self, image_input: Union[bytes, str, ScreenContext]) -> Tuple[str, Optional[str], Optional[str], float]:
        """
        Resolves input into text, application name, window title, and base confidence.
        """
        if isinstance(image_input, ScreenContext):
            text = image_input.ocr_text or ""
            app = image_input.application_name
            title = image_input.window_title
            conf = image_input.ocr_confidence or 0.95
            return text, app, title, conf

        if isinstance(image_input, bytes):
            # Check if bytes contain plain ASCII/UTF-8 text or simulated OCR payload
            try:
                decoded = image_input.decode("utf-8")
                return decoded, None, None, 0.95
            except UnicodeDecodeError:
                return f"[Binary image payload: {len(image_input)} bytes]", None, None, 0.92

        if isinstance(image_input, str):
            # If string is base64, attempt decode
            if image_input.startswith("data:image") or len(image_input) > 200:
                try:
                    payload = image_input.split(",")[-1]
                    decoded_bytes = base64.b64decode(payload, validate=False)
                    return f"[Base64 visual image: {len(decoded_bytes)} bytes]", None, None, 0.94
                except Exception:
                    pass
            return image_input, None, None, 0.95

        return "", None, None, 0.0

    def extract_text(self, image_input: Union[bytes, str, ScreenContext]) -> OCRResult:
        """
        Extracts optical text with confidence scoring and sensitive data detection.
        """
        start = time.perf_counter()
        text, _, _, confidence = self._resolve_raw_text(image_input)
        
        words = text.split()
        lines = [ln for ln in text.splitlines() if ln.strip()]

        has_sensitive, pii_categories = self._scanner.scan(text)

        elapsed_ms = (time.perf_counter() - start) * 1000.0

        return OCRResult(
            text=text,
            confidence=confidence,
            word_count=len(words),
            line_count=len(lines),
            language="en",
            bounding_boxes=[],
            contains_sensitive_data=has_sensitive,
            detected_pii_categories=pii_categories,
            processing_time_ms=round(elapsed_ms, 3),
        )

    def analyze_visuals(self, image_input: Union[bytes, str, ScreenContext]) -> VisionAnalysisResult:
        """
        Generates semantic UI summary and classifies interface elements.
        """
        start = time.perf_counter()
        ocr_res = self.extract_text(image_input)
        _, app_name, win_title, _ = self._resolve_raw_text(image_input)

        text_lower = ocr_res.text.lower()
        elements: List[str] = []

        if "zerodivisionerror" in text_lower or "traceback" in text_lower or "error" in text_lower:
            elements.extend(["code_editor", "runtime_error_dialog", "stack_trace"])
            summary = f"Code editor ({app_name or 'IDE'}) displaying an unhandled exception and traceback."
        elif "sales" in text_lower or "quarterly" in text_lower or "growth" in text_lower:
            elements.extend(["spreadsheet", "data_grid", "financial_metrics"])
            summary = f"Spreadsheet application ({app_name or 'Excel'}) with tabular sales performance metrics."
        elif "methodology" in text_lower or "framework" in text_lower or "deep residual" in text_lower:
            elements.extend(["document_viewer", "pdf_reader", "academic_paper"])
            summary = f"PDF viewer ({app_name or 'Reader'}) displaying research methodology."
        elif "dataset" in text_lower or "file" in text_lower or "downloads" in text_lower:
            elements.extend(["file_browser", "directory_listing", "file_metadata"])
            summary = f"File manager ({app_name or 'Explorer'}) displaying directory items."
        elif ocr_res.contains_sensitive_data:
            elements.extend(["web_browser", "account_settings", "sensitive_fields"])
            summary = "Browser window containing sensitive authentication credentials and user profile."
        else:
            elements.append("general_desktop_window")
            summary = f"Active window '{win_title or 'Application'}' with visible text."

        elapsed_ms = (time.perf_counter() - start) * 1000.0

        return VisionAnalysisResult(
            ocr=ocr_res,
            visual_summary=summary,
            detected_elements=elements,
            application_context=app_name,
            window_title=win_title,
            contains_sensitive_data=ocr_res.contains_sensitive_data,
            processing_time_ms=round(elapsed_ms, 3),
        )

    def process_screen_context(self, context: ScreenContext) -> ScreenContext:
        """
        Enriches ScreenContext with OCR extraction, confidence, and privacy flags.
        """
        analysis = self.analyze_visuals(context)
        context.ocr_text = analysis.ocr.text
        context.ocr_confidence = analysis.ocr.confidence
        context.contains_sensitive_data = analysis.contains_sensitive_data
        return context

