"""
Agentic Workflow Package for Academiaai AI Voicebot.
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M

Week 1 (Days 1-7): Foundation, schemas, state machine, mock tools, executor, tests, demo.
Week 2 (Days 8-14): PlanValidator (DAG, cycles, allow-lists, scopes), Approval expiry logic,
                    timeouts, bounded idempotent retries, and comprehensive policy tests.
"""

from src.workflow.schemas import (
    ApprovalRequest,
    ApprovalStatus,
    RetryPolicy,
    RiskLevel,
    StepStatus,
    ToolFailureBehavior,
    ToolSpec,
    WorkflowPlan,
    WorkflowResult,
    WorkflowState,
    WorkflowStep,
)
from src.workflow.state_machine import (
    InvalidStateTransitionError,
    StateTransitionEvent,
    WorkflowStateMachine,
)
from src.workflow.tools import (
    BaseTool,
    MockCourseScheduleTool,
    MockKnowledgeSearchTool,
    ToolRegistry,
)
from src.workflow.validator import (
    PlanValidationError,
    PlanValidator,
)
from src.workflow.executor import (
    ExecutionEvent,
    WorkflowExecutor,
)

__all__ = [
    # Schemas
    "WorkflowPlan",
    "WorkflowStep",
    "ToolSpec",
    "ApprovalRequest",
    "WorkflowResult",
    "WorkflowState",
    "RiskLevel",
    "ApprovalStatus",
    "StepStatus",
    "ToolFailureBehavior",
    "RetryPolicy",
    # State Machine
    "WorkflowStateMachine",
    "InvalidStateTransitionError",
    "StateTransitionEvent",
    # Tools
    "BaseTool",
    "MockKnowledgeSearchTool",
    "MockCourseScheduleTool",
    "ToolRegistry",
    # Validator
    "PlanValidator",
    "PlanValidationError",
    # Executor
    "WorkflowExecutor",
    "ExecutionEvent",
]
