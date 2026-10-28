"""
Reasoning Schemas for AI Voice Co-Pilot:
- ReasoningRequest
- ReasoningResult
- ActionStep

Implements domain validation and safety constraints aligned with:
- PRD Section 16: Multimodal AI Requirements
- PRD Section 18: Human-in-the-Loop Safety & Risk Categorization (Category A, B, C, D)
- PRD Section 24: Risk Mitigation & Confidence-Aware Validations
- SDD Sections 4.3, 4.4, 5, 6: Agent Orchestrator & Action Planning
"""

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import (
    ContextType,
    ExecutionStatus,
    InputModality,
    RiskLevel,
)
from app.schemas.context import ContextItem, ScreenContext, SourceReference


# Regex for valid tool names: alphanumeric, underscores, hyphens
TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")


class ActionStep(BaseModel):
    """
    Individual step in an agentic workflow plan.
    """
    step_number: int = Field(
        ...,
        ge=1,
        description="Ordinal execution sequence index. Units: step sequence index (1-based)."
    )
    tool_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Registered tool name identifier (e.g. 'file_search', 'pdf_reader'). Units: tool name string."
    )
    tool_parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="JSON schema-compliant input arguments for the tool. Units: key-value dictionary."
    )
    step_description: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Human-readable explanation of the action to be performed (explainability). Units: text string."
    )
    risk_level: RiskLevel = Field(
        default=RiskLevel.CATEGORY_A_INFORMATIONAL,
        description="Risk level for this specific action step."
    )
    requires_approval: bool = Field(
        default=False,
        description="Explicit flag whether this step must pause for user confirmation."
    )

    @field_validator("tool_name", mode="before")
    @classmethod
    def validate_tool_name(cls, v: Any) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("tool_name must be a non-empty string.")
        v_stripped = v.strip()
        if len(v_stripped) > 100:
            raise ValueError("tool_name must not exceed 100 characters.")
        if not TOOL_NAME_PATTERN.match(v_stripped):
            raise ValueError(f"tool_name '{v_stripped}' contains invalid characters. Must be alphanumeric, underscores, or hyphens.")
        return v_stripped

    @field_validator("step_description", mode="before")
    @classmethod
    def validate_step_description(cls, v: Any) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("step_description must be a non-empty string.")
        v_stripped = v.strip()
        if len(v_stripped) > 500:
            raise ValueError("step_description must not exceed 500 characters.")
        return v_stripped

    @model_validator(mode="after")
    def validate_action_step_safety(self) -> "ActionStep":
        """
        PRD Section 18: Sensitive (Category C) and Destructive (Category D)
        actions must always require explicit confirmation.
        """
        if self.risk_level in (RiskLevel.CATEGORY_C_SENSITIVE, RiskLevel.CATEGORY_D_HIGH_RISK_DESTRUCTIVE):
            if not self.requires_approval:
                raise ValueError(
                    f"Action step with risk level '{self.risk_level.value}' must require approval (requires_approval=True)."
                )
        return self


class ReasoningRequest(BaseModel):
    """
    Request payload submitted to the Multimodal AI Reasoning Engine.
    """
    request_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique request identifier (UUIDv4). Units: identifier string."
    )
    session_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Active dialogue session identifier. Units: identifier string."
    )
    user_query: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="Transcribed user voice query or text prompt. Units: text string (1 to 4,000 characters)."
    )
    modality: InputModality = Field(
        default=InputModality.VOICE,
        description="Originating modality of user request (voice, text, multimodal)."
    )
    screen_context: Optional[ScreenContext] = Field(
        default=None,
        description="Visual snapshot and OCR data of the active screen/window when requested."
    )
    context_items: List[ContextItem] = Field(
        default_factory=list,
        max_length=50,
        description="Prioritized context items filtered by the Context Engine (max 50 items)."
    )
    conversation_history: List[Dict[str, str]] = Field(
        default_factory=list,
        max_length=30,
        description="Recent conversation turns formatted as [{'role': 'user'|'assistant', 'content': str}] (max 30 turns)."
    )
    available_tools: List[str] = Field(
        default_factory=list,
        description="List of permitted tool names available in this session for agentic planning."
    )
    allow_agentic_planning: bool = Field(
        default=True,
        description="Flag enabling multi-step tool planning vs single-turn direct response."
    )
    max_tokens: int = Field(
        default=1024,
        ge=64,
        le=8192,
        description="Maximum tokens allowed for LLM reasoning/generation. Units: tokens."
    )
    temperature: float = Field(
        default=0.2,
        ge=0.0,
        le=2.0,
        description="Sampling temperature for LLM response generation."
    )
    stream_response: bool = Field(
        default=False,
        description="Whether to stream response tokens progressively over WebSocket."
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC request creation timestamp. Units: UTC ISO 8601 datetime."
    )

    @field_validator("request_id", "session_id", mode="before")
    @classmethod
    def validate_identifier(cls, v: Any) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Identifier must be a non-empty string.")
        v_stripped = v.strip()
        if len(v_stripped) > 64:
            raise ValueError("Identifier length must not exceed 64 characters.")
        return v_stripped

    @field_validator("user_query", mode="before")
    @classmethod
    def validate_user_query(cls, v: Any) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("user_query must be a non-empty string.")
        v_stripped = v.strip()
        if len(v_stripped) > 4000:
            raise ValueError("user_query length must not exceed 4000 characters.")
        return v_stripped

    @field_validator("conversation_history")
    @classmethod
    def validate_conversation_history(cls, v: List[Dict[str, str]]) -> List[Dict[str, str]]:
        if len(v) > 30:
            raise ValueError("conversation_history must not exceed 30 turns.")
        allowed_roles = {"user", "assistant", "system"}
        for idx, turn in enumerate(v):
            if not isinstance(turn, dict):
                raise ValueError(f"Conversation turn at index {idx} must be a dictionary.")
            if "role" not in turn or "content" not in turn:
                raise ValueError(f"Conversation turn at index {idx} must contain 'role' and 'content' keys.")
            if turn["role"] not in allowed_roles:
                raise ValueError(
                    f"Conversation turn at index {idx} has invalid role '{turn['role']}'. Allowed: {sorted(allowed_roles)}."
                )
            if not isinstance(turn["content"], str) or not turn["content"].strip():
                raise ValueError(f"Conversation turn at index {idx} has empty or non-string 'content'.")
        return v

    @field_validator("available_tools")
    @classmethod
    def validate_available_tools(cls, v: List[str]) -> List[str]:
        cleaned_tools: List[str] = []
        for idx, tool in enumerate(v):
            if not isinstance(tool, str) or not tool.strip():
                raise ValueError(f"Tool at index {idx} must be a non-empty string.")
            t_stripped = tool.strip()
            if not TOOL_NAME_PATTERN.match(t_stripped):
                raise ValueError(f"Tool '{t_stripped}' contains invalid characters. Allowed: alphanumeric, underscores, hyphens.")
            cleaned_tools.append(t_stripped)
        return cleaned_tools

    @model_validator(mode="after")
    def validate_request_modality_and_context(self) -> "ReasoningRequest":
        """
        PRD Section 14 & 16: If modality is MULTIMODAL, visual context
        (screen_context or visual context_items) must be present.
        """
        if self.modality == InputModality.MULTIMODAL:
            has_screen = self.screen_context is not None
            has_visual_item = any(
                item.context_type in (ContextType.SCREEN_OCR, ContextType.VISUAL_SUMMARY)
                for item in self.context_items
            )
            if not has_screen and not has_visual_item:
                raise ValueError(
                    "Multimodal request requires visual context: either screen_context "
                    "or visual context_items (e.g. screen_ocr, visual_summary) must be provided."
                )
        return self


class ReasoningResult(BaseModel):
    """
    Output model produced by the Multimodal AI Layer and Agent Orchestrator.
    """
    response_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique response identifier (UUIDv4). Units: identifier string."
    )
    request_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Correlating request identifier (UUIDv4). Units: identifier string."
    )
    session_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Active dialogue session identifier. Units: identifier string."
    )
    user_intent: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Detected intent category. Units: intent identifier string."
    )
    response_text: str = Field(
        ...,
        description="Natural language response text intended for voice playback (TTS) and UI display."
    )
    reasoning_summary: Optional[str] = Field(
        default=None,
        description="High-level rationale explaining derived answer or action plan."
    )
    tool_call_required: bool = Field(
        default=False,
        description="Boolean indicating whether tool invocation is required."
    )
    action_plan: List[ActionStep] = Field(
        default_factory=list,
        description="Decomposed multi-step tool execution plan if tool_call_required is True."
    )
    risk_level: RiskLevel = Field(
        default=RiskLevel.CATEGORY_A_INFORMATIONAL,
        description="Overall risk level classification of the action/response."
    )
    requires_user_approval: bool = Field(
        default=False,
        description="Boolean indicating whether explicit user approval is required."
    )
    approval_prompt: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Concise confirmation query spoken and displayed to the user."
    )
    sources_used: List[SourceReference] = Field(
        default_factory=list,
        description="List of contextual sources and citations referenced during reasoning."
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence estimate of the intent detection and response accuracy."
    )
    processing_time_ms: float = Field(
        ...,
        ge=0.0,
        description="Total round-trip reasoning and context assembly latency in ms."
    )
    status: ExecutionStatus = Field(
        default=ExecutionStatus.SUCCESS,
        description="Execution status outcome."
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC response completion timestamp."
    )

    @field_validator("response_id", "request_id", "session_id", mode="before")
    @classmethod
    def validate_identifier(cls, v: Any) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Identifier must be a non-empty string.")
        v_stripped = v.strip()
        if len(v_stripped) > 64:
            raise ValueError("Identifier length must not exceed 64 characters.")
        return v_stripped

    @field_validator("user_intent", "response_text", mode="before")
    @classmethod
    def validate_text_fields(cls, v: Any) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Field must be a non-empty string.")
        return v.strip()

    @field_validator("approval_prompt", mode="before")
    @classmethod
    def validate_approval_prompt(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, str):
            v_stripped = v.strip()
            if not v_stripped:
                return None
            if len(v_stripped) > 500:
                raise ValueError("approval_prompt length must not exceed 500 characters.")
            return v_stripped
        raise ValueError("approval_prompt must be a string or None.")

    @model_validator(mode="after")
    def validate_reasoning_result_integrity(self) -> "ReasoningResult":
        """
        Cross-field business integrity rules derived from PRD Sec 18, SDD Sec 6,
        and Tech Arch Sec 6-7.
        """
        # 1. Tool Call and Action Plan Consistency
        if self.tool_call_required and not self.action_plan:
            raise ValueError(
                "action_plan must contain at least one ActionStep when tool_call_required is True."
            )
        if not self.tool_call_required and self.action_plan:
            raise ValueError(
                "tool_call_required must be True when action_plan contains ActionSteps."
            )

        # 2. Sequential ActionStep Numbering (1-based contiguous indices)
        if self.action_plan:
            for idx, step in enumerate(self.action_plan, start=1):
                if step.step_number != idx:
                    raise ValueError(
                        f"ActionStep sequence numbers must be contiguous and 1-based (expected {idx}, got {step.step_number})."
                    )

        # 3. Action Step Risk Propagation (Overall risk cannot be lower than the highest step risk)
        if self.action_plan:
            risk_ranks = {
                RiskLevel.CATEGORY_A_INFORMATIONAL: 1,
                RiskLevel.CATEGORY_B_LOW_RISK: 2,
                RiskLevel.CATEGORY_C_SENSITIVE: 3,
                RiskLevel.CATEGORY_D_HIGH_RISK_DESTRUCTIVE: 4,
            }
            highest_step_risk = max(self.action_plan, key=lambda s: risk_ranks[s.risk_level]).risk_level
            if risk_ranks[self.risk_level] < risk_ranks[highest_step_risk]:
                raise ValueError(
                    f"Overall risk_level '{self.risk_level.value}' cannot be lower than the highest action step risk '{highest_step_risk.value}'."
                )

        # 4. Human-in-the-Loop Safety Gate & Approval Alignment (PRD Section 18)
        if self.risk_level in (RiskLevel.CATEGORY_C_SENSITIVE, RiskLevel.CATEGORY_D_HIGH_RISK_DESTRUCTIVE):
            if not self.requires_user_approval:
                raise ValueError(
                    f"requires_user_approval must be True for sensitive/destructive operations ({self.risk_level.value})."
                )
            if not self.approval_prompt:
                raise ValueError(
                    f"approval_prompt is required for sensitive/destructive operations ({self.risk_level.value})."
                )
        elif self.risk_level == RiskLevel.CATEGORY_A_INFORMATIONAL:
            if self.requires_user_approval:
                raise ValueError(
                    "Informational (Category A) responses must not require user approval (requires_user_approval must be False)."
                )
            if self.approval_prompt is not None:
                raise ValueError(
                    "approval_prompt must not be set for Category A informational responses."
                )

        # 5. Execution Status Alignment
        if self.status == ExecutionStatus.NEEDS_APPROVAL and not self.requires_user_approval:
            raise ValueError("ExecutionStatus.NEEDS_APPROVAL requires requires_user_approval=True.")

        return self
