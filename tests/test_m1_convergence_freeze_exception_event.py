"""Exception-plan event fallback for the M1 convergence freeze (#460)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-m1-convergence-freeze.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m1_convergence_freeze_event", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_direct_checker_reads_exception_plan_from_pull_request_event(
    tmp_path: Path, monkeypatch
) -> None:
    checker = _module()
    plan = "\n".join(
        (
            "Architecture rationale: reviewed extension",
            "Canonical owner: maistro.runs remains authoritative",
            "Disposition owner: #460",
            "Retirement/convergence path: retire after the canonical seam grows",
        )
    )
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"body": plan}}), encoding="utf-8")
    monkeypatch.delenv("M1_CONVERGENCE_EXCEPTION_PLAN", raising=False)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))

    assert checker._exception_plan_from_environment() == plan
