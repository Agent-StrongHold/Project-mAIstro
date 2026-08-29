"""Contract tests for the #542 ratchet-provenance inventory."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-ratchet-provenance.py"


@pytest.fixture(scope="module")
def checker():
    spec = importlib.util.spec_from_file_location("check_ratchet_provenance_under_test", CHECKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _tree(tmp_path: Path, script: str, name: str = "gate.py") -> Path:
    scripts = tmp_path / "scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / name).write_text(script, encoding="utf-8")
    return tmp_path


def test_candidate_controlled_quality_ledger_is_rejected(checker, tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        'from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n'
        'BASELINE = ROOT / "quality" / "debt.json"\n'
        'def load(): return BASELINE.read_text()\n',
    )

    assert checker.violations(root) == [
        "gate.py reads quality/debt.json from the candidate tree without "
        "trusted-base resolution or a documented exception"
    ]


def test_trusted_resolver_satisfies_inventory(checker, tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        'from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n'
        'BASELINE = ROOT / "quality" / "debt.json"\n'
        'import ratchet_provenance\n'
        'def load(): return ratchet_provenance.resolve_baseline(BASELINE)\n',
    )

    assert checker.violations(root) == []


def test_alias_for_quality_directory_is_resolved(checker, tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        'from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n'
        'QUALITY = ROOT / "quality"\nBASELINE = QUALITY / "debt.json"\n',
    )

    found = checker.consumers(root)
    assert checker.Consumer("gate.py", "quality/debt.json") in found


def test_repo_alias_for_quality_directory_is_resolved(checker, tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        'from pathlib import Path\nREPO = Path(__file__).resolve().parents[1]\n'
        'BASELINE = REPO / "quality" / "debt.json"\n',
    )

    assert checker.Consumer("gate.py", "quality/debt.json") in checker.consumers(root)


def test_direct_function_path_expression_is_not_invisible(checker, tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        'from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n'
        'def load():\n    return (ROOT / "quality" / "debt.json").read_text()\n',
    )

    assert checker.Consumer("gate.py", "quality/debt.json") in checker.consumers(root)


def test_documented_candidate_authored_specification_is_allowed(
    checker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _tree(
        tmp_path,
        'from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n'
        'SPEC = ROOT / "quality" / "policy.json"\n',
    )
    monkeypatch.setattr(
        checker,
        "CANDIDATE_AUTHORED",
        {("gate.py", "quality/policy.json"): "the file is the reviewed specification"},
    )
    monkeypatch.setattr(checker, "TRUSTED_ADAPTERS", {})

    assert checker.violations(root) == []


def test_delegated_consumer_requires_a_real_trusted_adapter(
    checker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _tree(
        tmp_path,
        'from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n'
        'BASELINE = ROOT / "quality" / "debt.json"\n',
    )
    monkeypatch.setattr(checker, "CANDIDATE_AUTHORED", {})
    monkeypatch.setattr(
        checker,
        "TRUSTED_ADAPTERS",
        {("gate.py", "quality/debt.json"): "adapter.py"},
    )

    assert checker.violations(root) == [
        "delegated trusted-base adapter adapter.py does not exist"
    ]


def test_delegated_adapter_must_use_shared_resolver(
    checker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _tree(
        tmp_path,
        'from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n'
        'BASELINE = ROOT / "quality" / "debt.json"\n',
    )
    (root / "scripts" / "adapter.py").write_text("def main(): return 0\n", encoding="utf-8")
    monkeypatch.setattr(checker, "CANDIDATE_AUTHORED", {})
    monkeypatch.setattr(
        checker,
        "TRUSTED_ADAPTERS",
        {("gate.py", "quality/debt.json"): "adapter.py"},
    )

    assert checker.violations(root) == [
        "delegated adapter adapter.py does not use ratchet_provenance"
    ]


def test_delegated_adapter_is_executed(
    checker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _tree(
        tmp_path,
        'from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n'
        'BASELINE = ROOT / "quality" / "debt.json"\n',
    )
    (root / "scripts" / "adapter.py").write_text(
        'import ratchet_provenance\n'
        'def probe(): return ratchet_provenance.resolve_baseline(None)\n'
        'def main(): return 7\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(checker, "CANDIDATE_AUTHORED", {})
    monkeypatch.setattr(
        checker,
        "TRUSTED_ADAPTERS",
        {("gate.py", "quality/debt.json"): "adapter.py"},
    )

    assert checker.violations(root) == []
    assert checker.run_delegated(root) == ["adapter.py: trusted-base gate returned 7"]


def test_unparseable_checker_fails_closed(checker, tmp_path: Path) -> None:
    root = _tree(tmp_path, "def (\n")

    with pytest.raises(RuntimeError, match="cannot inventory"):
        checker.consumers(root)
