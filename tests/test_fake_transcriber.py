"""Comprehensive unit tests for deterministic FakeTranscriber."""

import asyncio
from datetime import datetime, timezone
import json
import pytest

from src.voice.adapter import AudioConfig, TranscriberConfig, TranscriberState
from src.voice.fake_transcriber import (
    DEFAULT_REFERENCE_TIMESTAMP,
    FakeTranscriber,
    FakeUtterance,
    generate_deterministic_words,
    generate_progressive_interims,
)
from src.voice.schemas import (
    TranscriptError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
    WordTiming,
)


class TestDeterministicWordsAndInterims:
    """Tests for word slicing and interim text generation helpers."""

    def test_progressive_interims_generation(self):
        steps = generate_progressive_interims("Why is this failing")
        assert steps == ["Why", "Why is", "Why is this", "Why is this failing"]

    def test_generate_deterministic_words_constraints(self):
        words = generate_deterministic_words(
            text="What is Dijkstra algorithm",
            start_time_ms=0,
            end_time_ms=1000,
            base_confidence=0.96,
        )
        assert len(words) == 4
        # Verify chronological ordering
        for i in range(len(words)):
            assert words[i].start_time_ms >= 0
            assert words[i].end_time_ms >= words[i].start_time_ms
            assert 0.0 <= words[i].confidence <= 1.0
            if i > 0:
                assert words[i].start_time_ms >= words[i - 1].end_time_ms

    def test_generate_deterministic_words_reproducibility(self):
        words1 = generate_deterministic_words("Reproducible test", 0, 500)
        words2 = generate_deterministic_words("Reproducible test", 0, 500)
        assert words1 == words2


class TestFakeTranscriberDeterminism:
    """Core tests verifying that identical inputs yield identical TranscriptEvents."""

    def test_identical_audio_yields_identical_events(self):
        """CRITICAL: Same audio bytes fed to two independent FakeTranscribers must yield identical events."""

        async def _run():
            # 32000 bytes = 1000 ms of 16kHz 16-bit mono audio
            audio_bytes = b"\x12\x34\x56\x78" * 8000

            ft1 = FakeTranscriber(session_id="determinism-session-1")
            events1 = await ft1.transcribe_audio(audio_bytes)

            ft2 = FakeTranscriber(session_id="determinism-session-1")
            events2 = await ft2.transcribe_audio(audio_bytes)

            # 1. Total event count must be identical
            assert len(events1) == len(events2)
            assert len(events1) > 0

            # 2. Strict model equality across all events
            assert events1 == events2

            # 3. JSON serialized strings must be bit-for-bit identical
            for e1, e2 in zip(events1, events2):
                assert e1.model_dump_json() == e2.model_dump_json()
                assert e1.event_id == e2.event_id
                assert e1.sequence_number == e2.sequence_number
                assert e1.timestamp == e2.timestamp
                assert e1.event_type == e2.event_type
                if e1.segment and e2.segment:
                    assert e1.segment.id == e2.segment.id
                    assert e1.segment.text == e2.segment.text
                    assert e1.segment.confidence == e2.segment.confidence
                    assert e1.segment.start_time_ms == e2.segment.start_time_ms
                    assert e1.segment.end_time_ms == e2.segment.end_time_ms
                    assert e1.segment.words == e2.segment.words

        asyncio.run(_run())

    def test_identical_script_yields_identical_events(self):
        """CRITICAL: Same script fed to two independent FakeTranscribers must yield identical events."""

        async def _run():
            script = ["What is the difference between processes and threads?"]
            audio_chunk = b"\x00" * 3200  # 100ms per chunk

            async def run_session():
                transcriber = FakeTranscriber(session_id="script-session", script=script)
                events = []
                async with transcriber:
                    for _ in range(8):  # push 800ms
                        await transcriber.push_audio(audio_chunk)
                    await transcriber.finish_audio()
                    events = transcriber.events_history
                return events

            events_a = await run_session()
            events_b = await run_session()

            assert len(events_a) == len(events_b)
            assert events_a == events_b

        asyncio.run(_run())

    def test_different_audio_yields_distinct_transcripts(self):
        """Different audio fingerprints produce deterministically different selections."""

        async def _run():
            audio_a = b"\x00\x01" * 8000
            audio_b = b"\xfe\xff" * 8000

            ft_a = FakeTranscriber(session_id="diff-audio-session")
            events_a = await ft_a.transcribe_audio(audio_a)

            ft_b = FakeTranscriber(session_id="diff-audio-session")
            events_b = await ft_b.transcribe_audio(audio_b)

            final_a = [e for e in events_a if e.event_type == TranscriptEventType.FINAL_TRANSCRIPT][0]
            final_b = [e for e in events_b if e.event_type == TranscriptEventType.FINAL_TRANSCRIPT][0]

            # Different audio should produce different transcript text or digests
            assert final_a.segment.text != final_b.segment.text or events_a != events_b

        asyncio.run(_run())


class TestFakeTranscriberStreamingLifecycle:
    """Tests for the event sequence, state machine, and streaming callbacks."""

    def test_event_lifecycle_ordering(self):
        """Ensure stream emits: SPEECH_STARTED -> INTERIM* -> FINAL_TRANSCRIPT -> SPEECH_ENDED."""

        async def _run():
            script = ["Explain merge sort algorithm"]
            transcriber = FakeTranscriber(session_id="lifecycle-session", script=script)

            audio_data = b"\x00" * 16000  # 500 ms
            events = await transcriber.transcribe_audio(audio_data)

            event_types = [e.event_type for e in events]

            # 1. First event is SPEECH_STARTED
            assert event_types[0] == TranscriptEventType.SPEECH_STARTED
            assert events[0].segment is None
            assert events[0].error is None

            # 2. Intermediate events are INTERIM_TRANSCRIPT with is_final=False
            interim_events = [e for e in events if e.event_type == TranscriptEventType.INTERIM_TRANSCRIPT]
            assert len(interim_events) >= 1
            for ie in interim_events:
                assert ie.segment is not None
                assert ie.segment.is_final is False
                assert ie.segment.start_time_ms >= 0
                assert ie.segment.end_time_ms >= ie.segment.start_time_ms

            # 3. Final event is FINAL_TRANSCRIPT with is_final=True
            final_events = [e for e in events if e.event_type == TranscriptEventType.FINAL_TRANSCRIPT]
            assert len(final_events) == 1
            assert final_events[0].segment.is_final is True
            assert final_events[0].segment.text == "Explain merge sort algorithm"
            assert final_events[0].segment.words is not None

            # 4. Concluding event is SPEECH_ENDED
            assert event_types[-1] == TranscriptEventType.SPEECH_ENDED
            assert events[-1].segment is None
            assert events[-1].error is None

            # 5. Monotonic sequence numbers
            seq_numbers = [e.sequence_number for e in events]
            assert seq_numbers == list(range(1, len(events) + 1))

        asyncio.run(_run())

    def test_interim_results_disabled(self):
        """When interim_results=False, no interim hypotheses should be emitted."""

        async def _run():
            config = TranscriberConfig(interim_results=False)
            transcriber = FakeTranscriber(
                session_id="no-interim-session",
                config=config,
                script="Test utterance without interims",
            )
            events = await transcriber.transcribe_audio(b"\x00" * 32000)

            event_types = [e.event_type for e in events]
            assert TranscriptEventType.INTERIM_TRANSCRIPT not in event_types
            assert event_types == [
                TranscriptEventType.SPEECH_STARTED,
                TranscriptEventType.FINAL_TRANSCRIPT,
                TranscriptEventType.SPEECH_ENDED,
            ]

        asyncio.run(_run())

    def test_word_timings_disabled(self):
        """When word_timings=False, final segment.words should be None."""

        async def _run():
            config = TranscriberConfig(word_timings=False)
            transcriber = FakeTranscriber(
                session_id="no-words-session",
                config=config,
                script="No word breakdown needed",
            )
            events = await transcriber.transcribe_audio(b"\x00" * 32000)
            final_event = [e for e in events if e.event_type == TranscriptEventType.FINAL_TRANSCRIPT][0]
            assert final_event.segment.words is None

        asyncio.run(_run())


class TestFakeTranscriberMultiUtteranceAndStreaming:
    """Tests for multi-utterance scripts and stream piping."""

    def test_multi_utterance_script(self):
        """Transcribing multiple pre-scripted sentences."""

        async def _run():
            script = [
                FakeUtterance(text="First utterance.", duration_ms=400),
                FakeUtterance(text="Second utterance.", duration_ms=400),
            ]
            transcriber = FakeTranscriber(session_id="multi-utterance-session", script=script)

            # Feed 1000ms of audio (enough for both utterances)
            audio = b"\x00" * 32000
            events = await transcriber.transcribe_audio(audio)

            final_events = [e for e in events if e.event_type == TranscriptEventType.FINAL_TRANSCRIPT]
            assert len(final_events) == 2
            assert final_events[0].segment.text == "First utterance."
            assert final_events[1].segment.text == "Second utterance."

        asyncio.run(_run())

    def test_transcribe_stream_pipeline(self):
        """Test transcribe_stream with an async chunk generator."""

        async def _run():
            async def audio_generator():
                for _ in range(5):
                    yield b"\x00" * 3200  # 5 * 100ms = 500ms

            transcriber = FakeTranscriber(
                session_id="async-stream-session",
                script="Testing async audio stream piping",
            )
            await transcriber.start()

            collected_events: list[TranscriptEvent] = []
            async for event in transcriber.transcribe_stream(audio_generator()):
                collected_events.append(event)

            await transcriber.stop()

            assert len(collected_events) >= 3
            assert collected_events[0].event_type == TranscriptEventType.SPEECH_STARTED
            assert collected_events[-1].event_type == TranscriptEventType.SPEECH_ENDED

        asyncio.run(_run())


class TestFakeTranscriberErrorInjection:
    """Tests for deterministic error injection."""

    def test_error_injection_after_chunks(self):
        """Verify that FakeTranscriber deterministically emits ERROR after N chunks."""

        async def _run():
            custom_error = TranscriptError(
                code="SIMULATED_MICROPHONE_DISCONNECT",
                message="Microphone unplugged during session.",
                details={"port": "USB-1"},
            )
            transcriber = FakeTranscriber(
                session_id="error-session",
                error_after_chunks=3,
                simulated_error=custom_error,
            )

            async with transcriber:
                for i in range(5):
                    if transcriber.state == TranscriberState.ERROR:
                        break
                    await transcriber.push_audio(b"\x00" * 3200)

            events = transcriber.events_history
            assert transcriber.state == TranscriberState.ERROR

            error_events = [e for e in events if e.event_type == TranscriptEventType.ERROR]
            assert len(error_events) == 1
            assert error_events[0].error is not None
            assert error_events[0].error.code == "SIMULATED_MICROPHONE_DISCONNECT"
            assert error_events[0].error.message == "Microphone unplugged during session."
            assert error_events[0].error.details == {"port": "USB-1"}

        asyncio.run(_run())


class TestFakeTranscriberAdvancedFeatures:
    """Tests for timestamps, custom utterances, realtime flags, and edge cases."""

    def test_custom_base_timestamp(self):
        async def _run():
            custom_time = datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
            transcriber = FakeTranscriber(
                session_id="custom-time-session",
                script="Test timestamp offset",
                base_timestamp=custom_time,
            )
            events = await transcriber.transcribe_audio(b"\x00" * 32000)
            assert events[0].timestamp >= custom_time

        asyncio.run(_run())

    def test_custom_fake_utterance_with_explicit_words(self):
        async def _run():
            explicit_words = [
                WordTiming(word="Custom", start_time_ms=0, end_time_ms=300, confidence=0.99),
                WordTiming(word="timing", start_time_ms=310, end_time_ms=700, confidence=0.98),
            ]
            utterance = FakeUtterance(
                text="Custom timing",
                duration_ms=800,
                confidence=0.99,
                words=explicit_words,
                interim_steps=["Custom", "Custom timing"],
            )
            transcriber = FakeTranscriber(session_id="explicit-utterance", script=[utterance])
            events = await transcriber.transcribe_audio(b"\x00" * 32000)

            final_event = [e for e in events if e.event_type == TranscriptEventType.FINAL_TRANSCRIPT][0]
            assert final_event.segment.words == explicit_words
            assert final_event.segment.text == "Custom timing"

        asyncio.run(_run())

    def test_simulate_realtime_delay(self):
        async def _run():
            transcriber = FakeTranscriber(
                session_id="realtime-session",
                script="Short test",
                simulate_realtime=True,
            )
            # 160 bytes at 16kHz 16-bit mono = 5ms duration
            await transcriber.start()
            await transcriber.push_audio(b"\x00" * 160)
            await transcriber.finish_audio()
            await transcriber.stop()
            assert len(transcriber.events_history) > 0

        asyncio.run(_run())

    def test_direct_finish_without_pushing_audio(self):
        async def _run():
            transcriber = FakeTranscriber(
                session_id="direct-finish-session",
                script=["Unheard utterance."],
            )
            await transcriber.start()
            await transcriber.finish_audio()
            await transcriber.stop()

            final_events = [e for e in transcriber.events_history if e.event_type == TranscriptEventType.FINAL_TRANSCRIPT]
            assert len(final_events) == 1
            assert final_events[0].segment.text == "Unheard utterance."

        asyncio.run(_run())

    def test_seed_variation_changes_fallback_selection(self):
        async def _run():
            audio_bytes = b"\xaa\xbb" * 8000

            ft1 = FakeTranscriber(session_id="seed-session-1", seed=1)
            events1 = await ft1.transcribe_audio(audio_bytes)

            ft2 = FakeTranscriber(session_id="seed-session-2", seed=2)
            events2 = await ft2.transcribe_audio(audio_bytes)

            final1 = [e for e in events1 if e.event_type == TranscriptEventType.FINAL_TRANSCRIPT][0]
            final2 = [e for e in events2 if e.event_type == TranscriptEventType.FINAL_TRANSCRIPT][0]

            assert final1.segment.text != final2.segment.text

        asyncio.run(_run())

