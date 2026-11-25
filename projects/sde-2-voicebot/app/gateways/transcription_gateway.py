"""Gateway connecting backend sessions to transcription."""

import logging

from src.voice.orchestrator import TranscriptionOrchestrator


logger = logging.getLogger("voicebot.transcription_gateway")


class TranscriptionGateway:

    async def transcribe(
        self,
        session_id: str,
        correlation_id: str,
        audio_data: bytes,
        sample_rate: int = 16000,
        channels: int = 1
    ) -> str:

        log_context = {
            "session_id": session_id,
            "correlation_id": correlation_id
        }

        logger.info(
            "Transcription started",
            extra=log_context
        )

        try:
            orchestrator = TranscriptionOrchestrator(
                session_id=session_id
            )

            await orchestrator.process_audio(
                audio_data=audio_data,
                sample_rate=sample_rate,
                channels=channels
            )

            transcript = orchestrator.get_final_text()

            logger.info(
                "Transcription completed",
                extra=log_context
            )

            return transcript

        except Exception:
            logger.exception(
                "Transcription failed",
                extra=log_context
            )

            raise
