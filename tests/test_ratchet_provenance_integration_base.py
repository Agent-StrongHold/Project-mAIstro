"""Integration-target semantics for trusted ratchet baselines (#542)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.ratchet_provenance import resolve_baseline

LEDGER = "quality/ledger.json"


def _run(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _run(repo, "add", "-A")
    _run(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", message)
    return _run(repo, "rev-parse", "HEAD")


def _write(repo: Path, payload: object) -> None:
    path = repo / LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_current_target_ref_resolves_to_the_synthetic_merges_target_parent(tmp_path: Path) -> None:
    """A long-lived PR is judged against the target tree it will merge into.

    The candidate forks before a new ratchet exists. Develop adds that ratchet
    independently. GitHub's PR checkout is modeled by creating the synthetic
    merge from the updated target and merging the candidate into it. Naming the
    current target ref must therefore read the target's ledger, not pretend the
    later ratchet is candidate-authored debt.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init", "-q", "-b", "develop")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _commit(repo, "branch point")
    _run(repo, "remote", "add", "origin", str(repo))
    _run(repo, "fetch", "-q", "origin")

    _run(repo, "checkout", "-q", "-b", "candidate")
    (repo / "candidate.txt").write_text("candidate\n", encoding="utf-8")
    _commit(repo, "candidate work")

    _run(repo, "checkout", "-q", "develop")
    _write(repo, {"tolerated": ["introduced-on-target"]})
    target_tip = _commit(repo, "target adds ratchet")
    _run(repo, "fetch", "-q", "origin")

    _run(repo, "checkout", "-q", "-b", "synthetic")
    _run(repo, "merge", "--no-ff", "-q", "candidate", "-m", "synthetic merge")

    baseline = resolve_baseline(repo / LEDGER, base="origin/develop", root=repo)

    assert baseline.base_sha == target_tip
    assert baseline.loads()["tolerated"] == ["introduced-on-target"]
