"""Docs, workflow filters and one branch policy agree (#381).

README recommended `feature/*` while CONTRIBUTING and the quality/security
push filters used `feat/*` — an agent following README created a branch that
missed every push-triggered gate. And the push filters covered only one of
the six prefixes the docs documented, so `bug/*` and friends were in the same
position `feature/*` was.

The policy is single-sourced in `.github/branch-protection.json`
(`topic_branch_policy.prefixes`) — the file ADR-095 already names the
reviewable source of truth for the merge boundary — and everything else is
validated against it: README, CONTRIBUTING, WAYS-OF-WORKING, and the push
filters of the workflows that run topic-branch gates.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
POLICY_FILE = ROOT / ".github" / "branch-protection.json"
README = ROOT / "README.md"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"
WAYS = ROOT / "docs" / "WAYS-OF-WORKING.md"
WORKFLOWS = ROOT / ".github" / "workflows"

#: The protected integration branches push filters carry alongside the topic
#: prefixes. `integration` is retired as a tier (ADR-095) but remains a live
#: trigger target; `merge/main-into-integration` is ci.yml's backmerge shape.
PROTECTED_PUSH_TARGETS = {"main", "integration", "develop"}

#: The workflows that run the gate set on topic-branch pushes.
TOPIC_PUSH_WORKFLOWS = ("quality.yml", "security.yml")

#: Gate workflows whose PR half must run for every PR regardless of source.
PR_GATE_WORKFLOWS = ("ci.yml", "quality.yml", "security.yml", "registry.yml")


def policy_prefixes() -> list[str]:
    policy = json.loads(POLICY_FILE.read_text())["topic_branch_policy"]
    return list(policy["prefixes"])


def _push_branches(workflow: str) -> list[str]:
    doc = yaml.safe_load((WORKFLOWS / workflow).read_text())
    return list(doc[True]["push"]["branches"])


# --- the policy source ------------------------------------------------------


def test_the_policy_file_declares_a_nonempty_wellformed_prefix_set() -> None:
    prefixes = policy_prefixes()
    assert prefixes, "topic_branch_policy.prefixes is empty"
    for prefix in prefixes:
        assert re.fullmatch(r"[a-z]+", prefix), f"bad prefix {prefix!r}"


def test_the_retired_feature_prefix_is_not_in_the_policy() -> None:
    assert "feature" not in policy_prefixes()


# --- the docs name exactly the policy set -----------------------------------


def test_readme_names_exactly_the_policy_prefixes() -> None:
    section = README.read_text().split("## Contributing", 1)[1].split("## Layout", 1)[0]
    bullet = next(line for line in section.splitlines() if "Branch model" in line)
    named = set(re.findall(r"`([a-z]+)/\*?`", bullet))
    assert named == set(policy_prefixes()), (
        f"README branch-model bullet names {sorted(named)}; policy says {sorted(policy_prefixes())}"
    )


def test_contributing_names_exactly_the_policy_prefixes() -> None:
    text = CONTRIBUTING.read_text()
    bullet = next(line for line in text.splitlines() if line.startswith("- **Topic branches**"))
    named = set(re.findall(r"`([a-z]+)/\*`", bullet))
    assert named == set(policy_prefixes()), (
        f"CONTRIBUTING topic-branch bullet names {sorted(named)}; policy says "
        f"{sorted(policy_prefixes())}"
    )


def test_ways_of_working_names_exactly_the_policy_prefixes() -> None:
    flow = next(line for line in WAYS.read_text().splitlines() if "→  develop" in line)
    named = set(re.findall(r"([a-z]+)/\*", flow))
    assert named == set(policy_prefixes()), (
        f"WAYS-OF-WORKING flow names {sorted(named)}; policy says {sorted(policy_prefixes())}"
    )


def test_readme_no_longer_recommends_the_feature_prefix() -> None:
    """The #381 defect: following README created a gate-missing branch."""
    assert "feature/*" not in README.read_text()


# --- workflow triggers cover the policy set ---------------------------------


@pytest.mark.parametrize("workflow", TOPIC_PUSH_WORKFLOWS)
def test_topic_push_gates_cover_every_documented_prefix(workflow: str) -> None:
    branches = set(_push_branches(workflow))
    missing = {f"{p}/*" for p in policy_prefixes()} - branches
    assert not missing, (
        f"{workflow} push trigger misses documented prefixes {sorted(missing)}: "
        "a branch the docs bless would miss this push gate (#381)"
    )
    assert branches >= PROTECTED_PUSH_TARGETS


@pytest.mark.parametrize("workflow", PR_GATE_WORKFLOWS)
def test_pr_gates_run_regardless_of_source_branch(workflow: str) -> None:
    """The AC: the PR half must not filter on the source branch."""
    doc = yaml.safe_load((WORKFLOWS / workflow).read_text())
    triggers = doc[True]
    assert "pull_request" in triggers, f"{workflow} has no pull_request trigger"
    pr = triggers["pull_request"]
    # `pull_request:` bare parses as None; a mapping may carry activity types
    # but must not carry a branches filter.
    branches = pr.get("branches") if isinstance(pr, dict) else None
    assert branches in (None, []), (
        f"{workflow} filters pull_request by base {branches}; PR gates must run "
        "for every PR regardless of source-branch prefix"
    )
