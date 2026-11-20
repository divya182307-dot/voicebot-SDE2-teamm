"""
Week 3 Tests: Step-Level Audit Trail and Progress Events.
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M

Days 17-18 Deliverables:
1. Every step writes an audit record with timing, arguments, output/error, and idempotency key
2. Sensitive arguments in audit records are masked/sanitized
3. Progress events emitted in real-time to active listeners for all workflow lifecycle events
"""

from typing import List
import pytest

from src.workflow.audit import ProgressEventEmitter, StepAuditLogger
from src.workflow.executor import WorkflowExecutor
from src.workflow.schemas import (
    ProgressEvent,
    ProgressEventType,
    RiskLevel,
    StepStatus,
    WorkflowPlan,
    WorkflowState,
    WorkflowStep,
)
from src.workflow.tools import MockKnowledgeSearchTool, ToolRegistry


@pytest.fixture
def test_setup():
    registry = ToolRegistry()
    registry.register(MockKnowledgeSearchTool())
    audit_logger = StepAuditLogger()
    event_emitter = ProgressEventEmitter()
    return registry, audit_logger, event_emitter


def test_step_level_audit_trail_recorded(test_setup):
    """
    Acceptance Criteria 2: Every step writes an audit record.
    """
    registry, audit_logger, event_emitter = test_setup

    plan = WorkflowPlan(
        plan_id="plan-audit-1",
        session_id="sess-audit-1",
        correlation_id="corr-audit-1",
        title="Audit Trail Verification Plan",
        steps=[
            WorkflowStep(
                step_id="step-01",
                tool_name="knowledge_search",
                description="Query FAQ",
                arguments={"query": "cs101"},
            ),
            WorkflowStep(
                step_id="step-02",
                tool_name="knowledge_search",
                description="Query exam policy",
                arguments={"query": "exam policy"},
                depends_on=["step-01"],
            ),
        ],
    )

    executor = WorkflowExecutor(
        plan=plan,
        registry=registry,
        audit_logger=audit_logger,
        event_emitter=event_emitter,
    )
    result = executor.run()

    assert result is not None
    assert result.final_state == WorkflowState.SUCCEEDED

    trail = audit_logger.get_trail("plan-audit-1")
    assert len(trail) == 2

    step1_record = trail[0]
    assert step1_record.step_id == "step-01"
    assert step1_record.tool_name == "knowledge_search"
    assert step1_record.status == StepStatus.SUCCEEDED
    assert step1_record.arguments == {"query": "cs101"}
    assert step1_record.result is not None
    assert step1_record.duration_ms >= 0.0
    assert step1_record.started_at <= step1_record.completed_at
    assert step1_record.idempotency_key is not None

    step2_record = trail[1]
    assert step2_record.step_id == "step-02"
    assert step2_record.status == StepStatus.SUCCEEDED


def test_audit_trail_sanitizes_sensitive_fields(test_setup):
    """Verify that credentials and tokens in tool arguments are masked in audit records."""
    registry, audit_logger, _ = test_setup

    audit_logger.record_step(
        plan_id="plan-sec-1",
        step_id="step-auth",
        tool_name="knowledge_search",
        status=StepStatus.SUCCEEDED,
        arguments={
            "query": "tuition",
            "auth_token": "super-secret-jwt-12345",
            "user_password": "PlaintextPassword!",
        },
        started_at=pytest.importorskip("datetime").datetime.now(pytest.importorskip("datetime").timezone.utc),
    )

    trail = audit_logger.get_trail("plan-sec-1")
    assert len(trail) == 1
    args = trail[0].arguments

    assert args["query"] == "tuition"
    assert args["auth_token"] == "******"
    assert args["user_password"] == "******"


def test_progress_events_emitted_to_listeners(test_setup):
    """
    Acceptance Criteria 2: Workflow emits real-time progress events to subscribers.
    """
    registry, audit_logger, event_emitter = test_setup

    captured_events: List[ProgressEvent] = []

    def on_progress(event: ProgressEvent):
        captured_events.append(event)

    event_emitter.subscribe(on_progress)

    plan = WorkflowPlan(
        plan_id="plan-events-1",
        session_id="sess-events-1",
        correlation_id="corr-events-1",
        title="Event Emission Plan",
        steps=[
            WorkflowStep(
                step_id="step-01",
                tool_name="knowledge_search",
                description="Search syllabus",
                arguments={"query": "cs101"},
            ),
        ],
    )

    executor = WorkflowExecutor(
        plan=plan,
        registry=registry,
        audit_logger=audit_logger,
        event_emitter=event_emitter,
    )
    executor.run()

    assert len(captured_events) >= 3

    event_types = [e.event_type for e in captured_events]
    assert ProgressEventType.WORKFLOW_STARTED in event_types
    assert ProgressEventType.STEP_STARTED in event_types
    assert ProgressEventType.STEP_COMPLETED in event_types
    assert ProgressEventType.WORKFLOW_COMPLETED in event_types

    # Unsubscribe test
    event_emitter.unsubscribe(on_progress)
    prev_count = len(captured_events)
    event_emitter.emit(
        event_type=ProgressEventType.STEP_PROGRESS,
        plan_id="plan-events-1",
        message="Should not be captured by unsubscribed listener",
    )
    assert len(captured_events) == prev_count

