from __future__ import annotations

import json
import subprocess
from pathlib import Path
import sys


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mutation_select_baseline.py"


def run_selector(tmp_path: Path, baseline_entries: dict[str, object], seed: str = "seed") -> str:
    targets = tmp_path / "targets.tsv"
    targets.write_text("b.py\ttests/b\na.py\ttests/a\nc.py\ttests/c\n", encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"entries": baseline_entries}), encoding="utf-8")
    output = tmp_path / "selected.tsv"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(targets),
            "--baseline",
            str(baseline),
            "--seed",
            seed,
            "--output",
            str(output),
        ],
        check=True,
    )
    return output.read_text(encoding="utf-8")


def test_selection_is_reproducible_and_skips_baselined_sources(tmp_path: Path) -> None:
    first = run_selector(tmp_path, {"a.py": {"kill_rate": 0.5}}, seed="same")
    second = run_selector(tmp_path, {"a.py": {"kill_rate": 0.5}}, seed="same")
    assert first == second
    assert not first.startswith("a.py\t")
    assert first in {"b.py\ttests/b\n", "c.py\ttests/c\n"}


def test_empty_output_when_every_target_is_baselined(tmp_path: Path) -> None:
    result = run_selector(
        tmp_path,
        {"a.py": {}, "b.py": {}, "c.py": {}},
    )
    assert result == ""
