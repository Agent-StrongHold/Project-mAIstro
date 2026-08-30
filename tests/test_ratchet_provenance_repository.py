"""Required-CI proof that every live ratchet has an explicit provenance model (#542).

Runtime execution of delegated trusted-base adapters belongs to the required
Vulture Ratchet workflow, which supplies full git history and the event's actual
integration base. The generic root pytest job intentionally stays structural so
it does not duplicate environment-dependent ratchet execution with a depth-1
checkout and no trusted-base event context.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-ratchet-provenance.py"


def _checker():
    spec = importlib.util.spec_from_file_location("live_ratchet_provenance", CHECKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_every_live_ratchet_has_explicit_provenance() -> None:
    checker = _checker()
    assert checker.violations(ROOT) == []
