# Tests for ObservationManager frame handling

import pytest
from datetime import datetime, timedelta, timezone
from app.observations.manager import ObservationManager
from app.schemas.context import ScreenContext


def make_frame(ts: datetime):
    return ScreenContext(
        application_name="app",
        window_title="win",
        width=800,
        height=600,
        ocr_text="text",
        timestamp=ts,
        visual_elements_summary="summary",
    )

def test_duplicate_frame_detection():
    mgr = ObservationManager()
    mgr.opt_in()
    now = datetime.now(timezone.utc)
    frame = make_frame(now)
    # First ingest should not be duplicate
    obs1 = mgr.ingest_screen_frame(frame)
    assert not mgr._duplicate_frames_detected
    # Second ingest with same content -> duplicate
    obs2 = mgr.ingest_screen_frame(frame)
    assert mgr._duplicate_frames_detected == 1

def test_stale_frame_detection():
    mgr = ObservationManager(freshness_ttl_seconds=1.0)  # 1 second TTL
    mgr.opt_in()
    past = datetime.now(timezone.utc) - timedelta(seconds=2)
    stale_frame = make_frame(past)
    obs = mgr.ingest_screen_frame(stale_frame)
    # Should be marked stale internally (no direct attribute, but counts increment)
    assert mgr._stale_frames_detected == 1
