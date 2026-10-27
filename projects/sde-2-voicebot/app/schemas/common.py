"""
Common data types, enums, and utility models shared across schemas.
Aligned with PRD Section 18 (Human-in-the-Loop Safety) and SDD Section 4-6.
"""

from enum import Enum
from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """
    Risk classification defined in PRD Section 18 and SDD Safety & Approval Layer.
    """
    CATEGORY_A_INFORMATIONAL = "category_a_informational"
    CATEGORY_B_LOW_RISK = "category_b_low_risk"
    CATEGORY_C_SENSITIVE = "category_c_sensitive"
    CATEGORY_D_HIGH_RISK_DESTRUCTIVE = "category_d_high_risk_destructive"


class SourceType(str, Enum):
    """
    Medium / source type for context provenance.
    """
    SCREEN = "screen"
    ACTIVE_WINDOW = "active_window"
    DOCUMENT = "document"
    AUDIO_VOICE = "audio_voice"
    TERMINAL = "terminal"
    APPLICATION_STATE = "application_state"
    BROWSER = "browser"
    RETRIEVED_KNOWLEDGE = "retrieved_knowledge"
    CONVERSATION_HISTORY = "conversation_history"


class ContextType(str, Enum):
    """
    Categorization of context items ingested by the Context Engine.
    """
    USER_QUERY = "user_query"
    SCREEN_OCR = "screen_ocr"
    VISUAL_SUMMARY = "visual_summary"
    APPLICATION_METADATA = "application_metadata"
    DOCUMENT_EXCERPT = "document_excerpt"
    TERMINAL_OUTPUT = "terminal_output"
    CODE_SNIPPET = "code_snippet"
    DIALOGUE_HISTORY = "dialogue_history"
    RETRIEVED_DOC = "retrieved_doc"


class InputModality(str, Enum):
    """
    Primary modality of the incoming user request.
    """
    VOICE = "voice"
    TEXT = "text"
    MULTIMODAL = "multimodal"


class CaptureMode(str, Enum):
    """
    Screen capture scope according to FR-VISION-002.
    """
    FULLSCREEN = "fullscreen"
    ACTIVE_WINDOW = "active_window"
    REGION = "region"
    SELECTION = "selection"


class ExecutionStatus(str, Enum):
    """
    Reasoning and execution status outcome.
    """
    SUCCESS = "success"
    REQUIRES_CLARIFICATION = "requires_clarification"
    NEEDS_APPROVAL = "needs_approval"
    EXECUTION_IN_PROGRESS = "execution_in_progress"
    FAILED = "failed"


class BoundingBox(BaseModel):
    """
    2D coordinate box for screen regions or OCR bounding areas.
    """
    x_min: float = Field(
        ...,
        ge=0.0,
        description="Minimum X coordinate. Units: pixels (px) or normalized ratio [0.0, 1.0]."
    )
    y_min: float = Field(
        ...,
        ge=0.0,
        description="Minimum Y coordinate. Units: pixels (px) or normalized ratio [0.0, 1.0]."
    )
    x_max: float = Field(
        ...,
        ge=0.0,
        description="Maximum X coordinate. Must be >= x_min. Units: pixels (px) or normalized ratio."
    )
    y_max: float = Field(
        ...,
        ge=0.0,
        description="Maximum Y coordinate. Must be >= y_min. Units: pixels (px) or normalized ratio."
    )
    is_normalized: bool = Field(
        default=False,
        description="True if coordinates are normalized [0.0, 1.0], False if absolute pixel units."
    )
