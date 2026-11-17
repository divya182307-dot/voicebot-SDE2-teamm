
from enum import Enum
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


class SessionState(str, Enum):
    CREATED = "created"
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


# Allowed session state transitions
ALLOWED_TRANSITIONS = {
    SessionState.CREATED: {
        SessionState.ACTIVE,
        SessionState.FAILED,
        SessionState.EXPIRED,
    },
    SessionState.ACTIVE: {
        SessionState.PAUSED,
        SessionState.STOPPING,
        SessionState.FAILED,
        SessionState.EXPIRED,
    },
    SessionState.PAUSED: {
        SessionState.ACTIVE,
        SessionState.STOPPING,
        SessionState.FAILED,
        SessionState.EXPIRED,
    },
    SessionState.STOPPING: {
        SessionState.COMPLETED,
        SessionState.FAILED,
    },
    SessionState.COMPLETED: set(),
    SessionState.FAILED: set(),
    SessionState.EXPIRED: set(),
}


class Session(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    state: SessionState = SessionState.CREATED
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


def transition_session(session: Session, new_state: SessionState):
    allowed = ALLOWED_TRANSITIONS[session.state]

    if new_state not in allowed:
        raise ValueError(
            f"Invalid session transition: "
            f"{session.state.value} -> {new_state.value}"
        )

    session.state = new_state
    session.updated_at = datetime.now(timezone.utc)

    return session
