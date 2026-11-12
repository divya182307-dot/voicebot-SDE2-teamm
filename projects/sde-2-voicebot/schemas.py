"""
schemas.py — Shared Pydantic schemas (Week 1 base).
All other modules import from here; do NOT redefine these elsewhere.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RiskLevel(str, Enum):
    """Maps to the PRD safety tiers A-D."""
    INFORMATIONAL = "informational"   # Category A
    LOW = "low"                       # Category B
    SENSITIVE = "sensitive"           # Category C
    HIGH = "high"                     # Category D / destructive


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class PermissionScope(str, Enum):
    """Coarse permission scopes that tools declare and users grant."""
    READ_FILES = "read_files"
    SEARCH = "search"
    COMPUTE = "compute"
    # Intentionally no WRITE_FILES, NETWORK, SYSTEM for the MVP mock layer


# ---------------------------------------------------------------------------
# Tool-related schemas
# ---------------------------------------------------------------------------

class ToolArgSpec(BaseModel):
    """Declares one argument a tool accepts."""
    name: str
    type: str                    # "str" | "int" | "float" | "bool" | "list"
    required: bool = True
    description: str = ""


class ToolDefinition(BaseModel):
    """Registry entry for one allow-listed tool."""
    name: str
    description: str
    risk_level: RiskLevel
    required_scopes: List[PermissionScope] = Field(default_factory=list)
    args: List[ToolArgSpec] = Field(default_factory=list)
    idempotent: bool = False     # True → safe to retry on transient failure


class ToolCall(BaseModel):
    """A concrete invocation of a tool with supplied arguments."""
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Plan schemas
# ---------------------------------------------------------------------------

class PlanStep(BaseModel):
    """One step in an agentic plan."""
    step_id: str
    tool_call: ToolCall
    depends_on: List[str] = Field(default_factory=list)   # step_ids this waits for


class Plan(BaseModel):
    """A complete agentic plan produced by the agent orchestrator."""
    plan_id: str
    session_id: str
    steps: List[PlanStep]
    granted_scopes: List[PermissionScope] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

class ValidationResult(BaseModel):
    valid: bool
    errors: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Approval schemas
# ---------------------------------------------------------------------------

class ApprovalRequest(BaseModel):
    """Created when a plan needs human sign-off before execution."""
    approval_id: str
    plan_id: str
    risk_level: RiskLevel
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    reason: str = ""             # Human-readable description shown to user
    decided_at: Optional[datetime] = None
    decided_by: Optional[str] = None


# ---------------------------------------------------------------------------
# Execution schemas
# ---------------------------------------------------------------------------

class StepResult(BaseModel):
    step_id: str
    status: ExecutionStatus
    output: Any = None
    error: Optional[str] = None
    attempts: int = 0


class ExecutionRecord(BaseModel):
    """Audit record produced for every plan execution attempt."""
    execution_id: str
    plan_id: str
    approval_id: Optional[str] = None
    status: ExecutionStatus
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    step_results: List[StepResult] = Field(default_factory=list)
    audit_note: str = ""         # e.g. "rejected – no execution performed"

