"""Mock microphone source for SDE Team 2, Week 1 (Day 3-4).

Generates deterministic fake audio streams and emits AudioChunk objects for offline testing.
"""

from typing import Iterator

from voicebot.chunker import AudioChunker
from voicebot.schemas import AudioChunk, AudioError, AudioFormat


class MockMicrophone:
    """Generate deterministic fake audio chunks for testing.

    Provides a fake microphone source that emits repeatable AudioChunk streams
    with monotonically increasing sequence IDs and accurate timestamps.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_count: int = 5,
        frames_per_chunk: int = 4,
        sample_width: int = 2,
        raw_data: bytes | None = None,
    ):
        """Initialize the mock microphone.

        Args:
            sample_rate (int): Sampling rate in Hz (default: 16000).
            channels (int): Channel count, 1=mono, 2=stereo (default: 1).
            chunk_count (int): Number of chunks to emit when generating synthetic audio (default: 5).
            frames_per_chunk (int): Number of audio frames in each emitted chunk (default: 4).
            sample_width (int): Bytes per sample per channel (default: 2).
            raw_data (bytes, optional): Optional pre-recorded PCM bytes to stream instead
                                        of synthetic pattern.

        Raises:
            ValueError / AudioError: If parameters are invalid.
        """
        if isinstance(chunk_count, bool) or not isinstance(chunk_count, int):
            raise ValueError("Chunk count must be an integer.")
        if chunk_count < 0:
            raise ValueError("Chunk count must be non-negative.")

        if isinstance(frames_per_chunk, bool) or not isinstance(frames_per_chunk, int):
            raise ValueError("Frames per chunk must be an integer.")
        if frames_per_chunk <= 0:
            raise ValueError("Frames per chunk must be greater than 0.")

        self.audio_format = AudioFormat(
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
        )
        self.chunk_count = chunk_count
        self.frames_per_chunk = frames_per_chunk
        self.raw_data = raw_data
        self.chunker = AudioChunker(
            audio_format=self.audio_format,
            frames_per_chunk=frames_per_chunk,
        )

    def stream(self) -> Iterator[AudioChunk]:
        """Yield repeatable audio chunks with increasing sequence IDs.

        Yields:
            AudioChunk: Discrete audio chunks with monotonic sequence IDs and timestamps.
        """
        if self.raw_data is not None:
            yield from self.chunker.chunk_bytes(self.raw_data)
            return

        bytes_per_frame = self.audio_format.bytes_per_frame

        for sequence_id in range(self.chunk_count):
            data = bytes(
                [sequence_id % 256] * bytes_per_frame * self.frames_per_chunk
            )

            yield AudioChunk(
                sequence_id=sequence_id,
                timestamp=sequence_id * self.frames_per_chunk
                / self.audio_format.sample_rate,
                audio_format=self.audio_format,
                data=data,
            )