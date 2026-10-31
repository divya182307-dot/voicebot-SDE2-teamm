#!/usr/bin/env python3
"""Convenience alias for scripts/chunk_to_transcript_demo.py.

Usage:
    python scripts/demo_chunk_to_transcript.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.chunk_to_transcript_demo import main

if __name__ == "__main__":
    sys.exit(main())
