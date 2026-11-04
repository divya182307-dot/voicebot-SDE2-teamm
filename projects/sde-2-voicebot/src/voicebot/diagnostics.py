"""Pipeline diagnostics and health monitoring for SDE Team 2, Week 2 (Day 14).

This module provides a unified telemetry snapshot of the audio capture pipeline:
- PipelineDiagnostics: Immutable snapshot aggregating device state, lifecycle state,
  VAD classification metrics, buffer occupancy, dropped-chunk counts, and overall health.
"""

from dataclasses import dataclass

from voicebot.buffer import BoundedAudioBuffer
from voicebot.lifecycle import AudioLifecycleController
from voicebot.vad import VoiceActivityDetector


@dataclass(frozen=True)
class PipelineDiagnostics:
    """Comprehensive telemetry snapshot of the audio capture pipeline.

    Fields:
        device_id: Identifier of active audio device.
        device_name: Display name of active audio device.
        permission_state: Current permission state (e.g. GRANTED, DENIED).
        lifecycle_state: Current lifecycle state (e.g. RECORDING, PAUSED, STOPPED).
        session_id: Active session UUID or None.
        chunks_emitted: Chunks emitted while in RECORDING state.
        chunks_suppressed: Chunks suppressed while in PAUSED state.
        buffer_occupancy: Current number of chunks queued in bounded buffer.
        buffer_max_chunks: Maximum capacity of bounded buffer.
        buffer_occupancy_ratio: Fill fraction between 0.0 and 1.0.
        dropped_chunk_counter: Total chunks dropped due to buffer overflow.
        is_backpressure_active: Whether backpressure threshold has been reached.
        gaps_detected: Count of detected sequence gaps.
        late_chunks_detected: Count of out-of-order chunks.
        total_speech_chunks: Count of chunks classified as speech by VAD.
        total_silence_chunks: Count of chunks classified as silence/noise by VAD.
        speech_ratio_percent: Percentage of processed frames classified as speech.
        is_healthy: True if permission is granted, lifecycle not in ERROR, and no overflows.
    """

    device_id: str
    device_name: str
    permission_state: str
    lifecycle_state: str
    session_id: str | None
    chunks_emitted: int
    chunks_suppressed: int
    buffer_occupancy: int
    buffer_max_chunks: int
    buffer_occupancy_ratio: float
    dropped_chunk_counter: int
    is_backpressure_active: bool
    gaps_detected: int
    late_chunks_detected: int
    total_speech_chunks: int
    total_silence_chunks: int
    speech_ratio_percent: float
    is_healthy: bool


def collect_diagnostics(
    controller: AudioLifecycleController,
    buffer: BoundedAudioBuffer | None = None,
    vad: VoiceActivityDetector | None = None,
) -> PipelineDiagnostics:
    """Collect an immutable telemetry snapshot across pipeline components.

    Args:
        controller: Active or initialized AudioLifecycleController.
        buffer: Optional BoundedAudioBuffer instance.
        vad: Optional VoiceActivityDetector instance.

    Returns:
        PipelineDiagnostics: Aggregated health and performance snapshot.
    """
    device = controller.adapter.get_selected_device()
    perm_state = controller.adapter.get_permission_state().value
    life_state = controller.state.value

    # Buffer metrics
    if buffer is not None:
        stats = buffer.get_stats()
        buf_occ = stats.current_occupancy
        buf_max = stats.max_chunks
        buf_ratio = stats.occupancy_ratio
        dropped_count = stats.dropped_chunk_counter
        bp_active = stats.is_backpressure_active
        gaps = stats.gaps_detected
        late = stats.late_chunks_detected
    else:
        buf_occ = 0
        buf_max = 0
        buf_ratio = 0.0
        dropped_count = 0
        bp_active = False
        gaps = 0
        late = 0

    # VAD metrics
    if vad is not None:
        speech_chunks = vad.total_speech_chunks
        silence_chunks = vad.total_silence_chunks
        total_chunks = speech_chunks + silence_chunks
        speech_ratio = round((speech_chunks / total_chunks * 100.0), 2) if total_chunks > 0 else 0.0
    else:
        speech_chunks = 0
        silence_chunks = 0
        speech_ratio = 0.0

    # Overall health evaluation
    is_healthy = (
        perm_state == "GRANTED"
        and life_state != "ERROR"
        and dropped_count == 0
        and not bp_active
    )

    return PipelineDiagnostics(
        device_id=device.device_id,
        device_name=device.name,
        permission_state=perm_state,
        lifecycle_state=life_state,
        session_id=controller.session_id,
        chunks_emitted=controller.chunks_emitted,
        chunks_suppressed=controller.chunks_suppressed,
        buffer_occupancy=buf_occ,
        buffer_max_chunks=buf_max,
        buffer_occupancy_ratio=buf_ratio,
        dropped_chunk_counter=dropped_count,
        is_backpressure_active=bp_active,
        gaps_detected=gaps,
        late_chunks_detected=late,
        total_speech_chunks=speech_chunks,
        total_silence_chunks=silence_chunks,
        speech_ratio_percent=speech_ratio,
        is_healthy=is_healthy,
    )

