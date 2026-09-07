"""The PR template names the canonical base, and CI enforces it (#383).

The template told every author to target `main` — contradicting CONTRIBUTING,
ADR-095 and the actual branch flow — and it is the checklist every authoring
agent sees. Following it produced a mis-based PR no gate complained about.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check-pr-base.py"
TEMPLATE = ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"


def _gate():
    spec = importlib.util.spec_from_file_location("check_pr_base", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate():
    return _gate()


# --- the template ------------------------------------------------------------


def test_the_template_names_develop_as_the_normal_base() -> None:
    text = TEMPLATE.read_text()
    assert "Base branch is `develop`" in text
    assert "Base branch is `main`" not in text


def test_the_template_documents_the_promotion_exception() -> None:
    """`main` is authorized — but only as a labelled release/promotion PR."""
    text = TEMPLATE.read_text()
    assert "release/promotion PR" in text
    assert "`release` label" in text


def test_the_template_states_stacked_pr_behavior() -> None:
    text = TEMPLATE.read_text()
    assert "Stacked PRs" in text and "retargeted to `develop`" in text


def test_the_template_points_at_the_governing_adr() -> None:
    assert "ADR-095" in TEMPLATE.read_text()


# --- the gate ----------------------------------------------------------------


def test_develop_is_the_clean_base(gate) -> None:
    assert gate.check("develop") == []


def test_main_without_the_release_label_fails(gate) -> None:
    """The #383 defect, enforced: the default `main` base is not policy."""
    problems = gate.check("main", labels=[])

    assert len(problems) == 1
    assert "release" in problems[0] and "develop" in problems[0]


def test_main_with_the_release_label_is_the_authorized_promotion(gate) -> None:
    assert gate.check("main", labels=["release"]) == []


def test_a_stacked_topic_base_is_allowed(gate) -> None:
    assert gate.check("feat/anything") == []
    assert gate.check("bug/fix-thing") == []


def test_the_retired_integration_tier_fails(gate) -> None:
    problems = gate.check("integration")

    assert problems and "violates branch policy" in problems[0]


def test_the_undocumented_feature_prefix_fails(gate) -> None:
    """The #381 spelling, caught here too: it is not a documented prefix."""
    problems = gate.check("feature/my-branch")

    assert problems


def test_a_bare_branch_name_fails(gate) -> None:
    assert gate.check("blakes-work") != []


def test_topic_prefixes_come_from_the_policy_file(gate) -> None:
    """Single-sourced: the gate reads branch-protection.json, not a copy."""
    import json

    policy = json.loads((ROOT / ".github" / "branch-protection.json").read_text())
    prefixes = set(policy["topic_branch_policy"]["prefixes"])

    assert gate.topic_prefixes() == prefixes


def test_the_committed_invocation_shapes(gate, capsys: pytest.CaptureFixture[str]) -> None:
    """The workflow's argument shape works end to end."""
    assert gate.main(["--base", "develop", "--labels", ""]) == 0
    assert "ok" in capsys.readouterr().out

    assert gate.main(["--base", "main", "--labels", "release"]) == 0

    assert gate.main(["--base", "main", "--labels", ""]) == 1
    assert "::error::" in capsys.readouterr().out
