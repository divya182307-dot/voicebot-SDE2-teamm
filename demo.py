#!/usr/bin/env python3
"""Academia AI Voice Co-Pilot - Speech-to-Text Streaming & Integration Demo.

Top-level launcher for all project demonstration scripts:
  - Week 1 (Day 7):  Chunk-to-Transcript streaming STT demo.
  - Week 2 (Day 14): Synthetic audio fixture & preprocessing contract demo.
  - Week 3 (Day 21): End-to-end integration demo (W1 AudioEvents, revisions,
                     cancellation, mock fallback, W5 BackendEventStream).

Usage:
    python demo.py                        # Default: Week 3 Integration Demo
    python demo.py --week3 [--fast]       # Explicit Week 3 Integration Demo (Day 21)
    python demo.py --week2                # Week 2 Synthetic Fixture Demo (Day 14)
    python demo.py --week1 [--mode single]# Week 1 Streaming Demo (Day 7)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main(argv: list[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]

    # Week 2 flag selector
    if "--week2" in args or "--w2" in args:
        filtered = [a for a in args if a not in ("--week2", "--w2")]
        sys.argv = [sys.argv[0]] + filtered
        from scripts.week2_synthetic_demo import main as week2_main
        return week2_main()

    # Week 3 flag selector
    if "--week3" in args or "--w3" in args:
        filtered = [a for a in args if a not in ("--week3", "--w3")]
        sys.argv = [sys.argv[0]] + filtered
        from scripts.week3_integration_demo import main as week3_main
        return week3_main()

    # Week 1 options (backward compatibility with test_demo.py)
    w1_flags = ("--week1", "--w1", "--mode", "--pace", "--no-color", "--realtime")
    if any(f in args for f in w1_flags):
        filtered = [a for a in args if a not in ("--week1", "--w1")]
        from scripts.chunk_to_transcript_demo import main as week1_main
        return week1_main(filtered)

    # Default: Week 3 Integration Demo
    sys.argv = [sys.argv[0]] + args
    from scripts.week3_integration_demo import main as week3_main
    return week3_main()


if __name__ == "__main__":
    sys.exit(main())
