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
from voicebot.lifecycle import AudioLifecycleController, LifecycleState
from voicebot.mock_microphone import MockMicrophone
from voicebot.schemas import AudioChunk, AudioError, AudioFormat
from voicebot.vad import VADResult, VoiceActivityDetector

__all__ = [
    "AudioChunk",
    "AudioChunker",
    "AudioDevice",
    "AudioDeviceAdapter",
    "AudioError",
    "AudioFormat",
    "AudioLifecycleController",
    "BoundedAudioBuffer",
    "BufferStatistics",
    "DropStrategy",
    "LifecycleState",
    "MockAudioDeviceAdapter",
    "MockMicrophone",
    "PermissionState",
    "PipelineDiagnostics",
    "VADResult",
    "VoiceActivityDetector",
    "chunk_audio",
    "collect_diagnostics",
]
