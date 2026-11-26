"""Make the suite-local test scaffolding importable by name.

The root pytest config runs with ``--import-mode=importlib``, which performs
no ``sys.path`` insertion: test modules can only import what a normal
interpreter could already resolve, i.e. installed packages. The shared job
store doubles in ``canvas_testing/`` are suite-local scaffolding —
deliberately outside the shipped wheel and outside the production import
graph (the reachability gate counts src modules reachable from entry points
only) — so this conftest puts the suite directory on ``sys.path`` for that
one package name.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SUITE_DIR = Path(__file__).resolve().parent
if str(_SUITE_DIR) not in sys.path:
    sys.path.insert(0, str(_SUITE_DIR))
