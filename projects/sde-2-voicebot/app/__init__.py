
# Allow access to shared team reasoning modules.
from pathlib import Path

_shared_app = Path(__file__).resolve().parents[3] / "app"

if _shared_app.is_dir():
    if str(_shared_app) not in __path__:
        __path__.append(str(_shared_app))
