"""Integration-target semantics for trusted ratchet baselines (#542)."""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.ratchet_provenance import load_authorizations, resolve_baseline

ROOT = Path(__file__).resolve().parents[1]
LEDGER = "quality/ledger.json"
AUTHORIZATIONS = "quality/ratchet-authorizations.json"
AUTHORIZATION_RATCHET_CHECKERS = (
    "scripts/check-vulture-baseline.py",
    "scripts/check-radon-baseline.py",
    "scripts/check-citation-status-provenance.py",
    "scripts/check-promotion-surface-provenance.py",
    "scripts/check-shell-execution-provenance.py",
    "scripts/check-contract-markers-provenance.py",
    "scripts/check-enumerations-provenance.py",
    "scripts/check-execution-lifecycles.py",
    "scripts/check-reachability-provenance.py",
    "scripts/check-reachability-dispositions-provenance.py",
    "scripts/check-model-egress.py",
    "scripts/check-public-routes.py",
)


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


def _write_json(repo: Path, relative: str, payload: object) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _ratchet_identity(checker: str) -> str:
    """Read the actual checker identity and require the trusted grant seam."""
    source = (ROOT / checker).read_text(encoding="utf-8")
    assert "load_authorizations" in source, f"{checker} does not consume trusted authorizations"
    tree = ast.parse(source, filename=checker)
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and target.id == "RATCHET"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    raise AssertionError(f"{checker} does not declare a stable RATCHET identity")


def _load_script(relative: str, name: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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
    _run(
        repo,
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "merge",
        "--no-ff",
        "-q",
        "candidate",
        "-m",
        "synthetic merge",
    )

    baseline = resolve_baseline(repo / LEDGER, base="origin/develop", root=repo)

    assert baseline.base_sha == target_tip
    assert baseline.loads()["tolerated"] == ["introduced-on-target"]


@pytest.mark.parametrize("checker", AUTHORIZATION_RATCHET_CHECKERS)
def test_same_tree_bank_and_justify_cannot_authorize_converted_ratchet(
    checker: str, tmp_path: Path
) -> None:
    """Reproduce #534's self-approval exploit for authorization-based conversions."""
    ratchet = _ratchet_identity(checker)
    repo = tmp_path / ratchet.replace("/", "-")
    repo.mkdir()
    _run(repo, "init", "-q", "-b", "develop")
    _write_json(repo, LEDGER, {"tolerated": []})
    _write_json(repo, AUTHORIZATIONS, {})
    trusted_sha = _commit(repo, "trusted floor")

    _run(repo, "checkout", "-q", "-b", "candidate")
    _write_json(repo, LEDGER, {"tolerated": ["banked-regression"]})
    _write_json(
        repo,
        AUTHORIZATIONS,
        {
            ratchet: {
                "banked-regression": {
                    "owner": "candidate",
                    "issue": "#542-exploit",
                    "reason": "same-tree justification must not authorize itself",
                }
            }
        },
    )
    _commit(repo, "weaken metric, bank it, justify it")

    candidate_grants = load_authorizations(
        ratchet,
        path=repo / AUTHORIZATIONS,
        root=repo,
    )
    trusted_grants = load_authorizations(
        ratchet,
        path=repo / AUTHORIZATIONS,
        base=trusted_sha,
        root=repo,
    )
    trusted_ledger = resolve_baseline(repo / LEDGER, base=trusted_sha, root=repo).loads()

    assert "banked-regression" in candidate_grants, "exploit setup did not write its grant"
    assert "banked-regression" not in trusted_grants
    assert trusted_ledger["tolerated"] == []


def test_mutation_conversion_rejects_same_tree_floor_weakening() -> None:
    """Mutation is stricter: no authorization can lower an already-trusted floor."""
    mutation = _load_script("scripts/check_mutation_baseline.py", "_m1_542_mutation_strict_floor")
    current = {"pkg/mod.py": (19, 20)}
    trusted = {"entries": {"pkg/mod.py": {"kill_rate": 0.95}}}
    candidate = {"entries": {"pkg/mod.py": {"kill_rate": 0.90}}}

    assert mutation.candidate_baseline_failures(current, trusted, candidate) == [
        "pkg/mod.py: candidate kill_rate 90.0% weakens trusted 95.0%"
    ]
