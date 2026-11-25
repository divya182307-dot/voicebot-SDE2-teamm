
"""Audio gateway for W5 Backend and Sessions - Week 3."""

import logging

from voicebot.lifecycle import AudioLifecycleController
from voicebot.schemas import AudioChunk
from voicebot.device import AudioDeviceAdapter

logger = logging.getLogger("voicebot.audio_gateway")


class AudioGateway:
    """Connect backend sessions to the existing audio module."""

    def __init__(self, adapter: AudioDeviceAdapter):
        self.controller = AudioLifecycleController(adapter)

    def capture(
        self,
        session_id: str,
        correlation_id: str,
        chunk_count: int = 5,
        frames_per_chunk: int = 1600,
    ) -> list[AudioChunk]:

        log_context = {
            "session_id": session_id,
            "correlation_id": correlation_id,
        }

        logger.info(
            "Audio capture started",
            extra=log_context,
        )

        self.controller.start()

        try:
            chunks = list(
                self.controller.capture_stream(
                    chunk_count=chunk_count,
                    frames_per_chunk=frames_per_chunk,
                )
            )

            logger.info(
                "Audio capture completed: %s chunks",
                len(chunks),
                extra=log_context,
            )

            return chunks

        except Exception:
            logger.error(
                "Audio capture failed",
                extra=log_context,
            )
            raise

        finally:
            self.controller.stop()
