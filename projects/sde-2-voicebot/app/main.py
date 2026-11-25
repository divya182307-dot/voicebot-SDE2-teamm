import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

EventType = Literal[
    "session",
    "workflow",
    "transcript",
    "approval",
    "approval-decision",
    "execution",
]


class EventRequest(BaseModel):
    type: Literal["workflow", "transcript", "approval"]
    payload: Any


class WorkflowStep(BaseModel):
    id: str
    label: str
    status: Literal["pending", "active", "complete", "rejected"]


class TranscriptPayload(BaseModel):
    id: int
    speaker: Literal["Student", "AI Assistant"]
    text: str
    timestamp: str
    type: Literal["interim", "final"]
    confidence: float = Field(ge=0, le=1)
    revision: int = Field(ge=0)
    isRevised: bool


class ApprovalPayload(BaseModel):
    message: str = Field(min_length=1)
    action: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    screenContextEnabled: bool


class SessionRecord:
    def __init__(self) -> None:
        self.session_id = str(uuid4())
        self.status: Literal["active", "stopped"] = "active"
        self.events: list[dict[str, Any]] = []
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.pending_approval = False


class SessionStore:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionRecord] = {}

    def create(self) -> SessionRecord:
        session = SessionRecord()
        self.sessions[session.session_id] = session
        self.publish(
            session,
            "session",
            {"sessionId": session.session_id, "status": "active"},
        )
        return session

    def get(self, session_id: str) -> SessionRecord:
        session = self.sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session

    @staticmethod
    def publish(
        session: SessionRecord,
        event_type: EventType,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        event = {
            "id": len(session.events) + 1,
            "type": event_type,
            "payload": payload,
        }
        session.events.append(event)
        for subscriber in tuple(session.subscribers):
            subscriber.put_nowait(event)
        return event


sessions = SessionStore()
app = FastAPI(title="Academia AI Voice Co-Pilot Week 3 Backend", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/sessions")
def start_session() -> dict[str, str]:
    session = sessions.create()
    return {
        "sessionId": session.session_id,
        "status": session.status,
        "message": "Session started successfully",
    }


@app.post("/sessions/{session_id}/stop")
def stop_session(session_id: str) -> dict[str, str]:
    session = sessions.get(session_id)
    if session.status == "active":
        session.status = "stopped"
        sessions.publish(
            session,
            "session",
            {"sessionId": session.session_id, "status": "stopped"},
        )
    return {
        "sessionId": session.session_id,
        "status": session.status,
        "message": "Session stopped successfully",
    }


@app.get("/sessions/{session_id}/events")
async def session_events(
    session_id: str,
    request: Request,
    after: int = 0,
) -> StreamingResponse:
    session = sessions.get(session_id)
    try:
        last_event_id = max(
            0,
            after,
            int(request.headers.get("last-event-id", "0")),
        )
    except ValueError:
        last_event_id = 0

    async def stream() -> AsyncIterator[str]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        session.subscribers.add(queue)
        last_sent_id = last_event_id
        try:
            for event in tuple(session.events):
                if event["id"] > last_sent_id:
                    yield _encode_sse(event)
                    last_sent_id = event["id"]
            yield "event: replay-complete\ndata: {}\n\n"
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                else:
                    if event["id"] <= last_sent_id:
                        continue
                    yield _encode_sse(event)
                    last_sent_id = event["id"]
        finally:
            session.subscribers.discard(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/sessions/{session_id}/events")
def publish_session_event(session_id: str, event: EventRequest) -> dict[str, Any]:
    session = sessions.get(session_id)
    if session.status != "active":
        raise HTTPException(status_code=409, detail="Session is not active")
    payload = event.payload
    try:
        if event.type == "workflow":
            payload = [
                step.model_dump()
                for step in TypeAdapter(list[WorkflowStep]).validate_python(event.payload)
            ]
        elif event.type == "transcript":
            payload = TranscriptPayload.model_validate(event.payload).model_dump()
        else:
            payload = ApprovalPayload.model_validate(event.payload).model_dump()
    except ValidationError as error:
        raise HTTPException(status_code=422, detail="Invalid event payload") from error
    if event.type == "approval":
        session.pending_approval = True
    published = sessions.publish(session, event.type, payload)
    return {"event": published}


@app.post("/sessions/{session_id}/approve")
def approve_action(session_id: str) -> dict[str, Literal["approved"]]:
    session = sessions.get(session_id)
    _require_pending_approval(session)
    session.pending_approval = False
    sessions.publish(
        session,
        "execution",
        {"message": "Approved action execution started."},
    )
    sessions.publish(session, "approval-decision", {"decision": "approved"})
    return {"decision": "approved"}


@app.post("/sessions/{session_id}/reject")
def reject_action(session_id: str) -> dict[str, Literal["rejected"]]:
    session = sessions.get(session_id)
    _require_pending_approval(session)
    session.pending_approval = False
    sessions.publish(session, "approval-decision", {"decision": "rejected"})
    return {"decision": "rejected"}


def _require_pending_approval(session: SessionRecord) -> None:
    if session.status != "active":
        raise HTTPException(status_code=409, detail="Session is not active")
    if not session.pending_approval:
        raise HTTPException(status_code=409, detail="No action is awaiting approval")


def _encode_sse(event: dict[str, Any]) -> str:
    data = json.dumps(event, separators=(",", ":"))
    return f"id: {event['id']}\ndata: {data}\n\n"
