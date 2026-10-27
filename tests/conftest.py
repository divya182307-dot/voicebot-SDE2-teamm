"""Pytest configuration and fixtures for the Voicebot project."""

import os
import sys

import pytest

# Ensure projects/sde-2-voicebot is on sys.path.
current_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.abspath(os.path.join(current_dir, ".."))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

from src.voice.accumulator import SegmentAccumulator
from src.voice.fixtures import (
    duplicate_final_events,
    error_event_stream,
    multi_utterance_events,
    out_of_order_final_events,
    single_utterance_events,
)


@pytest.fixture
def accumulator() -> SegmentAccumulator:
    """Provide a fresh SegmentAccumulator instance."""
    return SegmentAccumulator()


@pytest.fixture
def single_turn_stream():
    """Provide a single-turn speech event stream."""
    return single_utterance_events("session-single-turn")


@pytest.fixture
def multi_turn_stream():
    """Provide a multi-turn speech event stream."""
    return multi_utterance_events("session-multi-turn")


@pytest.fixture
def out_of_order_stream():
    """Provide an out-of-order event stream to test sorting."""
    return out_of_order_final_events("session-ooo")


@pytest.fixture
def duplicate_events_stream():
    """Provide duplicate events to test deduplication."""
    return duplicate_final_events("session-dup")


@pytest.fixture
def error_stream():
    """Provide an event stream with an error event."""
    return error_event_stream("session-err")
