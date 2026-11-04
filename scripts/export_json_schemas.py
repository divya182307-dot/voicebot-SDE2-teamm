"""Utility script to export Pydantic data contracts as standard JSON Schema files.

This enables the Frontend/Desktop UI team to generate TypeScript interfaces
and the Backend team to import schema contracts directly.
"""

import json
from pathlib import Path

from src.voice.accumulator import AccumulatedTranscript, AccumulatorConfig
from src.voice.adapter import AudioConfig, TranscriberConfig
from src.voice.fake_transcriber import FakeUtterance
from src.voice.schemas import (
    TranscriptError,
    TranscriptEvent,
    TranscriptSegment,
    WordTiming,
)


def export_schemas():
    output_dir = Path("schemas")
    output_dir.mkdir(parents=True, exist_ok=True)

    models = {
        "word_timing.json": WordTiming,
        "transcript_segment.json": TranscriptSegment,
        "transcript_error.json": TranscriptError,
        "transcript_event.json": TranscriptEvent,
        "audio_config.json": AudioConfig,
        "transcriber_config.json": TranscriberConfig,
        "fake_utterance.json": FakeUtterance,
        "accumulator_config.json": AccumulatorConfig,
        "accumulated_transcript.json": AccumulatedTranscript,
    }

    for filename, model in models.items():
        file_path = output_dir / filename
        schema_dict = model.model_json_schema()
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(schema_dict, f, indent=2)
        print(f"Exported {filename} -> {file_path}")


if __name__ == "__main__":
    export_schemas()
