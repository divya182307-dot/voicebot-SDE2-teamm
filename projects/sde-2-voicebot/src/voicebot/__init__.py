"""Voicebot core package for SDE Team 2."""

from voicebot.buffer import BoundedAudioBuffer, BufferStatistics, DropStrategy
from voicebot.chunker import AudioChunker, chunk_audio
from voicebot.device import (
    AudioDevice,
    AudioDeviceAdapter,
    MockAudioDeviceAdapter,
    PermissionState,
)
from voicebot.diagnostics import PipelineDiagnostics, collect_diagnostics
from voicebot.events import (
    AudioEvent,
    AudioFrameEvent,
    EventStatistics,
    EventType,
    SpeechEndedEvent,
    SpeechEventProcessor,
    SpeechStartedEvent,
)
from voicebot.lifecycle import AudioLifecycleController, LifecycleState
from voicebot.mock_microphone import MockMicrophone
from voicebot.normalizer import AudioNormalizer, AudioQualityMetrics
from voicebot.schemas import AudioChunk, AudioError, AudioFormat
from voicebot.transcription_bridge import TranscriptionBridge
from voicebot.vad import VADResult, VoiceActivityDetector

__all__ = [
    "AudioChunk",
    "AudioChunker",
    "AudioDevice",
    "AudioDeviceAdapter",
    "AudioError",
    "AudioEvent",
    "AudioFormat",
    "AudioFrameEvent",
    "AudioLifecycleController",
    "AudioNormalizer",
    "AudioQualityMetrics",
    "BoundedAudioBuffer",
    "BufferStatistics",
    "DropStrategy",
    "EventStatistics",
    "EventType",
    "LifecycleState",
    "MockAudioDeviceAdapter",
    "MockMicrophone",
    "PermissionState",
    "PipelineDiagnostics",
    "SpeechEndedEvent",
    "SpeechEventProcessor",
    "SpeechStartedEvent",
    "TranscriptionBridge",
    "VADResult",
    "VoiceActivityDetector",
    "chunk_audio",
    "collect_diagnostics",
]
