#!/usr/bin/env python3
"""Entry point for the ratchet-provenance inventory (#542).

The logic lives in `check_ratchet_provenance_impl.py` because a filename with
hyphens is not an importable module name, and `scripts/` is a measured
diff-coverage root (#257) — so the gate has to arrive with tests that can reach
it by import rather than by subprocess.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_ratchet_provenance_impl import main

if __name__ == "__main__":
    sys.exit(main())
