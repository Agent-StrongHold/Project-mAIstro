from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check-autonomous-merge.py"
SPEC = importlib.util.spec_from_file_location("check_autonomous_merge_policy", SCRIPT)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def cf(path: str, status: str = "M"):
    return mod.ChangedFile(status=status, path=path)


def test_all_quality_policy_inputs_are_trusted() -> None:
    for path in (
        "quality/public-routes.json",
        "quality/security-resource-floors.json",
        "quality/model-egress.json",
    ):
        result = mod.assess([cf(path)], "", head_ref="chatgpt/x")
        assert result.risk == "red" and not result.eligible


def test_folded_notes_baseline_is_evidence_not_policy() -> None:
    # 2026-10-25 migration: ac-state notes (including the _baseline copy) are
    # worker-written verification evidence — yellow and eligible, not trusted
    # policy input. Policy inputs (public-routes, floors, egress) stay RED.
    result = mod.assess(
        [cf("quality/ac-state-notes/_baseline.json")], "", head_ref="chatgpt/x"
    )
    assert result.risk == "yellow" and result.eligible


def test_quality_checker_scripts_are_trusted() -> None:
    for path in (
        "scripts/check-radon-baseline.py",
        "scripts/check-vulture-baseline.py",
        "scripts/check-reachability.py",
    ):
        result = mod.assess([cf(path)], "", head_ref="chatgpt/x")
        assert result.risk == "red" and not result.eligible


def test_imperative_pytest_skip_is_integrity_finding() -> None:
    patch = "+++ b/tests/test_x.py\n+    pytest.skip('disable me')\n"
    result = mod.assess([cf("tests/test_x.py")], patch, head_ref="chatgpt/x")
    assert result.integrity_reasons and not result.eligible


def test_unittest_skip_decorator_is_integrity_finding() -> None:
    patch = "+++ b/tests/test_x.py\n+@unittest.skip('disable me')\n"
    result = mod.assess([cf("tests/test_x.py")], patch, head_ref="chatgpt/x")
    assert result.integrity_reasons and not result.eligible


def test_gitattributes_is_trusted() -> None:
    result = mod.assess([cf(".gitattributes")], "", head_ref="chatgpt/x")
    assert result.risk == "red" and not result.eligible
