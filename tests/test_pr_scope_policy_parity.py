"""Contract: one scope policy governs PR events across every surface (#1351).

Before #1351 the producers and the judge disagreed about pull requests:

- ``ci_merge_group_scope.scope_for_event()`` enabled every specialized leg for
  any non-``merge_group`` event, while ``check-gates-ran.py`` classified PR
  changed files directly;
- every specialized ci.yml job's ``if`` enabled it for every PR;
- ``check-integration-scope.required_checks()`` required all legs for PRs.

A specialized check reported ``skipped`` on a PR could therefore be discarded
by gates-ran as "out of scope" under a policy none of its producers used.
This module pins the converged policy (option (a) of #1351): PR events are
path-scoped by the single checked-in classifier everywhere -- ci.yml job
conditions, integration-scope's required set, the classifier's event API, and
the gates-ran evaluator -- so a skip a producer chose is exactly a skip the
evaluator may excuse, and anything else stays blocking.

The converged policy is also what the accepted
ADR-091226-1341 already described for the evaluator side: "a narrow
dependencies, documentation, or workflow change can legitimately skip a
specialized leg." The producers now make that true instead of merely
tolerating the evaluator's assumption.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from scripts.ci_merge_group_scope import LEGS, classify, scope_for_event

from tests.test_ci_specialized_scope_wiring import (
    SPECIALIZED,
    evaluate_github_expression,
)

ROOT = Path(__file__).resolve().parents[1]
GATES_RAN = ROOT / "scripts" / "check-gates-ran.py"
INTEGRATION_SCOPE = ROOT / "scripts" / "check-integration-scope.py"
CLASSIFIER = ROOT / "scripts" / "ci_merge_group_scope.py"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
INTEGRATION_SCOPE_WORKFLOW = ROOT / ".github" / "workflows" / "integration-scope.yml"

#: A change no specialized leg reads except docker-build (the classifier
#: copies docs into the shipped image context). The canonical "narrow PR"
#: shape the convergence is about.
DOCS_ONLY_FILES = ["docs/ci/MERGE-QUEUE.md"]


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gates_ran() -> Any:
    return _load("gates_ran_for_parity", GATES_RAN)


@pytest.fixture(scope="module")
def integration_scope() -> Any:
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return _load("check_integration_scope_for_parity", INTEGRATION_SCOPE)


@pytest.fixture(scope="module")
def ci_jobs() -> dict[str, Any]:
    return yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def _scope_from_envelope(gates_ran: Any, files: list[str], tmp_path: Path) -> dict[str, bool]:
    """Derive scope exactly as the gates-ran evaluator does from the envelope
    the publisher writes."""
    envelope = tmp_path / "changed-files.json"
    envelope.write_text(json.dumps({"measured": True, "files": files}), encoding="utf-8")
    scope, measured = gates_ran._pull_request_scope(envelope)
    assert measured is True
    assert scope is not None
    return scope


def test_the_evaluator_and_the_producers_share_one_classifier_implementation(
    gates_ran: Any,
) -> None:
    """Not two copies of the policy: gates-ran must load the checked-in
    ci_merge_group_scope.py, the same module the producers consume."""
    assert gates_ran._load_scope_classifier().__file__ == str(CLASSIFIER)


def test_all_four_surfaces_derive_the_same_pr_scope(
    gates_ran: Any,
    integration_scope: Any,
    tmp_path: Path,
) -> None:
    """classifier, event API, evaluator envelope, and required-check set must
    answer identically for one measured PR changed-file set."""
    files = DOCS_ONLY_FILES
    expected = classify(files)

    assert scope_for_event("pull_request", files) == expected
    assert _scope_from_envelope(gates_ran, files, tmp_path) == expected

    required = integration_scope.required_checks("pull_request", json.dumps(expected))
    assert required == {
        name
        for leg, names in integration_scope.CHECK_NAMES.items()
        if expected[leg]
        for name in names
    }
    # Docs select only the docker-build leg; everything else is skippable.
    assert required == {"docker-build"}


def test_ci_yml_conditions_produce_the_same_verdict_as_the_required_set(
    gates_ran: Any,
    integration_scope: Any,
    ci_jobs: dict[str, Any],
    tmp_path: Path,
) -> None:
    """For one measured PR, ci.yml's job conditions, integration-scope's
    required set, and gates-ran's scope derivation agree leg by leg."""
    scope = _scope_from_envelope(gates_ran, DOCS_ONLY_FILES, tmp_path)
    required = integration_scope.required_checks("pull_request", json.dumps(scope))

    for job_name, leg in SPECIALIZED.items():
        if job_name == "postgres":
            # The unconditional matrix cannot report its concrete names when
            # skipped (GitHub names the job before expanding), so it runs on
            # every candidate; pinned in test_ci_specialized_scope_wiring.
            continue
        runs = evaluate_github_expression(
            ci_jobs[job_name]["if"],
            {
                "github.event_name": "pull_request",
                f"needs.workflow-lint.outputs.{leg}": "true" if scope[leg] else "false",
            },
        )
        produced_names = set(integration_scope.CHECK_NAMES[leg])
        if runs:
            assert produced_names & required, (job_name, leg)
        else:
            assert not produced_names & required, (job_name, leg)


def _producer_outcome_runs(check: Any, scope: dict[str, bool]) -> list[dict[str, Any]]:
    """The check-run shape the converged producers produce for one PR: every
    required name ran, except the specialized checks whose leg is out of scope
    -- which their jobs skipped. The postgres matrix is the documented
    exception: its job has no `if` (GitHub evaluates job-level if before
    expanding the matrix), so its concrete names always execute."""
    unconditional = {"postgres (pg17)", "postgres (pg18)"}
    runs = []
    for name in check.required_check_names(event_name="pull_request"):
        leg = check.PATH_SCOPED_CHECKS.get(name)
        skipped = leg is not None and not scope[leg] and name not in unconditional
        runs.append(
            {"name": name, "status": "completed", "conclusion": "skipped" if skipped else "success"}
        )
    return runs


def test_documented_outcome_narrow_pr_with_producer_skips_is_green(
    gates_ran: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """THE #1351 outcome, end to end: a docs-only PR whose specialized jobs
    skipped per the classifier must publish gates-ran green -- with the same
    envelope, the same classifier, and no producer divergence."""
    scope = classify(DOCS_ONLY_FILES)
    assert not all(scope.values()), "premise: a docs-only PR scopes legs off"
    payload = tmp_path / "check-runs.json"
    payload.write_text(json.dumps({"check_runs": _producer_outcome_runs(gates_ran, scope)}))
    envelope = tmp_path / "changed-files.json"
    envelope.write_text(json.dumps({"measured": True, "files": DOCS_ONLY_FILES}))

    code = gates_ran.main(
        [
            "--check-runs",
            str(payload),
            "--require-complete",
            "--base-branch",
            "develop",
            "--event-name",
            "pull_request",
            "--changed-files",
            str(envelope),
        ]
    )
    assert code == 0
    assert "ok: all" in capsys.readouterr().out


def test_documented_outcome_in_scope_skip_stays_red(
    gates_ran: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Convergence cuts both ways: a skipped check whose leg the same measured
    scope selects is non-execution, never an excuse."""
    files = ["packages/maistro-core/src/maistro/runs/attempt.py"]
    scope = classify(files)
    assert scope["strike_ladder"] is True, "premise: the leg is in scope"
    runs = _producer_outcome_runs(gates_ran, classify(DOCS_ONLY_FILES))
    for run in runs:
        if run["name"] == "strike-ladder":
            run["conclusion"] = "skipped"
    payload = tmp_path / "check-runs.json"
    payload.write_text(json.dumps({"check_runs": runs}))
    envelope = tmp_path / "changed-files.json"
    envelope.write_text(json.dumps({"measured": True, "files": files}))

    code = gates_ran.main(
        [
            "--check-runs",
            str(payload),
            "--require-complete",
            "--base-branch",
            "develop",
            "--event-name",
            "pull_request",
            "--changed-files",
            str(envelope),
        ]
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "strike-ladder" in out


def test_integration_scope_workflow_classifies_pull_requests() -> None:
    """The workflow must measure PR changed files through the same base
    revision + classifier path it uses for merge groups; a PR branch that
    kept `--json` unmeasured would quietly require every leg again."""
    text = INTEGRATION_SCOPE_WORKFLOW.read_text(encoding="utf-8")
    scope_step = text.split("- name: Resolve integration scope", 1)[1].split("- name:", 1)[0]
    assert (
        '"$GITHUB_EVENT_NAME" == "merge_group" || "$GITHUB_EVENT_NAME" == "pull_request"'
        in scope_step
    )
    assert "ci_base_revision.py" in scope_step
    assert "ci_merge_group_scope.py --json" in scope_step


def test_gates_ran_publisher_hands_pr_envelopes_to_the_shared_evaluator() -> None:
    """The publisher's PR branch writes the measured envelope and the evaluate
    step passes it on; with the producers converged, this is the only PR
    scope consumer left in gates-ran.yml."""
    text = (ROOT / ".github" / "workflows" / "gates-ran.yml").read_text(encoding="utf-8")
    assert "changed-files.json" in text
    assert "--changed-files changed-files.json" in text


def test_the_converged_policy_covers_exactly_the_candidate_events() -> None:
    """One classifier, two candidate events, everything else unconditional."""
    from scripts import ci_merge_group_scope as helper

    assert set(helper.PATH_SCOPED_EVENTS) == {"merge_group", "pull_request"}
    assert all(helper.scope_for_event("push", DOCS_ONLY_FILES).values())
    assert all(helper.scope_for_event("pull_request", None).values())
    # And the classifier itself is unchanged: empty evidence fails closed.
    assert all(classify([]).values())
    assert set(classify(DOCS_ONLY_FILES)) == set(LEGS)
