"""One locked Ruff owner per event, without losing the CI-only push profile."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = ("uv run ruff check .", "uv run ruff format --check .")
FALLBACK_BRANCH = "merge/main-into-integration"
FALLBACK = "github.event_name == 'push' && github.ref == 'refs/heads/merge/main-into-integration'"


@pytest.fixture(scope="module")
def documents():
    workflows = ROOT / ".github" / "workflows"
    return {
        "ci": yaml.safe_load((workflows / "ci.yml").read_text()),
        "quality": yaml.safe_load((workflows / "quality.yml").read_text()),
        "protection": json.loads((ROOT / ".github" / "branch-protection.json").read_text()),
    }


def _triggers(document):
    return document.get("on", document.get(True))


def _assert_owner(documents, command):
    ci = documents["ci"]
    quality = documents["quality"]
    for document in (ci, quality):
        assert not document.get("defaults", {}).get("run", {}).get("working-directory")
        events = _triggers(document)
        assert set(events) == {"push", "pull_request", "merge_group"}
        assert events["pull_request"] in (None, {})
        assert events["merge_group"] == {"types": ["checks_requested"]}
        assert set(events["push"]) == {"branches"}

    ci_pushes = set(_triggers(ci)["push"]["branches"])
    quality_pushes = set(_triggers(quality)["push"]["branches"])
    assert ci_pushes == {"main", "integration", "develop", FALLBACK_BRANCH}
    assert {"main", "integration", "develop"} <= quality_pushes
    assert ci_pushes - quality_pushes == {FALLBACK_BRANCH}
    prefixes = documents["protection"]["topic_branch_policy"]["prefixes"]
    assert {f"{prefix}/*" for prefix in prefixes} <= quality_pushes

    for document, job_id, condition in (
        (ci, "lint-and-type-check", FALLBACK),
        (quality, "quality-gate", None),
    ):
        job = document["jobs"][job_id]
        assert "if" not in job and "continue-on-error" not in job
        assert not job.get("defaults", {}).get("run", {}).get("working-directory")
        matches = [step for step in job["steps"] if step.get("run") == command]
        assert len(matches) == 1
        step = matches[0]
        assert "continue-on-error" not in step and "working-directory" not in step
        if condition is None:
            assert "if" not in step
        else:
            assert step["if"] == condition
        assert any(item.get("uses") == "./.github/actions/setup-uv" for item in job["steps"])
        expected_sync = {
            "lint-and-type-check": "uv sync --locked --extra dev",
            "quality-gate": "uv sync --locked --all-extras",
        }[job_id]
        assert any(item.get("run") == expected_sync for item in job["steps"])

    name = quality["jobs"]["quality-gate"]["name"]
    for branch in ("develop", "main"):
        required = documents["protection"]["branches"][branch]["required_status_checks"]
        assert name in required["contexts"]


@pytest.mark.parametrize("command", COMMANDS)
def test_deployed_workflows_keep_one_required_owner_and_the_push_fallback(documents, command):
    _assert_owner(documents, command)


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("mutation", ["remove", "narrow", "tolerate", "different-root"])
def test_removing_or_weakening_the_remaining_owner_is_detected(documents, command, mutation):
    changed = copy.deepcopy(documents)
    steps = changed["quality"]["jobs"]["quality-gate"]["steps"]
    owner = next(step for step in steps if step.get("run") == command)
    if mutation == "remove":
        steps.remove(owner)
    elif mutation == "narrow":
        owner["if"] = "github.base_ref == 'main'"
    elif mutation == "tolerate":
        owner["continue-on-error"] = True
    else:
        owner["working-directory"] = "packages/maistro-core"
    with pytest.raises(AssertionError):
        _assert_owner(changed, command)


@pytest.mark.parametrize("condition", ["false", "true", "github.event_name == 'push'"])
def test_missing_or_overbroad_ci_fallback_is_detected(documents, condition):
    changed = copy.deepcopy(documents)
    steps = changed["ci"]["jobs"]["lint-and-type-check"]["steps"]
    next(step for step in steps if step.get("run") == COMMANDS[0])["if"] = condition
    with pytest.raises(AssertionError):
        _assert_owner(changed, COMMANDS[0])


@pytest.mark.parametrize("event", ["pull_request", "merge_group", "push"])
def test_narrowed_quality_events_are_detected(documents, event):
    changed = copy.deepcopy(documents)
    events = _triggers(changed["quality"])
    if event == "pull_request":
        events[event] = {"branches": ["main"]}
    elif event == "merge_group":
        del events[event]
    else:
        events[event]["branches"].remove("develop")
    with pytest.raises(AssertionError):
        _assert_owner(changed, COMMANDS[0])


def test_new_ci_only_push_profile_requires_an_ownership_decision(documents):
    changed = copy.deepcopy(documents)
    _triggers(changed["ci"])["push"]["branches"].append("another/profile")
    with pytest.raises(AssertionError):
        _assert_owner(changed, COMMANDS[0])


@pytest.mark.parametrize("branch", ["develop", "main"])
def test_quality_cannot_become_advisory_after_deduplication(documents, branch):
    changed = copy.deepcopy(documents)
    required = changed["protection"]["branches"][branch]["required_status_checks"]
    required["contexts"].remove(changed["quality"]["jobs"]["quality-gate"]["name"])
    with pytest.raises(AssertionError):
        _assert_owner(changed, COMMANDS[0])
