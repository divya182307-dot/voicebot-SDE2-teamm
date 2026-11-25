# Tests for ObservationManager core behaviours

import pytest
from app.observations.manager import ObservationManager
from app.vision.capture_adapter import CaptureNotAuthorizedException


def test_opt_in_and_withdraw():
    mgr = ObservationManager()
    # Initially consent is OFF
    assert not mgr.is_consent_active
    token = mgr.opt_in()
    assert mgr.is_consent_active
    assert isinstance(token, str)
    # Withdraw consent clears buffers
    mgr.withdraw_consent()
    assert not mgr.is_consent_active
    # After withdrawal, attempting to ingest should raise
    with pytest.raises(CaptureNotAuthorizedException):
        class DummyFrame:
            application_name = "app"
            window_title = "win"
            width = 800
            height = 600
            ocr_text = ""
            timestamp = None
        mgr.ingest_screen_frame(DummyFrame())
