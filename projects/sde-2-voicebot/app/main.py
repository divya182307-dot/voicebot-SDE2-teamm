
import uuid

from typing import Literal
from pydantic import BaseModel
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.errors import create_error
from app.middleware import RequestIDMiddleware
from app.repository import session_repository
from app.sessions import SessionState


app = FastAPI(
    title="SDE 2 Voicebot Backend",
    description="Backend foundation with mock mode",
    version="1.0.0"
)

app.add_middleware(RequestIDMiddleware)


def get_correlation_id(request: Request):
    return getattr(
        request.state,
        "correlation_id",
        str(uuid.uuid4())
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
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
async def validation_error_handler(request: Request, exc: ValueError):
    error = create_error(
        code="INVALID_SESSION_TRANSITION",
        message="This session state change is not allowed.",
        correlation_id=get_correlation_id(request),
        retryable=False
    )
    return JSONResponse(status_code=409, content=error.model_dump())
@app.get("/")
def home():
    return {
        "project": "SDE 2 Voicebot Backend",
        "status": "running",
        "mode": "mock",
        "documentation": "/docs"
    }

@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/ready")
def readiness_check():
    return {"status": "ready", "mode": "mock"}


@app.post("/sessions")
def create_session():
    session = session_repository.create()
    return {
        "mode": "mock",
        "session": session.model_dump(mode="json")
    }


@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    session = session_repository.get(session_id)

    if session is None:
        raise StarletteHTTPException(status_code=404)

    return session.model_dump(mode="json")


class MockEvent(BaseModel):
    event_type: Literal[
        "start", "pause", "resume", "stop",
        "complete", "fail", "expire"
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



@app.post("/sessions/{session_id}/events")
def mock_session_event(session_id: str, event: MockEvent):
    if session_repository.get(session_id) is None:
        raise StarletteHTTPException(status_code=404)

    updated_session = session_repository.update_state(
        session_id,
        EVENT_TRANSITIONS[event.event_type]
    )

    return {
        "mode": "mock",
        "event_type": event.event_type,
        "session": updated_session.model_dump(mode="json")
    }
