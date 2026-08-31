from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-branch-independence.py"
spec = importlib.util.spec_from_file_location("_branch_independence_repository", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_every_quality_json_state_surface_is_classified_once():
    base = mod.base_registry(ROOT)
    assert mod.check_repository(ROOT, base=base) == []
