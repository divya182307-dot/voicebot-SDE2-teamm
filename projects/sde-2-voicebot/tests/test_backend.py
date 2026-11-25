import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.main import app, session_events, sessions

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_sessions():
    sessions.sessions.clear()


def _approval_event() -> dict:
    return {
        "type": "approval",
        "payload": {
            "message": "The assistant is requesting permission to save a study plan.",
            "action": "Save a study plan generated from this session's transcript",
            "reason": "Saving creates persistent study-plan content from your transcript.",
            "screenContextEnabled": False,
        },
    }


def test_session_and_events_endpoint_emits_replayable_sse():
    created = client.post("/sessions").json()
    session_id = created["sessionId"]
    assert created["status"] == "active"

    workflow = {
        "type": "workflow",
        "payload": [{"id": "audio", "label": "Capture audio", "status": "active"}],
    }
    assert client.post(f"/sessions/{session_id}/events", json=workflow).status_code == 200

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": f"/sessions/{session_id}/events",
        "raw_path": f"/sessions/{session_id}/events".encode(),
        "query_string": b"",
        "headers": [(b"last-event-id", b"1")],
        "server": ("test", 80),
        "client": ("test", 1),
    }
    request = Request(scope)
    request.is_disconnected = _disconnect_after_replay
    response = asyncio.run(session_events(session_id, request))

    async def read_stream() -> list[str]:
        return [chunk async for chunk in response.body_iterator]

    chunks = asyncio.run(read_stream())
    assert len(chunks) == 2
    assert chunks[0].startswith("id: 2\ndata: ")
    assert '"type":"workflow"' in chunks[0]
    assert chunks[1] == "event: replay-complete\ndata: {}\n\n"


async def _disconnect_after_replay() -> bool:
    return True


def test_approval_and_rejection_never_execute_rejected_action():
    session_id = client.post("/sessions").json()["sessionId"]
    approval = client.post(f"/sessions/{session_id}/events", json=_approval_event())
    assert approval.status_code == 200

    rejected = client.post(f"/sessions/{session_id}/reject")
    assert rejected.json() == {"decision": "rejected"}
    events = sessions.get(session_id).events
    assert [event["type"] for event in events].count("execution") == 0
    assert events[-1]["payload"]["decision"] == "rejected"

    assert client.post(f"/sessions/{session_id}/reject").status_code == 409


def test_approval_executes_only_after_explicit_approval():
    session_id = client.post("/sessions").json()["sessionId"]
    assert client.post(f"/sessions/{session_id}/approve").status_code == 409

    client.post(f"/sessions/{session_id}/events", json=_approval_event())
    approved = client.post(f"/sessions/{session_id}/approve")

    assert approved.json() == {"decision": "approved"}
    events = sessions.get(session_id).events
    assert [event["type"] for event in events].count("execution") == 1


def test_invalid_approval_payload_is_rejected():
    session_id = client.post("/sessions").json()["sessionId"]
    response = client.post(
        f"/sessions/{session_id}/events",
        json={"type": "approval", "payload": {"action": "Do something"}},
    )
    assert response.status_code == 422


def test_stop_publishes_stopped_session_event():
    created = client.post("/sessions").json()
    response = client.post(f"/sessions/{created['sessionId']}/stop")

    assert response.json()["status"] == "stopped"
    assert sessions.get(created["sessionId"]).events[-1]["payload"]["status"] == "stopped"
