"""Import coverage for integrity pins in ``scripts/vendor_bfcl.py``.

DevSkim same-line suppressions live on the pin literals; diff-coverage still
requires those assignment lines to execute under test.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "vendor_bfcl.py"


def test_wheel_sha256_pin_loads() -> None:
    spec = importlib.util.spec_from_file_location("_vendor_bfcl_pins", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        del sys.modules[spec.name]
    assert isinstance(mod.WHEEL_SHA256, str)
    assert len(mod.WHEEL_SHA256) == 64
