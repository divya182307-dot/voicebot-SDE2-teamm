"""Unit tests for provider-neutral BaseTranscriber adapter interface and AudioConfig."""

import asyncio
import pytest

from src.voice.adapter import (
    AudioConfig,
    AudioEncoding,
    BaseTranscriber,
    TranscriberConfig,
    TranscriberState,
)
from src.voice.exceptions import (
    TranscriberAudioError,
    TranscriberError,
    TranscriberStateError,
)
from src.voice.schemas import (
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


class DummyTranscriber(BaseTranscriber):
    """Concrete test dummy implementation of BaseTranscriber."""

    def __init__(self, session_id: str = "dummy-session", config: TranscriberConfig = None):
        super().__init__(session_id=session_id, config=config)
        self.started = False
        self.stopped = False
        self.received_chunks: list[bytes] = []
        self.finished = False

    async def _on_start(self) -> None:
        self.started = True

    async def _on_stop(self) -> None:
        self.stopped = True

    async def _process_audio_chunk(self, chunk: bytes) -> None:
        self.received_chunks.append(chunk)

    async def _on_finish_audio(self) -> None:
        self.finished = True


class FailingStartTranscriber(BaseTranscriber):
    """Dummy transcriber that throws an exception during startup."""

    async def _on_start(self) -> None:
        raise ConnectionRefusedError("Simulated socket connection failure")

    async def _on_stop(self) -> None:
        pass

    async def _process_audio_chunk(self, chunk: bytes) -> None:
        pass

    async def _on_finish_audio(self) -> None:
        pass


class TestAudioConfig:
    """Tests for AudioConfig calculations and conversions."""

    def test_default_audio_config(self):
        config = AudioConfig()
        assert config.sample_rate_hertz == 16000
        assert config.channels == 1
        assert config.encoding == AudioEncoding.PCM_S16LE
        assert config.bytes_per_sample == 2
        # 16000 * 1 * 2 = 32000 bytes/sec
        assert config.bytes_per_second == 32000
        # 100ms chunk = 32000 * 0.1 = 3200 bytes
        assert config.chunk_size_bytes == 3200

    def test_duration_and_byte_conversions(self):
        config = AudioConfig(sample_rate_hertz=16000, channels=1, encoding=AudioEncoding.PCM_S16LE)
        # 32000 bytes = 1000 ms
        assert config.bytes_to_duration_ms(32000) == 1000
        assert config.duration_ms_to_bytes(1000) == 32000
        # 1600 bytes = 50 ms
        assert config.bytes_to_duration_ms(1600) == 50
        assert config.duration_ms_to_bytes(50) == 1600

    def test_stereo_float_config(self):
        config = AudioConfig(sample_rate_hertz=48000, channels=2, encoding=AudioEncoding.PCM_F32LE)
        assert config.bytes_per_sample == 4
        # 48000 * 2 * 4 = 384000 bytes/sec
        assert config.bytes_per_second == 384000
        assert config.bytes_to_duration_ms(384000) == 1000

    def test_mulaw_bytes_per_sample(self):
        config = AudioConfig(encoding=AudioEncoding.MULAW)
        assert config.bytes_per_sample == 1


class TestBaseTranscriberLifecycle:
    """Tests for BaseTranscriber lifecycle states and error handling."""

    def test_reject_empty_session_id(self):
        with pytest.raises(ValueError, match="session_id must be a non-empty string"):
            DummyTranscriber(session_id="")

        with pytest.raises(ValueError, match="session_id must be a non-empty string"):
            DummyTranscriber(session_id="   ")

    def test_initial_state(self):
        transcriber = DummyTranscriber("test-session")
        assert transcriber.session_id == "test-session"
        assert transcriber.state == TranscriberState.IDLE
        assert not transcriber.is_listening
        assert not transcriber.is_closed

    def test_start_and_stop_lifecycle(self):
        async def _run():
            transcriber = DummyTranscriber("test-session")
            await transcriber.start()
            assert transcriber.state == TranscriberState.LISTENING
            assert transcriber.is_listening
            assert transcriber.started

            await transcriber.stop()
            assert transcriber.state == TranscriberState.STOPPED
            assert transcriber.is_closed
            assert transcriber.stopped

        asyncio.run(_run())

    def test_async_context_manager(self):
        async def _run():
            transcriber = DummyTranscriber("test-session")
            async with transcriber as t:
                assert t.is_listening
                assert t.state == TranscriberState.LISTENING
            assert transcriber.state == TranscriberState.STOPPED

        asyncio.run(_run())

    def test_reject_start_when_already_listening(self):
        async def _run():
            transcriber = DummyTranscriber("test-session")
            await transcriber.start()
            with pytest.raises(TranscriberStateError, match="Cannot start transcriber in state 'listening'"):
                await transcriber.start()
            await transcriber.stop()

        asyncio.run(_run())

    def test_startup_failure_transitions_to_error(self):
        async def _run():
            transcriber = FailingStartTranscriber("failing-session")
            with pytest.raises(TranscriberError, match="Transcriber startup failed"):
                await transcriber.start()
            assert transcriber.state == TranscriberState.ERROR
            assert transcriber.is_closed

        asyncio.run(_run())


class TestBaseTranscriberAudioIngestion:
    """Tests for push_audio and finish_audio audio validations."""

    def test_push_audio_without_start_raises_error(self):
        async def _run():
            transcriber = DummyTranscriber("test-session")
            with pytest.raises(TranscriberStateError, match="Cannot push audio in state 'idle'"):
                await transcriber.push_audio(b"audio_bytes")

        asyncio.run(_run())

    def test_push_empty_chunk_raises_audio_error(self):
        async def _run():
            transcriber = DummyTranscriber("test-session")
            await transcriber.start()
            with pytest.raises(TranscriberAudioError, match="Audio chunk cannot be empty"):
                await transcriber.push_audio(b"")
            await transcriber.stop()

        asyncio.run(_run())

    def test_push_non_bytes_raises_audio_error(self):
        async def _run():
            transcriber = DummyTranscriber("test-session")
            await transcriber.start()
            with pytest.raises(TranscriberAudioError, match="must be an instance of bytes or bytearray"):
                await transcriber.push_audio("not_bytes")
            await transcriber.stop()

        asyncio.run(_run())

    def test_push_and_finish_audio_success(self):
        async def _run():
            transcriber = DummyTranscriber("test-session")
            await transcriber.start()
            await transcriber.push_audio(b"\x01\x02\x03\x04")
            await transcriber.push_audio(b"\x05\x06\x07\x08")
            assert len(transcriber.received_chunks) == 2
            await transcriber.finish_audio()
            assert transcriber.finished
            await transcriber.stop()

        asyncio.run(_run())


class TestBaseTranscriberEventsAndListeners:
    """Tests for event broadcasting, callbacks, and subscriber streams."""

    def test_callback_listeners(self):
        async def _run():
            transcriber = DummyTranscriber("test-session")
            received_events: list[TranscriptEvent] = []

            def sync_listener(evt: TranscriptEvent):
                received_events.append(evt)

            transcriber.add_event_listener(sync_listener)
            await transcriber.start()

            test_event = TranscriptEvent(
                session_id=transcriber.session_id,
                event_type=TranscriptEventType.SPEECH_STARTED,
            )
            await transcriber._emit_event(test_event)

            assert len(received_events) == 1
            assert received_events[0].event_type == TranscriptEventType.SPEECH_STARTED
            assert received_events[0].sequence_number == 1
            assert len(transcriber.events_history) == 1

            transcriber.remove_event_listener(sync_listener)
            await transcriber._emit_event(test_event)
            assert len(received_events) == 1  # Unregistered, so not called again
            await transcriber.stop()

        asyncio.run(_run())

    def test_multiple_stream_subscribers(self):
        async def _run():
            transcriber = DummyTranscriber("multi-sub-session")
            await transcriber.start()

            sub1_events: list[TranscriptEvent] = []
            sub2_events: list[TranscriptEvent] = []

            async def sub1():
                async for evt in transcriber.stream():
                    sub1_events.append(evt)

            async def sub2():
                async for evt in transcriber.stream():
                    sub2_events.append(evt)

            t1 = asyncio.create_task(sub1())
            t2 = asyncio.create_task(sub2())
            await asyncio.sleep(0.01)

            # Emit event
            evt1 = TranscriptEvent(
                session_id=transcriber.session_id,
                event_type=TranscriptEventType.SPEECH_STARTED,
            )
            await transcriber._emit_event(evt1)
            await transcriber.stop()

            await asyncio.gather(t1, t2)
            assert len(sub1_events) == 1
            assert len(sub2_events) == 1
            assert sub1_events[0].event_id == sub2_events[0].event_id

        asyncio.run(_run())
