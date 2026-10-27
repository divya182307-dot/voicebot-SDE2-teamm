"""
Agentic Workflow Schemas for Academiaai AI Voicebot.
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M

Day 1-2 Deliverable:
Defines WorkflowPlan, WorkflowStep, ToolSpec, ApprovalRequest, and WorkflowResult schemas,
along with RiskLevel and WorkflowState enums per PRD specifications.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4
from pydantic import BaseModel, Field, field_validator, model_validator


class WorkflowState(str, Enum):
    """
    Workflow execution lifecycle states as specified in PRD Section 8.
    """
    DRAFT = "draft"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RiskLevel(str, Enum):
    """
    Risk classification per PRD Section 18:
    Category A - Informational (no confirmation normally required)
    Category B - Low-Risk Interaction (execute according to policy)
    Category C - Sensitive (user confirmation required)
    Category D - High-Risk / Destructive (explicit confirmation strictly required)
    """
    INFORMATIONAL = "informational"
    LOW_RISK = "low_risk"
    SENSITIVE = "sensitive"
    DESTRUCTIVE = "destructive"


class ApprovalStatus(str, Enum):
    """
    State of an approval request.
    """
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ToolFailureBehavior(str, Enum):
    """
    Behavior when a tool execution fails.
    """
    FAIL_WORKFLOW = "fail_workflow"
    RETRY = "retry"
    IGNORE_AND_CONTINUE = "ignore_and_continue"


class ToolSpec(BaseModel):
    """
    Specification for allow-listed tools in the agentic workflow.
    Defined in PRD Section 17.
    """
    name: str = Field(..., description="Unique tool identifier name")
    purpose: str = Field(..., description="Clear human-readable description of what the tool does")
    input_schema: Dict[str, Any] = Field(default_factory=dict, description="JSON schema describing expected arguments")
    output_schema: Dict[str, Any] = Field(default_factory=dict, description="JSON schema describing returned output")
    permission_requirements: List[str] = Field(default_factory=list, description="List of permissions required to execute")
    risk_level: RiskLevel = Field(default=RiskLevel.INFORMATIONAL, description="Tool safety risk classification")
    failure_behavior: ToolFailureBehavior = Field(default=ToolFailureBehavior.FAIL_WORKFLOW, description="Default action on failure")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        name = v.strip()
        if not name:
            raise ValueError("Tool name cannot be empty")
        return name


class StepStatus(str, Enum):
    """
    Individual step execution status.
    """
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class WorkflowStep(BaseModel):
    """
    Individual executable step within a WorkflowPlan.
    """
    step_id: str = Field(default_factory=lambda: str(uuid4()), description="Unique ID for the step")
    tool_name: str = Field(..., description="Name of the tool to execute")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Input arguments passed to the tool")
    description: str = Field(..., description="Human-readable description of this step")
    risk_level: RiskLevel = Field(default=RiskLevel.INFORMATIONAL, description="Risk level associated with this step")
    requires_approval: bool = Field(default=False, description="Whether explicit user confirmation is needed")
    depends_on: List[str] = Field(default_factory=list, description="List of step_ids that must complete before this step")
    status: StepStatus = Field(default=StepStatus.PENDING, description="Current status of the step")
    result: Optional[Any] = Field(default=None, description="Result output if completed")
    error_message: Optional[str] = Field(default=None, description="Error message if step failed")

    @model_validator(mode="after")
    def enforce_consequential_approval_rule(self) -> "WorkflowStep":
        """
        PRD Rule: Consequential (sensitive/destructive) actions must default to requiring approval.
        """
        if self.risk_level in (RiskLevel.SENSITIVE, RiskLevel.DESTRUCTIVE):
            self.requires_approval = True
        return self


class ApprovalRequest(BaseModel):
    """
    Approval request raised when a consequential or policy-restricted step needs human sign-off.
    Defined in PRD Section 18.
    """
    approval_id: str = Field(default_factory=lambda: str(uuid4()), description="Unique ID for approval request")
    session_id: str = Field(..., description="Session ID this request belongs to")
    correlation_id: str = Field(..., description="Tracing correlation ID")
    plan_id: str = Field(..., description="Target WorkflowPlan ID")
    step_id: str = Field(..., description="Target WorkflowStep ID")
    tool_name: str = Field(..., description="Name of tool requiring approval")
    risk_level: RiskLevel = Field(..., description="Risk category")
    action_summary: str = Field(..., description="Plain-language description of intended action")
    target_resources: List[str] = Field(default_factory=list, description="Files, directories, or endpoints affected")
    status: ApprovalStatus = Field(default=ApprovalStatus.PENDING, description="Current approval status")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Creation timestamp")
    decided_at: Optional[datetime] = Field(default=None, description="Timestamp of user decision")
    rejection_reason: Optional[str] = Field(default=None, description="Reason if rejected")


class WorkflowPlan(BaseModel):
    """
    A typed, structured execution plan containing a sequence of steps.
    """
    plan_id: str = Field(default_factory=lambda: str(uuid4()), description="Unique ID for this plan")
    session_id: str = Field(..., description="Associated session ID")
    correlation_id: str = Field(..., description="Associated correlation ID for end-to-end tracing")
    title: str = Field(..., description="Short objective or description of the workflow")
    steps: List[WorkflowStep] = Field(default_factory=list, description="List of steps in execution order")
    state: WorkflowState = Field(default=WorkflowState.DRAFT, description="Current state of the plan")
    schema_version: str = Field(default="1.0.0", description="Schema version per Section 8")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Creation timestamp")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Last update timestamp")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Optional metadata / annotations")

    @model_validator(mode="after")
    def validate_plan_steps(self) -> "WorkflowPlan":
        step_ids = set()
        for step in self.steps:
            if step.step_id in step_ids:
                raise ValueError(f"Duplicate step_id detected in plan: {step.step_id}")
            step_ids.add(step.step_id)

        # Validate dependency references
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    raise ValueError(f"Step '{step.step_id}' depends on non-existent step '{dep}'")
                if dep == step.step_id:
                    raise ValueError(f"Step '{step.step_id}' cannot depend on itself")
        return self


class WorkflowResult(BaseModel):
    """
    Final output and execution report of a WorkflowPlan.
    """
    plan_id: str = Field(..., description="ID of completed workflow plan")
    session_id: str = Field(..., description="Associated session ID")
    correlation_id: str = Field(..., description="Tracing correlation ID")
    final_state: WorkflowState = Field(..., description="Final terminal state of workflow")
    step_results: Dict[str, Any] = Field(default_factory=dict, description="Results keyed by step_id")
    started_at: datetime = Field(..., description="Workflow execution start time")
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Workflow completion time")
    error_details: Optional[Dict[str, Any]] = Field(default=None, description="Details if workflow ended in failure")
