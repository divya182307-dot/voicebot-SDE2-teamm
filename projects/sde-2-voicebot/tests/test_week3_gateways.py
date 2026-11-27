"""End-to-end integration tests for all four backend gateways."""

import pytest

from app.gateways import transcription_gateway
from app.gateways.audio_gateway import AudioGateway
from app.gateways.transcription_gateway import TranscriptionGateway
from app.gateways.reasoning_gateway import ReasoningGateway
from app.gateways.workflow_gateway import (
    WorkflowGateway,
    MockFileActionTool,
)
from app.session_pipeline import SessionPipeline
from src.voice import orchestrator
from src.voice.fake_transcriber import FakeTranscriber


@pytest.fixture
def scripted_transcription(monkeypatch):
    """Use a deterministic speech provider for workflow testing."""

    def create_transcriber(*args, **kwargs):
        kwargs["script"] = "move files"
        return FakeTranscriber(*args, **kwargs)

    monkeypatch.setattr(
        orchestrator,
        "FakeTranscriber",
        create_transcriber
    )


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_audio_transcription_reasoning_workflow_gateways(
    authenticated_client,
    scripted_transcription,
    monkeypatch,
    decision
):
    """Run a real mock session through all four gateways."""

    calls = []

    def track_method(cls, method_name, label):
        original = getattr(cls, method_name)

        def tracked(self, *args, **kwargs):
            calls.append(label)
            return original(self, *args, **kwargs)

        monkeypatch.setattr(cls, method_name, tracked)

    track_method(AudioGateway, "capture", "audio")
    track_method(ReasoningGateway, "reason", "reasoning")
    track_method(WorkflowGateway, "execute", "workflow")
    track_method(MockFileActionTool, "execute", "file_action")

    original_transcribe = TranscriptionGateway.transcribe

    async def tracked_transcribe(self, *args, **kwargs):
        calls.append("transcription")
        return await original_transcribe(self, *args, **kwargs)

    monkeypatch.setattr(
        TranscriptionGateway,
        "transcribe",
        tracked_transcribe
    )

    correlation_id = f"gateway-test-{decision}"

    headers = {
        "X-Correlation-ID": correlation_id
    }

    response = authenticated_client.post(
        "/sessions",
        headers=headers
    )

    assert response.status_code == 200, response.text

    session_id = response.json()["session"]["id"]

    response = authenticated_client.post(
        f"/sessions/{session_id}/run",
        headers=headers
    )

    assert response.status_code == 200, response.text

    result = response.json()

    assert calls == [
        "audio",
        "transcription",
        "reasoning",
        "workflow"
    ]

    assert result["audio_chunks"] > 0
    assert result["transcript"] == "move files"
    assert result["session_id"] == session_id
    assert result["correlation_id"] == correlation_id

    assert result["reasoning"]["session_id"] == session_id
    assert result["reasoning"]["request_id"] == correlation_id

    assert result["status"] == "awaiting_approval"
    assert result["requires_user_approval"] is True
    assert result["workflow"] is not None

    approvals = result["workflow"]["pending_approvals"]

    assert len(approvals) == 1

    approval_id = approvals[0]["approval_id"]

    assert "file_action" not in calls

    response = authenticated_client.post(
        f"/sessions/{session_id}/approvals/{approval_id}/{decision}",
        headers=headers
    )

    assert response.status_code == 200, response.text

    workflow = response.json()

    if decision == "approve":
        assert workflow["status"] == "succeeded"
        assert calls.count("file_action") == 1

    else:
        assert workflow["status"] in {"cancelled", "failed"}
        assert "file_action" not in calls

    assert workflow["pending_approvals"] == []

    # A consumed approval is no longer pending and must not execute again.
    response = authenticated_client.post(
        f"/sessions/{session_id}/approvals/{approval_id}/{decision}",
        headers=headers
    )

    assert response.status_code == 404, response.text

    assert calls.count("file_action") == (
        1 if decision == "approve" else 0
    )
