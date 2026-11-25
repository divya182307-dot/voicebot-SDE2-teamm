"""
Data models for Observations, Grounded Answers, and Workflow Proposals.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.common import RiskLevel, SourceType
from app.schemas.context import SourceReference
from app.schemas.reasoning import ActionStep


class ConsentStatus(str, Enum):
    """Lifecycle states for user visual/audio capture consent."""
    OPTED_OUT = "opted_out"
    CONSENT_ACTIVE = "consent_active"
    CONSENT_WITHDRAWN = "consent_withdrawn"


class Observation(BaseModel):
    """
    A trustworthy, timestamped, source-linked factual observation derived from
    screen frames, document excerpts, audio utterances, or system context.
    """
    observation_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique observation identifier (e.g. obs-12345)."
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC ISO 8601 timestamp when observation was formed."
    )
    source: SourceReference = Field(
        ...,
        description="Verifiable source reference linking observation to window, file, page, or coordinates."
    )
    source_type: SourceType = Field(
        ...,
        description="Primary provenance modality (screen, document, audio_voice, terminal, browser)."
    )
    content: str = Field(
        ...,
        min_length=1,
        max_length=50000,
        description="Raw or normalized text, code, or OCR snippet captured."
    )
    summary: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Concise factual observation summary."
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Grounding confidence score between 0.0 and 1.0."
    )
    is_stale: bool = Field(
        default=False,
        description="True if observation exceeds freshness TTL or has been superseded."
    )
    is_duplicate: bool = Field(
        default=False,
        description="True if observation content matches a recent frame."
    )
    has_evidence: bool = Field(
        default=True,
        description="True if verifiable empirical evidence is present in the source."
    )
    content_hash: str = Field(
        default="",
        description="SHA-256 content hash used for deduplication."
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional auxiliary attributes (e.g. bounding_box, window_rect)."
    )


class ObservationBatch(BaseModel):
    """Aggregated batch of observations with freshness and duplicate metrics."""
    batch_id: str = Field(..., description="Unique batch identifier.")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Batch creation timestamp."
    )
    observations: List[Observation] = Field(default_factory=list)
    total_count: int = Field(default=0)
    fresh_count: int = Field(default=0)
    stale_count: int = Field(default=0)
    duplicate_count: int = Field(default=0)


class WorkflowProposal(BaseModel):
    """Actionable workflow proposal handed off to the workflow orchestration module."""
    proposal_id: str = Field(..., description="Unique proposal identifier.")
    task_intent: str = Field(..., description="User intent triggering the workflow.")
    action_steps: List[ActionStep] = Field(
        default_factory=list,
        description="Sequential 1-based action step sequence."
    )
    risk_level: RiskLevel = Field(
        default=RiskLevel.CATEGORY_A_INFORMATIONAL,
        description="Assigned safety risk tier."
    )
    requires_approval: bool = Field(
        default=False,
        description="True if execution requires explicit human authorization."
    )
    approval_prompt: Optional[str] = Field(
        default=None,
        description="Verbal/visual confirmation prompt displayed to user."
    )
    target_module: str = Field(
        default="workflow",
        description="Target downstream executor (workflow, tool_runner, orchestrator)."
    )


class GroundedAnswer(BaseModel):
    """
    Final answer produced by the engine, grounded in source-linked observations,
    or an honest 'no evidence' reply when observations do not support the query.
    """
    query: str = Field(..., description="Original user utterance or query.")
    answer_text: str = Field(..., description="Grounded response or honest 'no evidence' message.")
    has_evidence: bool = Field(
        ...,
        description="True if grounded in verified observations; False if no supporting evidence."
    )
    evidence_observations: List[Observation] = Field(
        default_factory=list,
        description="Observations used as ground-truth evidence."
    )
    sources_cited: List[SourceReference] = Field(
        default_factory=list,
        description="Direct citations attributing the answer."
    )
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score in the answer."
    )
    workflow_proposal: Optional[WorkflowProposal] = Field(
        default=None,
        description="Optional workflow proposal handed to workflow module if actions required."
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC generation timestamp."
    )

