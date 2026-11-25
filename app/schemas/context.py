"""
Context Schemas for AI Voice Co-Pilot:
- SourceReference
- ScreenContext
- ContextItem
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from app.schemas.common import (
    BoundingBox,
    CaptureMode,
    ContextType,
    SourceType,
)


class SourceReference(BaseModel):
    """
    Provenance tracking and source attribution model.
    """
    source_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique identifier for the source item (e.g. UUIDv4). Units: identifier string."
    )
    source_type: SourceType = Field(
        ...,
        description="Origin modality or medium (screen, window, document, voice, terminal, etc.)."
    )
    application_name: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Name of the application hosting the source content (e.g. 'VS Code', 'Chrome'). Units: application identifier name."
    )
    window_title: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Title of the active OS window or document tab. Units: text string."
    )
    document_uri: Optional[str] = Field(
        default=None,
        max_length=2048,
        description="URI or local absolute file path to the source document or resource. Units: RFC 3986 URI / file path string."
    )
    page_number: Optional[int] = Field(
        default=None,
        ge=1,
        description="1-based page index if the source is a paginated document (PDF, presentation). Units: pages (count >= 1)."
    )
    line_number: Optional[int] = Field(
        default=None,
        ge=1,
        description="1-based line number if the source is code or text file. Units: line index (count >= 1)."
    )
    bounding_box: Optional[BoundingBox] = Field(
        default=None,
        description="Spatial coordinates on screen or document page where source element is located. Units: pixels or normalized coordinates."
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the source reference was created/recorded. Units: UTC ISO 8601 datetime."
    )


class ScreenContext(BaseModel):
    """
    Screen and visual context captured from the user's workspace.
    """
    capture_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique capture event identifier (UUIDv4). Units: identifier string."
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of capture. Units: UTC ISO 8601 datetime."
    )
    capture_mode: CaptureMode = Field(
        default=CaptureMode.ACTIVE_WINDOW,
        description="Capture boundary scope (fullscreen, active_window, region, selection)."
    )
    application_name: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Application corresponding to captured screen/window. Units: application identifier."
    )
    window_title: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Window title corresponding to captured area. Units: text string."
    )
    width: int = Field(
        ...,
        ge=1,
        le=16384,
        description="Width of captured frame or region. Units: pixels (px). Constraints: 1 <= width <= 16384."
    )
    height: int = Field(
        ...,
        ge=1,
        le=16384,
        description="Height of captured frame or region. Units: pixels (px). Constraints: 1 <= height <= 16384."
    )
    dpi_scale: float = Field(
        default=1.0,
        ge=0.5,
        le=5.0,
        description="Display DPI scale factor. Units: ratio factor (e.g. 1.0, 1.25, 2.0). Constraints: 0.5 <= dpi_scale <= 5.0."
    )
    bounding_box: Optional[BoundingBox] = Field(
        default=None,
        description="Absolute screen coordinate bounding box for region/window capture. Units: pixels (px)."
    )
    image_format: str = Field(
        default="image/webp",
        pattern=r"^(image/png|image/jpeg|image/webp)$",
        description="MIME type format of encoded visual payload. Units: MIME type. Constraints: image/png, image/jpeg, or image/webp."
    )
    image_base64: Optional[str] = Field(
        default=None,
        max_length=10000000,
        description="Base64-encoded compressed image bytes (if raw visual reasoning is required). Units: Base64 string (max ~10MB)."
    )
    ocr_text: Optional[str] = Field(
        default=None,
        max_length=100000,
        description="Text extracted via OCR from the captured area (FR-VISION-003). Units: text characters (max 100,000)."
    )
    ocr_confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Mean confidence level of OCR extraction. Units: normalized confidence score [0.0, 1.0]."
    )
    contains_sensitive_data: bool = Field(
        default=False,
        description="Flag indicating whether sensitive/PII data was detected or masked (FR-VISION-006, PRD Section 19)."
    )


class ContextItem(BaseModel):
    """
    Atomic contextual data item collected and curated by the Context Engine.
    """
    item_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique identifier for the context item (UUIDv4). Units: identifier string."
    )
    context_type: ContextType = Field(
        ...,
        description="Classification category of the context item."
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Concise descriptive title/header for the context snippet. Units: text string."
    )
    content: str = Field(
        ...,
        min_length=1,
        max_length=250000,
        description="Raw or sanitized text payload of the context. Units: text string (1 to 250,000 characters)."
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured key-value metadata (e.g. process_id, file_extension, error_code). Units: key-value dictionary."
    )
    source: Optional[SourceReference] = Field(
        default=None,
        description="Attribution and provenance linking this context item back to its origin."
    )
    relevance_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Relevance weight calculated by Context Engine to filter noise. Units: normalized score [0.0, 1.0]."
    )
    token_count: Optional[int] = Field(
        default=None,
        ge=0,
        description="Estimated or measured token size of content for context window budgeting. Units: tokens (count >= 0)."
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC creation or ingestion timestamp. Units: UTC ISO 8601 datetime."
    )
