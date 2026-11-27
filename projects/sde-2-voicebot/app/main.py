
import uuid
import json
import logging
import asyncio
from threading import Lock
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel
from fastapi import FastAPI, Request, Header, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.errors import create_error
from app.middleware import RequestIDMiddleware
from app.repository import session_repository
from app.sessions import SessionState


# Structured JSON logging
class JSONFormatter(logging.Formatter):

    def format(self, record):
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(
                record,
                "correlation_id",
                None
            ),
            "session_id": getattr(record, "session_id", None),
        }

        return json.dumps(log_data)


logging.basicConfig(
    level=settings.log_level,
    handlers=[logging.StreamHandler()],
    force=True
)

for handler in logging.getLogger().handlers:
    handler.setFormatter(JSONFormatter())

logger = logging.getLogger("voicebot")


app = FastAPI(
    title="SDE 2 Voicebot Backend",
    description="Backend foundation with mock mode",
    version="1.0.0"
)

app.add_middleware(RequestIDMiddleware)


# In-memory stores
idempotency_store = {}
event_history = {}

# Active SSE subscribers, grouped by session ID
event_subscribers = {}

idempotency_lock = Lock()


def get_correlation_id(request: Request):
    return getattr(
        request.state,
        "correlation_id",
        str(uuid.uuid4())
    )


@app.on_event("startup")
async def startup_event():
    logger.info(
        "Voicebot application started",
        extra={"correlation_id": "startup"}
    )


# Error handlers
@app.exception_handler(StarletteHTTPException)
async def http_error_handler(
    request: Request,
    exc: StarletteHTTPException
):
    error = create_error(
        code="HTTP_ERROR",
        message="The request could not be completed.",
        correlation_id=get_correlation_id(request),
        retryable=False,
        details={"status_code": exc.status_code}
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=error.model_dump()
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    request: Request,
    exc: RequestValidationError
):
    error = create_error(
        code="INVALID_REQUEST",
        message="The request contains invalid data.",
        correlation_id=get_correlation_id(request),
        retryable=False,
        details={}
    )

    return JSONResponse(
        status_code=422,
        content=error.model_dump()
    )


@app.exception_handler(ValueError)
async def validation_error_handler(
    request: Request,
    exc: ValueError
):
    error = create_error(
        code="INVALID_SESSION_TRANSITION",
        message="This session state change is not allowed.",
        correlation_id=get_correlation_id(request),
        retryable=False
    )

    return JSONResponse(
        status_code=409,
        content=error.model_dump()
    )


# Basic endpoints
@app.get("/")
def home():
    return {
        "project": "SDE 2 Voicebot Backend",
        "status": "running",
        "mode": settings.app_mode,
        "documentation": "/docs"
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/ready")
def readiness_check():
    return {
        "status": "ready",
        "mode": settings.app_mode
    }


# Session endpoints
@app.post("/sessions")
def create_session(request: Request):
    session = session_repository.create()

    with idempotency_lock:
        event_history[session.id] = []

    logger.info(
        "Session created",
        extra={
            "correlation_id": get_correlation_id(request)
        }
    )

    return {
        "mode": settings.app_mode,
        "session": session.model_dump(mode="json")
    }


@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    session = session_repository.get(session_id)

    if session is None:
        raise StarletteHTTPException(status_code=404)

    return session.model_dump(mode="json")


# Event schemas
class MockEvent(BaseModel):
    event_type: Literal[
        "start",
        "pause",
        "resume",
        "stop",
        "complete",
        "fail",
        "expire"
    ]


EVENT_TRANSITIONS = {
    "start": SessionState.ACTIVE,
    "pause": SessionState.PAUSED,
    "resume": SessionState.ACTIVE,
    "stop": SessionState.STOPPING,
    "complete": SessionState.COMPLETED,
    "fail": SessionState.FAILED,
    "expire": SessionState.EXPIRED
}


# Record events and notify connected SSE clients
def record_event(
    session_id: str,
    event_type: str,
    session_data: dict
):
    events = event_history.setdefault(session_id, [])

    event_record = {
        "event_id": len(events) + 1,
        "session_id": session_id,
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session": session_data
    }

    events.append(event_record)

    # Notify active subscribers in event order
    for loop, queue in list(
        event_subscribers.get(session_id, set())
    ):
        if not loop.is_closed():
            loop.call_soon_threadsafe(
                queue.put_nowait,
                event_record
            )

    return event_record


# Process session events
@app.post("/sessions/{session_id}/events")
def mock_session_event(
    session_id: str,
    event: MockEvent,
    request: Request,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key"
    )
):
    with idempotency_lock:

        if session_repository.get(session_id) is None:
            raise StarletteHTTPException(status_code=404)

        store_key = None

        if idempotency_key:
            store_key = (session_id, idempotency_key)

            previous_result = idempotency_store.get(store_key)

            if previous_result is not None:

                if previous_result["event_type"] != event.event_type:
                    raise StarletteHTTPException(
                        status_code=409,
                        detail=(
                            "Idempotency key was already used "
                            "for another event."
                        )
                    )

                logger.info(
                    "Duplicate event command returned cached result",
                    extra={
                        "correlation_id": get_correlation_id(request)
                    }
                )

                return previous_result["response"]

        updated_session = session_repository.update_state(
            session_id,
            EVENT_TRANSITIONS[event.event_type]
        )

        session_data = updated_session.model_dump(mode="json")

        event_record = record_event(
            session_id,
            event.event_type,
            session_data
        )

        response = {
            "mode": settings.app_mode,
            "event_type": event.event_type,
            "event_id": event_record["event_id"],
            "session": session_data
        }

        if store_key is not None:
            idempotency_store[store_key] = {
                "event_type": event.event_type,
                "response": response
            }

        logger.info(
            "Session event processed",
            extra={
                "correlation_id": get_correlation_id(request)
            }
        )

        return response


# Retrieve stored event history
@app.get("/sessions/{session_id}/events")
def get_session_events(session_id: str):
    if session_repository.get(session_id) is None:
        raise StarletteHTTPException(status_code=404)

    with idempotency_lock:
        events = list(event_history.get(session_id, []))

    return {
        "session_id": session_id,
        "count": len(events),
        "events": events
    }


# Week 3: Live SSE streaming with event replay and reconnect
@app.get("/sessions/{session_id}/events/stream")
async def stream_session_events(
    session_id: str,
    request: Request,
    max_events: int | None = Query(default=None, ge=1),
    timeout: float | None = Query(
        default=None,
        gt=0,
        le=300
    ),
    last_event_id: int = Query(default=0, ge=0),
    last_event_id_header: int | None = Header(
        default=None,
        alias="Last-Event-ID",
        ge=0
    )
):
    # Validate session
    if session_repository.get(session_id) is None:
        raise StarletteHTTPException(status_code=404)

    # Prefer the SSE reconnect header over the query parameter
    replay_cursor = (
        last_event_id_header
        if last_event_id_header is not None
        else last_event_id
    )

    # Retrieve the latest recorded event ID
    with idempotency_lock:
        latest_event_id = len(
            event_history.get(session_id, [])
        )

    # Reject cursors that refer to nonexistent future events
    if replay_cursor > latest_event_id:
        error = create_error(
            code="INVALID_EVENT_CURSOR",
            message="The requested event ID does not exist.",
            correlation_id=get_correlation_id(request),
            retryable=False
        )

        return JSONResponse(
            status_code=400,
            content=error.model_dump()
        )

    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()

    # Use a bounded timeout when an event limit is requested
    effective_timeout = timeout

    if max_events is not None and timeout is None:
        effective_timeout = 5.0

    async def event_generator():
        sent_events = 0
        subscriber = (loop, queue)

        deadline = (
            loop.time() + effective_timeout
            if effective_timeout is not None
            else None
        )

        # Snapshot history and register subscriber atomically
        with idempotency_lock:
            events = [
                event
                for event in event_history.get(session_id, [])
                if event["event_id"] > replay_cursor
            ]

            event_subscribers.setdefault(
                session_id,
                set()
            ).add(subscriber)

        try:
            # Replay previously missed events first
            for event_record in events:

                if deadline is not None and loop.time() >= deadline:
                    return

                event_data = json.dumps(event_record)

                yield (
                    f"id: {event_record['event_id']}\n"
                    f"event: {event_record['event_type']}\n"
                    f"data: {event_data}\n\n"
                )

                sent_events += 1

                # Close when the requested event limit is reached
                if max_events is not None and sent_events >= max_events:
                    return

            # Continue waiting for newly created events
            while not await request.is_disconnected():

                wait_time = 15.0

                # Respect the overall stream timeout
                if deadline is not None:
                    remaining = deadline - loop.time()

                    if remaining <= 0:
                        return

                    wait_time = min(wait_time, remaining)

                try:
                    event_record = await asyncio.wait_for(
                        queue.get(),
                        timeout=wait_time
                    )

                    event_data = json.dumps(event_record)

                    yield (
                        f"id: {event_record['event_id']}\n"
                        f"event: {event_record['event_type']}\n"
                        f"data: {event_data}\n\n"
                    )

                    sent_events += 1

                    # Close when the event limit is reached
                    if max_events is not None and sent_events >= max_events:
                        return

                except asyncio.TimeoutError:

                    # Close the stream when its deadline is reached
                    if deadline is not None and loop.time() >= deadline:
                        return

                    # Keep normal SSE connections alive
                    yield ": keep-alive\n\n"

        finally:
            # Remove disconnected or completed subscribers
            with idempotency_lock:
                subscribers = event_subscribers.get(session_id)

                if subscribers is not None:
                    subscribers.discard(subscriber)

                    if not subscribers:
                        event_subscribers.pop(session_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )
from app.module_health import get_module_health


@app.get("/health/modules")
def module_health():
    return get_module_health()
# Week 3 mock session pipeline endpoint
from app.session_pipeline import SessionPipeline
from voicebot.device import MockAudioDeviceAdapter


@app.post("/sessions/{session_id}/run")
async def run_session_pipeline(
    session_id: str,
    request: Request
):
    if session_repository.get(session_id) is None:
        raise StarletteHTTPException(status_code=404)

    correlation_id = get_correlation_id(request)

    try:
        pipeline = SessionPipeline(
            MockAudioDeviceAdapter()
        )

        result = await pipeline.run(
            session_id=session_id,
            correlation_id=correlation_id
        )

        if pipeline.workflow is not None:
            with workflow_lock:
                existing = active_workflows.get(session_id)

                if existing and existing.plan.state.value not in {
                    "succeeded", "failed", "cancelled"
                }:
                    return JSONResponse(
                        status_code=409,
                        content=create_error(
                            code="WORKFLOW_ALREADY_ACTIVE",
                            message="A workflow is already active.",
                            correlation_id=correlation_id
                        ).model_dump()
                    )

                active_workflows[session_id] = pipeline.workflow

        return result

    except Exception:
        error = create_error(
            code="PIPELINE_FAILED",
            message="Session processing failed.",
            correlation_id=correlation_id,
            retryable=False
        )

        return JSONResponse(
            status_code=500,
            content=error.model_dump()
        )

# Week 3 workflow and approval endpoints

from app.gateways.reasoning_gateway import ReasoningGateway
from app.gateways.workflow_gateway import (
    WorkflowGateway,
    build_workflow_plan
)
from threading import Lock

active_workflows = {}
workflow_lock = Lock()


def workflow_response(gateway, result=None):

    return {
        "session_id": gateway.plan.session_id,
        "correlation_id": gateway.plan.correlation_id,
        "plan_id": gateway.plan.plan_id,
        "status": gateway.plan.state.value,
        "pending_approvals": [
            approval.model_dump(mode="json")
            for approval in gateway.pending_approvals().values()
            if approval.status.value == "pending"
        ],
        "result": (
            result.model_dump(mode="json")
            if hasattr(result, "model_dump")
            else None
        )
    }


@app.post("/sessions/{session_id}/workflow")
def start_session_workflow(
    session_id: str,
    request: Request,
    transcript: str = Query(..., min_length=1, max_length=4000)
):

    if session_repository.get(session_id) is None:
        raise StarletteHTTPException(status_code=404)

    correlation_id = get_correlation_id(request)

    with workflow_lock:

        existing = active_workflows.get(session_id)

        if existing and existing.plan.state.value not in {
            "succeeded", "failed", "cancelled"
        }:
            raise StarletteHTTPException(status_code=409)

        try:
            reasoning = ReasoningGateway().reason(
                session_id,
                correlation_id,
                transcript
            )

            if not reasoning.action_plan:
                return {
                    "session_id": session_id,
                    "correlation_id": correlation_id,
                    "status": "completed",
                    "requires_user_approval": False
                }

            plan = build_workflow_plan(
                reasoning,
                session_id,
                correlation_id
            )

            gateway = WorkflowGateway(plan)
            result = gateway.execute()

            active_workflows[session_id] = gateway

            return workflow_response(gateway, result)

        except (ValueError, KeyError, PermissionError):

            error = create_error(
                code="WORKFLOW_VALIDATION_FAILED",
                message="The workflow action is not permitted.",
                correlation_id=correlation_id,
                retryable=False
            )

            return JSONResponse(
                status_code=400,
                content=error.model_dump()
            )


@app.get("/sessions/{session_id}/workflow")
def get_session_workflow(session_id: str):

    with workflow_lock:

        gateway = active_workflows.get(session_id)

        if gateway is None:
            raise StarletteHTTPException(status_code=404)

        gateway.executor.check_for_expired_approvals()

        return workflow_response(gateway)


@app.post(
    "/sessions/{session_id}/approvals/{approval_id}/approve"
)
def approve_session_workflow(
    session_id: str,
    approval_id: str
):

    with workflow_lock:

        gateway = active_workflows.get(session_id)

        if (
            gateway is None
            or session_repository.get(session_id) is None
        ):
            raise StarletteHTTPException(status_code=404)

        gateway.executor.check_for_expired_approvals()

        approval = gateway.pending_approvals().get(approval_id)

        if approval is None:
            raise StarletteHTTPException(status_code=404)

        if approval.status.value != "pending":
            raise StarletteHTTPException(status_code=409)

        result = gateway.approve(approval_id)

        return workflow_response(gateway, result)


@app.post(
    "/sessions/{session_id}/approvals/{approval_id}/reject"
)
def reject_session_workflow(
    session_id: str,
    approval_id: str
):

    with workflow_lock:

        gateway = active_workflows.get(session_id)

        if (
            gateway is None
            or session_repository.get(session_id) is None
        ):
            raise StarletteHTTPException(status_code=404)

        gateway.executor.check_for_expired_approvals()

        approval = gateway.pending_approvals().get(approval_id)

        if approval is None:
            raise StarletteHTTPException(status_code=404)

        if approval.status.value != "pending":
            raise StarletteHTTPException(status_code=409)

        result = gateway.reject(approval_id)

        return workflow_response(gateway, result)
