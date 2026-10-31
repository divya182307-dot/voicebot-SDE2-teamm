#!/usr/bin/env python3
"""Combined Voicebot demo entry point.

Default: Day 7 chunk-to-transcript streaming demo.
Use --reasoning to run the original Day 2 reasoning demo.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:

 sys.path.insert(0, str(PROJECT_ROOT))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] == "--reasoning":
        from demo_day2 import main as reasoning_main

        reasoning_main()
        return 0

    from scripts.chunk_to_transcript_demo import main as chunk_demo_main

    return chunk_demo_main(args)


if __name__ == "__main__":
    sys.exit(main())
