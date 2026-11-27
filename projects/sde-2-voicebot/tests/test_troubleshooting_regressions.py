"""Regression test fixtures and tests for device troubleshooting scenarios (Week 4, Days 28-29).

Validates all documented hardware failure modes, permission states, mid-stream disconnects,
fallback auto-reconnections, buffer overflows, and cancellation recovery paths from
docs/DEVICE_TROUBLESHOOTING.md.

All tests operate 100% in-memory using deterministic synthetic audio (PRD Section 19 compliance).
"""

from __future__ import annotations

import math
import struct
import pytest

from voicebot.buffer import BoundedAudioBuffer, DropStrategy
from voicebot.device import (
    AudioDevice,
    AudioDeviceAdapter,
    MockAudioDeviceAdapter,
    PermissionState,
)
from voicebot.events import EventType, SpeechEventProcessor
from voicebot.lifecycle import AudioLifecycleController, LifecycleState
from voicebot.normalizer import AudioNormalizer
from voicebot.schemas import AudioChunk, AudioError, AudioFormat
from voicebot.vad import VoiceActivityDetector


# =============================================================================
# Pytest Fixtures for Troubleshooting Regressions
# =============================================================================

@pytest.fixture
def standard_format() -> AudioFormat:
    """Standard 16kHz mono 16-bit PCM format."""
    return AudioFormat(sample_rate=16000, channels=1, sample_width=2)


@pytest.fixture
def primary_usb_mic() -> AudioDevice:
    """Simulated primary USB microphone."""
    return AudioDevice(
        device_id="usb-primary-mic",
        name="USB Studio Condenser Mic",
        channels=1,
        default_sample_rate=16000,
        is_default=False,
        sample_width=2,
    )


@pytest.fixture
def fallback_builtin_mic() -> AudioDevice:
    """Simulated fallback built-in microphone."""
    return AudioDevice(
        device_id="builtin-fallback-mic",
        name="System Default Built-in Mic",
        channels=1,
        default_sample_rate=16000,
        is_default=True,
        sample_width=2,
    )


@pytest.fixture
def dual_device_adapter(
    primary_usb_mic: AudioDevice,
    fallback_builtin_mic: AudioDevice,
) -> MockAudioDeviceAdapter:
    """Mock adapter initialized with both primary USB and fallback built-in microphones."""
    adapter = MockAudioDeviceAdapter(
        devices=[primary_usb_mic, fallback_builtin_mic],
        initial_permission=PermissionState.GRANTED,
    )
    adapter.select_device("usb-primary-mic")
    return adapter


@pytest.fixture
def clean_controller(dual_device_adapter: MockAudioDeviceAdapter) -> AudioLifecycleController:
    """Lifecycle controller with auto-recovery enabled."""
    return AudioLifecycleController(
        adapter=dual_device_adapter,
        max_reconnect_attempts=3,
        reconnect_delay_seconds=0.0,
        auto_reconnect=True,
    )


def make_synthetic_chunk(
    seq: int,
    fmt: AudioFormat,
    amplitude: float = 0.35,
    duration_ms: int = 20,
) -> AudioChunk:
    """Generate a deterministic synthetic audio chunk."""
    frame_count = int(fmt.sample_rate * (duration_ms / 1000.0))
    samples: list[int] = []
    freq = 440.0

    for i in range(frame_count):
        if amplitude > 0.0:
            val = int(amplitude * 32767.0 * math.sin(2.0 * math.pi * freq * (i / fmt.sample_rate)))
        else:
            val = 0
        samples.append(max(-32768, min(32767, val)))

    raw_data = struct.pack(f"<{len(samples)}h", *samples)
    return AudioChunk(
        sequence_id=seq,
        timestamp=float(seq * duration_ms) / 1000.0,
        audio_format=fmt,
        data=raw_data,
    )


# =============================================================================
# Regression Tests: Scenario 1 - Device Enumeration & Detection Failures
# =============================================================================

class TestDeviceDetectionRegressions:
    """Regression tests for Scenario 1: Device enumeration, schema, and selection failures."""

    def test_regression_no_devices_available_raises_clean_error(self) -> None:
        """Verify requesting default device when devices list is empty raises clean AudioError."""
        adapter = MockAudioDeviceAdapter(
            devices=[],
            initial_permission=PermissionState.GRANTED,
        )
        assert adapter.list_devices() == []

        with pytest.raises(AudioError) as exc_info:
            adapter.get_default_device()
        assert "No audio devices available" in str(exc_info.value)

    def test_regression_device_selection_unknown_id_raises_clean_error(
        self,
        dual_device_adapter: MockAudioDeviceAdapter,
    ) -> None:
        """Verify selecting a non-existent device ID raises AudioError with helpful message."""
        with pytest.raises(AudioError) as exc_info:
            dual_device_adapter.select_device("ghost-device-999")
        assert "not found" in str(exc_info.value)

    def test_regression_invalid_device_schema_parameters_raise_audio_error(self) -> None:
        """Verify AudioDevice enforces non-empty string IDs, names, and valid channel numbers."""
        # Blank device_id
        with pytest.raises(AudioError):
            AudioDevice(device_id="", name="Valid Name", channels=1, default_sample_rate=16000)

        # Blank name
        with pytest.raises(AudioError):
            AudioDevice(device_id="mic-1", name="   ", channels=1, default_sample_rate=16000)

        # Invalid channels (e.g. 0 or 3)
        with pytest.raises(AudioError):
            AudioDevice(device_id="mic-1", name="Mic", channels=0, default_sample_rate=16000)

        # Invalid sample rate (<= 0)
        with pytest.raises(AudioError):
            AudioDevice(device_id="mic-1", name="Mic", channels=1, default_sample_rate=0)


# =============================================================================
# Regression Tests: Scenario 2 - Permission Denials & Revocations
# =============================================================================

class TestPermissionTroubleshootingRegressions:
    """Regression tests for Scenario 2: Permission states, PROMPT handling, and mid-stream denial."""

    def test_regression_initial_permission_denied_aborts_start(self) -> None:
        """Verify controller.start() raises AudioError and enters ERROR state when DENIED."""
        adapter = MockAudioDeviceAdapter(initial_permission=PermissionState.DENIED)
        controller = AudioLifecycleController(adapter)

        with pytest.raises(AudioError) as exc_info:
            controller.start()

        assert "Microphone permission denied" in str(exc_info.value)
        assert controller.state == LifecycleState.ERROR

    def test_regression_permission_prompt_auto_requests_permission(self) -> None:
        """Verify controller in PROMPT state auto-requests permission upon start()."""
        adapter = MockAudioDeviceAdapter(
            initial_permission=PermissionState.PROMPT,
            permission_response=PermissionState.GRANTED,
        )
        controller = AudioLifecycleController(adapter)

        # Starting capture should automatically trigger request_permission() and transition to RECORDING
        controller.start()
        assert controller.state == LifecycleState.RECORDING
        assert adapter.get_permission_state() == PermissionState.GRANTED
        controller.stop()

    def test_regression_midstream_permission_revocation_halts_capture(self) -> None:
        """Verify permission dynamically changed to DENIED halts capture and enters ERROR state."""
        adapter = MockAudioDeviceAdapter(initial_permission=PermissionState.GRANTED)
        controller = AudioLifecycleController(adapter)
        controller.start()

        stream = controller.capture_stream(chunk_count=5, frames_per_chunk=4)
        _ = next(stream)

        # Simulate user or OS revoking permission mid-recording
        adapter.set_permission_state(PermissionState.DENIED)

        with pytest.raises(AudioError) as exc_info:
            _ = next(stream)

        assert "Microphone permission denied" in str(exc_info.value) or "DENIED" in str(exc_info.value)
        assert controller.state == LifecycleState.ERROR


# =============================================================================
# Regression Tests: Scenario 3 - Mid-Stream Disconnect & Recovery
# =============================================================================

class TestDeviceDisconnectAndRecoveryRegressions:
    """Regression tests for Scenario 3: Mid-stream hardware unplug and fallback recovery."""

    def test_regression_midstream_device_disconnect_auto_reconnects_to_fallback(
        self,
        clean_controller: AudioLifecycleController,
        dual_device_adapter: MockAudioDeviceAdapter,
    ) -> None:
        """Verify active stream detects disconnection, reconnects to fallback, and emits all chunks."""
        clean_controller.start()
        original_session = clean_controller.session_id

        # Simulate disconnect after 2 chunks
        dual_device_adapter.simulate_disconnect_after(2)

        stream = clean_controller.capture_stream(chunk_count=6, frames_per_chunk=4)
        chunks = list(stream)

        assert len(chunks) == 6
        assert clean_controller.chunks_emitted == 6
        assert clean_controller.successful_reconnects == 1
        assert clean_controller.last_recovery_device == "builtin-fallback-mic"
        assert clean_controller.session_id == original_session
        assert clean_controller.state == LifecycleState.RECORDING

        clean_controller.stop()

    def test_regression_reconnect_failure_exhaustion_halts_cleanly(self) -> None:
        """Verify device loss when 0 fallback devices remain halts cleanly in ERROR state."""
        single_mic = AudioDevice(
            device_id="solo-mic",
            name="Solo USB Mic",
            channels=1,
            default_sample_rate=16000,
            is_default=True,
        )
        adapter = MockAudioDeviceAdapter(devices=[single_mic], initial_permission=PermissionState.GRANTED)
        controller = AudioLifecycleController(adapter, max_reconnect_attempts=2, auto_reconnect=True)
        controller.start()

        # Simulate disconnect and wipe all remaining devices
        adapter.simulate_disconnect_after(1)
        adapter.set_devices([])

        with pytest.raises(AudioError) as exc_info:
            list(controller.capture_stream(chunk_count=4, frames_per_chunk=4))

        assert "Audio capture aborted" in str(exc_info.value)
        assert controller.state == LifecycleState.ERROR


# =============================================================================
# Regression Tests: Scenario 4 - Buffer Overflow & Ingestion Backpressure
# =============================================================================

class TestBufferBackpressureRegressions:
    """Regression tests for Scenario 4: Bounded buffer overflow, strategies, and backpressure signals."""

    def test_regression_buffer_backpressure_watermark_80_percent(
        self,
        standard_format: AudioFormat,
    ) -> None:
        """Verify buffer backpressure activates at exactly 80% occupancy and clears on pull."""
        buffer = BoundedAudioBuffer(max_chunks=10, high_water_mark=0.8)
        assert buffer.is_backpressure_active is False

        # Push 7 chunks (70% < 80%)
        for i in range(7):
            buffer.push(make_synthetic_chunk(i, standard_format))
        assert buffer.is_backpressure_active is False

        # Push 8th chunk (80% >= 80%)
        buffer.push(make_synthetic_chunk(7, standard_format))
        assert buffer.is_backpressure_active is True

        # Pull 1 chunk (70% < 80%)
        _ = buffer.pull()
        assert buffer.is_backpressure_active is False

    def test_regression_buffer_drop_oldest_preserves_latest_speech(
        self,
        standard_format: AudioFormat,
    ) -> None:
        """Verify DROP_OLDEST keeps the freshest speech chunks at buffer overflow."""
        buffer = BoundedAudioBuffer(max_chunks=5, drop_strategy=DropStrategy.DROP_OLDEST)

        # Push 10 chunks (0..9)
        for i in range(10):
            buffer.push(make_synthetic_chunk(i, standard_format))

        assert buffer.current_occupancy == 5
        assert buffer.dropped_chunk_counter == 5

        # Oldest retained chunk should be chunk sequence 5 (chunks 5, 6, 7, 8, 9 retained)
        retained = buffer.pull_all()
        assert [c.sequence_id for c in retained] == [5, 6, 7, 8, 9]

    def test_regression_buffer_drop_newest_preserves_earliest_speech(
        self,
        standard_format: AudioFormat,
    ) -> None:
        """Verify DROP_NEWEST keeps the earliest speech chunks at buffer overflow."""
        buffer = BoundedAudioBuffer(max_chunks=5, drop_strategy=DropStrategy.DROP_NEWEST)

        # Push 10 chunks (0..9)
        for i in range(10):
            buffer.push(make_synthetic_chunk(i, standard_format))

        assert buffer.current_occupancy == 5
        assert buffer.dropped_chunk_counter == 5

        # Retained chunks should be the first 5 (chunks 0, 1, 2, 3, 4)
        retained = buffer.pull_all()
        assert [c.sequence_id for c in retained] == [0, 1, 2, 3, 4]

    def test_regression_buffer_reject_new_raises_overflow_error(
        self,
        standard_format: AudioFormat,
    ) -> None:
        """Verify REJECT_NEW raises AudioError when buffer capacity is exceeded."""
        buffer = BoundedAudioBuffer(max_chunks=3, drop_strategy=DropStrategy.REJECT_NEW)

        for i in range(3):
            buffer.push(make_synthetic_chunk(i, standard_format))

        with pytest.raises(AudioError) as exc_info:
            buffer.push(make_synthetic_chunk(3, standard_format))

        assert "Audio buffer overflow: reached capacity of 3 chunks" in str(exc_info.value)


# =============================================================================
# Regression Tests: Scenario 5 - Frame Alignment & Audio Artifact Robustness
# =============================================================================

class TestFrameAlignmentAndArtifactRegressions:
    """Regression tests for Scenario 5: Frame misalignment rejection and acoustic normalization safety."""

    def test_regression_corrupted_frame_alignment_rejected(
        self,
        standard_format: AudioFormat,
    ) -> None:
        """Verify AudioChunk rejects byte buffers that are not multiples of bytes_per_frame."""
        # 16-bit mono requires 2 bytes per frame; 321 bytes is misaligned
        bad_data = b"\x00" * 321

        with pytest.raises(AudioError) as exc_info:
            AudioChunk(
                sequence_id=0,
                timestamp=0.0,
                audio_format=standard_format,
                data=bad_data,
            )

        assert "complete audio frames" in str(exc_info.value)

    def test_regression_digital_silence_normalizer_safety(
        self,
        standard_format: AudioFormat,
    ) -> None:
        """Verify pure digital silence normalizes safely without division-by-zero or NaN."""
        normalizer = AudioNormalizer(target_peak=0.95)
        silence_chunk = make_synthetic_chunk(0, standard_format, amplitude=0.0)

        norm_chunk = normalizer.normalize_chunk(silence_chunk)
        assert norm_chunk.sequence_id == silence_chunk.sequence_id
        assert len(norm_chunk.data) == len(silence_chunk.data)

        # Energy of silence should remain 0.0
        vad = VoiceActivityDetector()
        vad_res = vad.process_chunk(norm_chunk)
        assert vad_res.energy_score == 0.0
        assert vad_res.is_speech is False

    def test_regression_extreme_clipping_normalizer_safety(
        self,
        standard_format: AudioFormat,
    ) -> None:
        """Verify heavily clipped full-scale square wave normalizes without distortion or crash."""
        normalizer = AudioNormalizer(target_peak=0.95)
        # Full scale alternating ±32767 square wave
        samples = [32767 if i % 2 == 0 else -32768 for i in range(320)]
        raw_data = struct.pack(f"<{len(samples)}h", *samples)
        clipped_chunk = AudioChunk(
            sequence_id=1,
            timestamp=0.02,
            audio_format=standard_format,
            data=raw_data,
        )

        norm_chunk = normalizer.normalize_chunk(clipped_chunk)
        assert len(norm_chunk.data) == len(clipped_chunk.data)
        metrics = normalizer.analyze_quality(norm_chunk)
        assert metrics is not None
        assert metrics.peak_amplitude <= 1.0


# =============================================================================
# Regression Tests: Scenario 6 - Barge-In Cancellation & Memory Purge
# =============================================================================

class TestBargeInCancellationRegressions:
    """Regression tests for Scenario 6: User interruption (barge-in) and buffer purge."""

    def test_regression_barge_in_cancellation_purges_buffer_and_resets_processor(
        self,
        clean_controller: AudioLifecycleController,
        standard_format: AudioFormat,
    ) -> None:
        """Verify cancel(buffer=..., processor=...) immediately terminates capture and clears memory."""
        clean_controller.start()
        assert clean_controller.state == LifecycleState.RECORDING

        buffer = BoundedAudioBuffer(max_chunks=20)
        vad = VoiceActivityDetector(energy_threshold=0.02)
        processor = SpeechEventProcessor(vad=vad, session_id=clean_controller.session_id)

        # Feed 5 active speech chunks
        for i in range(5):
            chunk = make_synthetic_chunk(i, standard_format, amplitude=0.4)
            buffer.push(chunk)
            _ = processor.process_chunk(chunk)

        assert buffer.current_occupancy == 5
        assert processor.is_in_speech is True

        # User interrupts / barge-in: cancel immediately
        clean_controller.cancel(buffer=buffer, processor=processor)

        assert clean_controller.state == LifecycleState.CANCELLED
        assert clean_controller.is_cancelled is True
        assert buffer.current_occupancy == 0
        assert buffer.pull() is None
        assert processor.is_in_speech is False
        assert processor.active_correlation_id is None
