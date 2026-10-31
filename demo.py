#!/usr/bin/env python3
"""Academia AI Voice Co-Pilot - Chunk-to-Transcript Streaming STT Demo (Day 7 Milestone).

Top-level entrypoint forwarding directly to scripts/chunk_to_transcript_demo.py.

Usage:
    python demo.py
    python demo.py --mode single
    python demo.py --fast
    python demo.py --export-json snapshot.json
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.chunk_to_transcript_demo import main

if __name__ == "__main__":
    sys.exit(main())
