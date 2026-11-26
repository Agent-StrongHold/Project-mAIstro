"""The ``run`` command's genome-summary wiring.

``__main__._run`` prints ``LocalRsiLoop._population_summary`` after a run
started with ``--genome-db``: the summary is the operator's one view of
whether a live run is actually LEARNING (population size, champions,
per-model reliability, who is benched). These tests pin the printout's shape
and the genome-db wiring with a stub loop — the population machinery itself
is covered by test_live_evolution.py.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from maistro_rsi import __main__ as entry

_SUMMARY: dict[str, Any] = {
    "population_size": 2,
    "generations": {"1": 1, "3": 1},
    "top_genomes": [
        {
            "name": "genome-abc",
            "generation": 3,
            "model": "fake/model-1",
            "fitness": 0.87,
            "tdd_rigor": 0.9,
            "test_style": "strict",
        }
    ],
    "reliability": {"fake/model-1": 0.91234567},
    "benched_models": ["fake/model-2"],
    "memory": {"learned_successes": "x"},
}


class _StubLoop:
    """Stands in for LocalRsiLoop: run() succeeds, the population summary is
    the stub's data. The summary PRINTING under test is the real code."""

    def __init__(self, config: Any) -> None:
        self.config = config

    def run(self) -> Any:
        class _Result:
            def summary(self) -> str:
                return "1 cycle(s): 1 promoted"

        return _Result()

    def _population_summary(self) -> dict[str, Any]:
        return _SUMMARY


def _init_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)
    return root


def test_genome_summary_prints_header_champions_reliability_and_bench(capsys) -> None:
    entry._print_genome_summary(_StubLoop(None))  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert "Evolution: 2 genome(s), generations=" in out
    assert "champion: genome-abc (gen 3, fake/model-1)" in out
    assert "fitness=0.87" in out
    assert "tdd_rigor=0.9" in out
    assert "test_style=strict" in out
    # Reliability is rounded to three places for the operator.
    assert "reliability: fake/model-1=0.912" in out
    assert "benched: fake/model-2" in out


def test_genome_summary_with_an_empty_population_prints_only_the_header(capsys) -> None:
    empty = {
        "population_size": 0,
        "generations": {},
        "top_genomes": [],
        "reliability": {},
        "benched_models": [],
        "memory": {},
    }

    class _EmptyLoop(_StubLoop):
        def _population_summary(self) -> dict[str, Any]:
            return empty

    entry._print_genome_summary(_EmptyLoop(None))  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert "Evolution: 0 genome(s)" in out
    assert "champion:" not in out
    assert "reliability:" not in out
    assert "benched:" not in out


def test_run_with_genome_db_prints_the_summary_after_the_loop(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """--genome-db wires the population into the loop AND the summary after
    it: a run that never prints the evolution state hides whether the run
    learned anything."""
    repo = _init_repo(tmp_path / "src")
    seen: dict[str, Any] = {}

    class _WiredLoop(_StubLoop):
        def __init__(self, config: Any) -> None:
            super().__init__(config)
            seen["genome_db"] = config.genome_db

    monkeypatch.setattr(entry, "LocalRsiLoop", _WiredLoop)
    db = tmp_path / "pop.db"

    code = entry.main(
        [
            "run",
            "--repo",
            str(repo),
            "--test-cmd",
            "exit 0",
            "--cycles",
            "1",
            "--genome-db",
            str(db),
        ]
    )

    assert code == 0
    assert seen["genome_db"] == str(db)
    out = capsys.readouterr().out
    assert "live evolution: population at" in out
    assert "Evolution: 2 genome(s)" in out
