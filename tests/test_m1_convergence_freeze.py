"""Executable evidence for the M1 no-new-islands freeze (#460)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-m1-convergence-freeze.py"
MATRIX = ROOT / "docs" / "architecture" / "CONVERGENCE-MATRIX.md"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m1_convergence_freeze", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _matrix(*subsystems: str) -> str:
    rows = "\n".join(f"| {name} | `example.{index}` |" for index, name in enumerate(subsystems))
    return f"# matrix\n\n<!-- matrix:ownership -->\n| Subsystem | Modules |\n|---|---|\n{rows}\n"


def test_new_subsystem_is_rejected_without_exception() -> None:
    checker = _module()
    current = _matrix("Canonical", "New island")
    base = _matrix("Canonical")

    failures = checker.check(current, base, exception=False)

    assert len(failures) == 1
    assert "New island" in failures[0]
    assert "m1-convergence-exception" in failures[0]


def test_explicit_exception_allows_reviewed_new_subsystem() -> None:
    checker = _module()

    assert (
        checker.check(
            _matrix("Canonical", "Reviewed extension"),
            _matrix("Canonical"),
            exception=True,
        )
        == []
    )


def test_shrinking_the_island_set_is_always_allowed() -> None:
    checker = _module()

    assert (
        checker.check(
            _matrix("Canonical"),
            _matrix("Canonical", "Legacy island"),
            exception=False,
        )
        == []
    )


def test_live_pull_request_does_not_add_unapproved_subsystem() -> None:
    """Make the freeze a real PR gate, not merely a unit-tested policy helper."""
    base_ref = os.environ.get("GITHUB_BASE_REF")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not base_ref or not event_path:
        # Local/push runs still execute the three policy tests above. The live
        # comparison is meaningful only when Actions has checked out a PR and
        # fetched its base ref.
        return

    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    labels = {
        item.get("name", "")
        for item in event.get("pull_request", {}).get("labels", [])
        if isinstance(item, dict)
    }
    command = [
        sys.executable,
        str(CHECKER),
        "--base",
        f"origin/{base_ref}",
    ]
    if "m1-convergence-exception" in labels:
        command.append("--exception")

    subprocess.run(command, cwd=ROOT, check=True)
