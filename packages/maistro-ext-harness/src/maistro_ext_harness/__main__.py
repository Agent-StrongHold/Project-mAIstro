"""`python -m maistro_ext_harness` — the same CLI as the console script."""

from __future__ import annotations

import sys

from maistro_ext_harness.cli import main

if __name__ == "__main__":  # pragma: no cover - exercised via subprocess in tests
    sys.exit(main())
