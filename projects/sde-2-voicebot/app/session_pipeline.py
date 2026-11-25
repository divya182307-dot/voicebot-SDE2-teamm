import logging

from app.gateways.audio_gateway import AudioGateway
from app.gateways.transcription_gateway import TranscriptionGateway
from app.gateways.reasoning_gateway import ReasoningGateway
from app.gateways.workflow_gateway import (
    WorkflowGateway,
    build_workflow_plan
)

logger = logging.getLogger("voicebot.session_pipeline")


class SessionPipeline:

    def __init__(self, audio_adapter):
        self.audio = AudioGateway(audio_adapter)
        self.transcription = TranscriptionGateway()
        self.reasoning = ReasoningGateway()
        self.workflow = None

    async def run(self, session_id, correlation_id):

        context = {
            "session_id": session_id,
            "correlation_id": correlation_id
        }

        self.workflow = None

        logger.info("Session pipeline started", extra=context)

        try:
            chunks = self.audio.capture(
                session_id=session_id,
                correlation_id=correlation_id
            )

            if not chunks:
                raise ValueError("No audio chunks captured")

            audio_data = b"".join(
                chunk.data for chunk in chunks
            )

            audio_format = chunks[0].audio_format

            transcript = await self.transcription.transcribe(
                session_id=session_id,
                correlation_id=correlation_id,
                audio_data=audio_data,
                sample_rate=audio_format.sample_rate,
                channels=audio_format.channels
            )

            if not transcript.strip():
                raise ValueError("No transcript generated")

            reasoning = self.reasoning.reason(
                session_id=session_id,
                correlation_id=correlation_id,
                transcript=transcript
            )

            workflow_data = None
            approvals = []
            status = "completed"

            if reasoning.action_plan:

                plan = build_workflow_plan(
                    reasoning,
                    session_id,
                    correlation_id
                )

                self.workflow = WorkflowGateway(plan)

                result = self.workflow.execute()

                approvals = [
                    approval.model_dump(mode="json")
                    for approval in
                    self.workflow.pending_approvals().values()
                    if approval.status.value == "pending"
                ]

                workflow_data = {
                    "plan_id": plan.plan_id,
                    "status": plan.state.value,
                    "pending_approvals": approvals,
                    "result": (
                        result.model_dump(mode="json")
                        if result is not None
                        else None
                    )
                }

                status = (
                    "completed"
                    if plan.state.value == "succeeded"
                    else plan.state.value
                )

            elif (
                reasoning.requires_user_approval
                or reasoning.tool_call_required
            ):
                status = "awaiting_workflow_validation"

            logger.info(
                "Session pipeline finished",
                extra=context
            )

            return {
                "session_id": session_id,
                "correlation_id": correlation_id,
                "status": status,
                "audio_chunks": len(chunks),
                "transcript": transcript,
                "reasoning": reasoning.model_dump(mode="json"),
                "workflow": workflow_data,
                "requires_user_approval": (
                    bool(approvals)
                    or reasoning.requires_user_approval
                )
            }

        except Exception:
            logger.exception(
                "Session pipeline failed",
                extra=context
            )
            raise
