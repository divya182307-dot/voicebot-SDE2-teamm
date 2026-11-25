"""Deterministic audio chunker for SDE Team 2, Week 1 (Day 3-4).

Splits raw audio streams or byte buffers into sequential, deterministic AudioChunk objects.
"""

import math
from typing import Iterable, Iterator

from voicebot.schemas import AudioChunk, AudioError, AudioFormat


class AudioChunker:
    """Deterministic chunker that segments raw PCM audio into AudioChunk objects.

    Guarantees:
        - Determinism: Given the same input data and configuration, emits identical chunks every run.
        - Monotonicity: Emits strictly increasing sequence IDs (0, 1, 2, ...).
        - Accurate Timing: Emits exact timestamps reflecting cumulative audio duration.
        - Frame Alignment: Guarantees every chunk contains an integer number of complete frames.
    """

    def __init__(
        self,
        audio_format: AudioFormat,
        frames_per_chunk: int,
    ):
        """Initialize the audio chunker.

        Args:
            audio_format (AudioFormat): Format metadata for the audio stream.
            frames_per_chunk (int): Number of complete audio frames per chunk; must be > 0.

        Raises:
            AudioError: If audio_format is invalid or frames_per_chunk <= 0.
        """
        if not isinstance(audio_format, AudioFormat):
            raise AudioError("audio_format must be an AudioFormat instance.")
        if isinstance(frames_per_chunk, bool) or not isinstance(frames_per_chunk, int):
            raise AudioError("frames_per_chunk must be an integer.")
        if frames_per_chunk <= 0:
            raise AudioError("frames_per_chunk must be greater than 0.")

        self.audio_format = audio_format
        self.frames_per_chunk = frames_per_chunk
        self.bytes_per_chunk = frames_per_chunk * audio_format.bytes_per_frame
        self.chunk_duration = frames_per_chunk / audio_format.sample_rate

    @staticmethod
    def _validate_timing_params(start_sequence_id: int, start_timestamp: float) -> None:
        """Validate start sequence ID and timestamp parameters.

        Raises:
            AudioError: If types or value constraints are violated.
        """
        if isinstance(start_sequence_id, bool) or not isinstance(start_sequence_id, int):
            raise AudioError("start_sequence_id must be an integer.")
        if start_sequence_id < 0:
            raise AudioError("start_sequence_id must be non-negative.")
        if isinstance(start_timestamp, bool) or not isinstance(start_timestamp, (int, float)):
            raise AudioError("start_timestamp must be a number in seconds.")
        if not math.isfinite(start_timestamp):
            raise AudioError("start_timestamp must be finite.")
        if start_timestamp < 0:
            raise AudioError("start_timestamp must be non-negative.")

    def chunk_bytes(
        self,
        raw_audio: bytes,
        start_sequence_id: int = 0,
        start_timestamp: float = 0.0,
        allow_partial_chunk: bool = True,
    ) -> Iterator[AudioChunk]:
        """Split a raw audio byte buffer into deterministic AudioChunk instances.

        Args:
            raw_audio (bytes): Raw PCM audio data.
            start_sequence_id (int): Initial sequence ID (default: 0).
            start_timestamp (float): Initial timestamp in seconds (default: 0.0).
            allow_partial_chunk (bool): If True, emits remaining complete frames as a final
                                        chunk. If False, discards incomplete trailing frames.

        Yields:
            AudioChunk: Discrete audio chunks with monotonic sequence IDs and timestamps.

        Raises:
            AudioError: If raw_audio is not bytes, sequence ID/timestamp is invalid,
                        or data length is not a multiple of bytes_per_frame.
        """
        if not isinstance(raw_audio, bytes):
            raise AudioError("raw_audio must be bytes.")
        self._validate_timing_params(start_sequence_id, start_timestamp)

        # Empty data yields no chunks
        if not raw_audio:
            return

        bytes_per_frame = self.audio_format.bytes_per_frame
        if len(raw_audio) % bytes_per_frame != 0:
            raise AudioError("Audio data size must contain complete audio frames.")

        total_bytes = len(raw_audio)
        current_seq = start_sequence_id
        offset = 0
        frames_emitted = 0

        while offset < total_bytes:
            chunk_slice = raw_audio[offset : offset + self.bytes_per_chunk]
            offset += len(chunk_slice)

            if len(chunk_slice) < self.bytes_per_chunk and not allow_partial_chunk:
                break

            current_time = start_timestamp + (frames_emitted / self.audio_format.sample_rate)
            chunk = AudioChunk(
                sequence_id=current_seq,
                timestamp=current_time,
                audio_format=self.audio_format,
                data=chunk_slice,
            )
            yield chunk

            current_seq += 1
            frames_emitted += chunk.frame_count

    def chunk_stream(
        self,
        stream: Iterable[bytes],
        start_sequence_id: int = 0,
        start_timestamp: float = 0.0,
        allow_partial_chunk: bool = True,
    ) -> Iterator[AudioChunk]:
        """Split a stream of arbitrary-sized byte buffers into uniform AudioChunks.

        Args:
            stream (Iterable[bytes]): Generator or iterable yielding raw audio bytes.
            start_sequence_id (int): Initial sequence ID (default: 0).
            start_timestamp (float): Initial timestamp in seconds (default: 0.0).
            allow_partial_chunk (bool): If True, emits remaining complete frames when stream ends.

        Yields:
            AudioChunk: Discrete audio chunks.

        Raises:
            AudioError: If parameters are invalid, or streamed data contains non-bytes or frame misalignment.
        """
        self._validate_timing_params(start_sequence_id, start_timestamp)
        buffer = bytearray()
        bytes_per_frame = self.audio_format.bytes_per_frame
        current_seq = start_sequence_id
        frames_emitted = 0

        for packet in stream:
            if not isinstance(packet, (bytes, bytearray)):
                raise AudioError("Stream packets must be bytes or bytearray.")
            buffer.extend(packet)

            while len(buffer) >= self.bytes_per_chunk:
                chunk_data = bytes(buffer[: self.bytes_per_chunk])
                del buffer[: self.bytes_per_chunk]

                current_time = start_timestamp + (frames_emitted / self.audio_format.sample_rate)
                chunk = AudioChunk(
                    sequence_id=current_seq,
                    timestamp=current_time,
                    audio_format=self.audio_format,
                    data=chunk_data,
                )
                yield chunk

                current_seq += 1
                frames_emitted += self.frames_per_chunk

        # Handle remaining buffer at end of stream
        if buffer and allow_partial_chunk:
            if len(buffer) % bytes_per_frame != 0:
                raise AudioError("Trailing stream data contains incomplete audio frames.")
            chunk_data = bytes(buffer)
            current_time = start_timestamp + (frames_emitted / self.audio_format.sample_rate)
            chunk = AudioChunk(
                sequence_id=current_seq,
                timestamp=current_time,
                audio_format=self.audio_format,
                data=chunk_data,
            )
            yield chunk


def chunk_audio(
    raw_audio: bytes,
    audio_format: AudioFormat,
    frames_per_chunk: int,
    start_sequence_id: int = 0,
    start_timestamp: float = 0.0,
) -> Iterator[AudioChunk]:
    """Convenience helper function to deterministically chunk raw audio bytes.

    Args:
        raw_audio (bytes): Raw PCM audio bytes.
        audio_format (AudioFormat): Audio format configuration.
        frames_per_chunk (int): Number of audio frames per chunk.
        start_sequence_id (int): Initial sequence ID.
        start_timestamp (float): Initial timestamp in seconds.

    Returns:
        Iterator[AudioChunk]: Deterministic audio chunk iterator.
    """
    chunker = AudioChunker(audio_format=audio_format, frames_per_chunk=frames_per_chunk)
    return chunker.chunk_bytes(
        raw_audio=raw_audio,
        start_sequence_id=start_sequence_id,
        start_timestamp=start_timestamp,
    )
