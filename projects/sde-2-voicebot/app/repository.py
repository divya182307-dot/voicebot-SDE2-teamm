
from app.sessions import (
    Session,
    SessionState,
    transition_session,
    expire_if_needed,
)


class InMemorySessionRepository:

    def __init__(self):
        self.sessions: dict[str, Session] = {}

    def create(self) -> Session:
        session = Session()
        self.sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        session = self.sessions.get(session_id)

        if session is not None:
            expire_if_needed(session)

        return session

    def update_state(
        self,
        session_id: str,
        new_state: SessionState
    ) -> Session:

        session = self.get(session_id)

        if session is None:
            raise KeyError("Session not found")

        transition_session(session, new_state)

        return session

    def list_all(self) -> list[Session]:
        return [
            expire_if_needed(session)
            for session in self.sessions.values()
        ]

    def delete(self, session_id: str) -> bool:
        return self.sessions.pop(session_id, None) is not None


# Shared in-memory repository
session_repository = InMemorySessionRepository()
