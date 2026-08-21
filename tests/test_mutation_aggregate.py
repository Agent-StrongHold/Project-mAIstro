"""Regression coverage for repository mutation-health aggregation."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "mutation_aggregate.py"


@pytest.fixture(scope="module")
def module():
    spec = importlib.util.spec_from_file_location("_mutation_aggregate", SCRIPT)
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


def row(source: str, rate: float, viable: int, killed: int, mutation: float) -> dict[str, object]:
    return {
        "source": source,
        "complete": True,
        "verified_at": "2026-08-15T20:00:00+00:00",
        "tool_fingerprint": "tools-v1",
        "viable_mutants": viable,
        "killed_mutants": killed,
        "surviving_mutants": viable - killed,
        "kill_rate": rate,
        "mutation_seconds": mutation,
        "baseline_test_seconds": 5.0,
    }


def test_report_aggregates_quality_and_source_movement(module) -> None:
    rows = [row("a.py", 0.95, 100, 95, 600), row("b.py", 0.90, 50, 45, 300)]
    history = {"entries": {"a.py": {"kill_rate": 0.90}, "b.py": {"kill_rate": 0.95}}}
    report = module.build_report(rows, ["a.py", "b.py"], history)
    assert report["complete"] is True
    assert report["viable_mutants"] == 150
    assert report["killed_mutants"] == 140
    assert report["kill_rate"] == pytest.approx(140 / 150)
    assert report["improved_sources"] == ["a.py"]
    assert report["regressed_sources"] == ["b.py"]
    assert report["slowest_sources"][0]["source"] == "a.py"


def test_incomplete_inventory_is_reported(module) -> None:
    report = module.build_report([row("a.py", 1.0, 10, 10, 10)], ["a.py", "b.py"], {"entries": {}})
    assert report["complete"] is False
    assert report["unmeasured_sources"] == ["b.py"]


def test_checkpoint_reader_uses_latest_complete_source(module, tmp_path: Path) -> None:
    root = tmp_path / "checkpoints"
    root.mkdir()
    older = row("a.py", 0.8, 10, 8, 20)
    newer = row("a.py", 0.9, 10, 9, 15)
    newer["verified_at"] = "2026-08-15T21:00:00+00:00"
    (root / "old.checkpoint.json").write_text(json.dumps(older), encoding="utf-8")
    (root / "new.checkpoint.json").write_text(json.dumps(newer), encoding="utf-8")
    incomplete = row("b.py", 1.0, 1, 1, 1)
    incomplete["complete"] = False
    (root / "bad.checkpoint.json").write_text(json.dumps(incomplete), encoding="utf-8")
    assert module.read_checkpoints(root) == [newer]


def test_baseline_rows_only_come_from_selected_complete_checkpoints(module, tmp_path: Path) -> None:
    root = tmp_path / "checkpoints"
    complete_dir = root / "complete"
    incomplete_dir = root / "incomplete"
    complete_dir.mkdir(parents=True)
    incomplete_dir.mkdir(parents=True)

    complete = row("a.py", 1.0, 1, 1, 1)
    incomplete = row("b.py", 0.0, 1, 0, 1)
    incomplete["complete"] = False
    (complete_dir / "a.checkpoint.json").write_text(json.dumps(complete), encoding="utf-8")
    (complete_dir / "a.rows.jsonl").write_text('{"mutant": "complete"}\n', encoding="utf-8")
    (incomplete_dir / "b.checkpoint.json").write_text(json.dumps(incomplete), encoding="utf-8")
    (incomplete_dir / "b.rows.jsonl").write_text('{"mutant": "partial"}\n', encoding="utf-8")

    selected = module.select_checkpoints(root)
    assert module.read_selected_mutation_rows(selected) == ['{"mutant": "complete"}']


def test_mixed_tool_fingerprints_are_rejected(module) -> None:
    first = row("a.py", 1.0, 1, 1, 1)
    second = row("b.py", 1.0, 1, 1, 1)
    second["tool_fingerprint"] = "tools-v2"
    with pytest.raises(ValueError, match="mixed mutation tool fingerprints"):
        module.validate_tool_fingerprint([first, second])


def test_markdown_surfaces_regressions_and_unmeasured(module) -> None:
    report = module.build_report(
        [row("a.py", 0.8, 10, 8, 20)],
        ["a.py", "missing.py"],
        {"entries": {"a.py": {"kill_rate": 0.9}}},
    )
    rendered = module.render_markdown(report)
    assert "Regressed sources" in rendered
    assert "`a.py`" in rendered
    assert "Unmeasured sources" in rendered
    assert "`missing.py`" in rendered
