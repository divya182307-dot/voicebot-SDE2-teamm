"""Compatibility shim for the src-layout voicebot package.

This project stores the real code under src/voicebot. By exposing that directory as
this package's __path__, imports such as "from voicebot.schemas import ..." work when
running the project from the repository root without requiring an editable install.
"""

from pathlib import Path

_SRC_VOICEBOT = Path(__file__).resolve().parent.parent / "src" / "voicebot"
__path__ = [str(_SRC_VOICEBOT)]

# Re-export the public package API from the real implementation.
try:
    from src.voicebot import *  # type: ignore
except ImportError:  # pragma: no cover
    pass
