"""Regression coverage for mutation-baseline bootstrap behavior."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_mutation_baseline.py"


@pytest.fixture(scope="module")
def module():
    spec = importlib.util.spec_from_file_location("_mutation_baseline", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        del sys.modules[spec.name]
        raise
    yield mod
    del sys.modules[spec.name]


def _rows(path: Path, source: str, *, killed: int, survived: int) -> None:
    """Write Cosmic Ray dump JSONL: one [work_item, outcome] pair per mutant."""
    lines = [
        json.dumps([{"mutations": [{"module_path": source}]}, {"test_outcome": outcome}])
        for outcome in ["killed"] * killed + ["survived"] * survived
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_unbaselined_source_below_the_global_floor_now_fails(
    module, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The global floor applies to every measured source, reviewed or not.

    This used to pass with a "no entry" report: an unbaselined source was
    measured and then exempted. That is the gap this ratchet closes — a brand
    new file could sit at any kill rate indefinitely, because it had no
    recorded rate to regress from.
    """
    rows = tmp_path / "rows.jsonl"
    _rows(rows, "packages/example.py", killed=0, survived=1)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        '{"entries": {"packages/already-covered.py": {"kill_rate": 0.95}}}\n',
        encoding="utf-8",
    )

    assert module.main([str(rows), "--baseline", str(baseline)]) == 1
    assert "below required 90.0%" in capsys.readouterr().err


def test_unbaselined_source_clearing_the_floor_passes(module, tmp_path: Path) -> None:
    """The floor is a floor, not a blanket rejection of unreviewed sources."""
    rows = tmp_path / "rows.jsonl"
    _rows(rows, "packages/example.py", killed=19, survived=1)  # 95%
    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"entries": {}}\n', encoding="utf-8")

    assert module.main([str(rows), "--baseline", str(baseline)]) == 0


def test_write_baseline_merges_the_legacy_candidate(module, tmp_path: Path) -> None:
    rows = tmp_path / "rows.jsonl"
    _rows(rows, "packages/example.py", killed=19, survived=1)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        '{"entries": {"packages/already-covered.py": {"kill_rate": 0.95}}}\n',
        encoding="utf-8",
    )

    assert module.main([str(rows), "--baseline", str(baseline), "--write-baseline"]) == 0
    assert set(json.loads(baseline.read_text(encoding="utf-8"))["entries"]) == {
        "packages/already-covered.py",
        "packages/example.py",
    }


def test_baselined_source_regression_fails(module, tmp_path: Path) -> None:
    rows = tmp_path / "rows.jsonl"
    rows.write_text(
        json.dumps(
            [
                {"mutations": [{"module_path": "packages/example.py"}]},
                {"test_outcome": "survived"},
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        '{"entries": {"packages/example.py": {"kill_rate": 0.9}}}\n',
        encoding="utf-8",
    )

    assert module.main([str(rows), "--baseline", str(baseline)]) == 1
