"""Tests for #1357 check-name recovery and refusal of ambiguous contracts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check-required-checks.py"


@pytest.fixture
def discovery(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("recovered_check_discovery", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "WORKFLOW_DIR", workflows)
    monkeypatch.setattr(module, "PROTECTION", tmp_path / ".github" / "branch-protection.json")
    monkeypatch.setattr(module, "MERGE_QUEUE", tmp_path / ".github" / "merge-queue.json")
    return module


def write_workflow(discovery, filename, document):
    path = discovery.WORKFLOW_DIR / filename
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def caller(discovery, **changes):
    job = {
        "name": "Quality / lint",
        "uses": "./.github/workflows/reusable.yml",
        "with": {"check_name": "Lint"},
    }
    job.update(changes)
    return write_workflow(
        discovery,
        "caller.yml",
        {"name": "Caller", "on": {"pull_request": None}, "jobs": {"quality": job}},
    )


def callee(discovery, **changes):
    document = {
        "name": "Reusable",
        "on": {"workflow_call": {"inputs": {"check_name": {"type": "string"}}}},
        "jobs": {"check": {"name": "${{ inputs.check_name }}"}},
    }
    document.update(changes)
    return write_workflow(discovery, "reusable.yml", document)


def test_composes_caller_and_callee_names(discovery):
    caller(discovery)
    callee(discovery)
    assert discovery.collect() == [("Caller", "Quality / lint / Lint", "every PR")]


def test_preserves_literal_name_and_job_id_fallbacks(discovery):
    caller(discovery, name="Static")
    callee(discovery, jobs={"check": {"runs-on": "ubuntu-latest"}})
    assert discovery.collect() == [("Caller", "Static / check", "every PR")]


def test_resolves_declared_default_without_explicit_input(discovery):
    caller(discovery, **{"with": {}})
    callee(
        discovery,
        on={"workflow_call": {"inputs": {"check_name": {"type": "string", "default": "D"}}}},
    )
    assert discovery.collect()[0][1] == "Quality / lint / D"


def test_undeclared_name_input_is_not_treated_as_valid(discovery):
    caller(discovery)
    callee(discovery, on={"workflow_call": None})
    with pytest.raises(discovery.ContractError, match="undeclared input"):
        discovery.collect()


def test_unresolved_name_input_fails_closed(discovery):
    caller(discovery, **{"with": {}})
    callee(discovery)
    with pytest.raises(discovery.ContractError, match="unresolved input"):
        discovery.collect()


@pytest.mark.parametrize(
    "uses",
    [
        "octo/repo/.github/workflows/x.yml@v1",
        "./reusable.yml",
        "./.github/workflows/subdir/x.yml",
        "./.github/workflows/../x.yml",
        "./.github/workflows/x.yml@main",
        "./.github/workflows/x.txt",
    ],
)
def test_unsupported_or_external_path_fails_closed(discovery, uses):
    caller(discovery, uses=uses)
    with pytest.raises(discovery.ContractError, match="unsupported or external"):
        discovery.collect()


def test_missing_callee_fails_closed(discovery):
    caller(discovery)
    with pytest.raises(discovery.ContractError, match="missing reusable workflow"):
        discovery.collect()


def test_symlink_cannot_escape_the_workflow_directory(discovery):
    caller(discovery)
    outside = discovery.REPO_ROOT / "outside.yml"
    outside.write_text("on: workflow_call\njobs: {check: {name: Hidden}}\n")
    (discovery.WORKFLOW_DIR / "reusable.yml").symlink_to(outside)
    with pytest.raises(discovery.ContractError, match="escapes"):
        discovery.collect()


@pytest.mark.parametrize("jobs", [{}, None, []])
def test_empty_or_invalid_jobs_fail_closed(discovery, jobs):
    caller(discovery)
    callee(discovery, jobs=jobs)
    with pytest.raises(discovery.ContractError, match="has no jobs"):
        discovery.collect()


def test_uncallable_workflow_fails_closed(discovery):
    caller(discovery)
    callee(discovery, on={"workflow_dispatch": None})
    with pytest.raises(discovery.ContractError, match="no workflow_call"):
        discovery.collect()


def test_malformed_callee_fails_with_contract_error(discovery):
    caller(discovery)
    (discovery.WORKFLOW_DIR / "reusable.yml").write_text("jobs: [\n")
    with pytest.raises(discovery.ContractError, match="cannot read reusable workflow"):
        discovery.collect()


def test_unsupported_callee_expression_fails_closed(discovery):
    caller(discovery)
    callee(discovery, jobs={"check": {"name": "${{ matrix.version }} / check"}})
    with pytest.raises(discovery.ContractError, match="unsupported check name"):
        discovery.collect()


@pytest.mark.parametrize("value", ["${{ github.sha }}", "", "  ", False, 3])
def test_name_input_must_be_a_nonempty_literal_string(discovery, value):
    caller(discovery, **{"with": {"check_name": value}})
    callee(discovery)
    with pytest.raises(discovery.ContractError, match="unsupported check name"):
        discovery.collect()


def test_command_expressions_do_not_affect_name_resolution(discovery):
    caller(
        discovery,
        **{"with": {"check_name": "Lint", "command": "${{ github.event.before }}"}},
    )
    callee(discovery)
    assert discovery.collect()[0][1] == "Quality / lint / Lint"


@pytest.mark.parametrize(
    "change",
    [
        {"uses": "./.github/workflows/deeper.yml"},
        {"strategy": {"matrix": {"version": [17, 18]}}},
        {"if": "github.base_ref == 'main'"},
        {"if": False},
    ],
)
def test_unsupported_callee_topology_cannot_be_reported_as_unconditional(discovery, change):
    caller(discovery)
    callee(discovery, jobs={"check": {"name": "Lint", **change}})
    with pytest.raises(discovery.ContractError, match="nested, matrix or conditional"):
        discovery.collect()


def test_reusable_caller_matrix_is_not_silently_collapsed(discovery):
    caller(discovery, strategy={"matrix": {"version": [17, 18]}})
    callee(discovery)
    with pytest.raises(discovery.ContractError, match="caller matrices"):
        discovery.collect()


def test_caller_base_scope_is_preserved(discovery):
    caller(discovery, **{"if": "github.base_ref == 'main'"})
    callee(discovery)
    assert discovery.base_coupled(discovery.collect()) == {("Caller", "Quality / lint / Lint")}


def test_two_callee_jobs_are_both_discovered(discovery):
    caller(discovery)
    callee(discovery, jobs={"one": {"name": "One"}, "two": {"name": "Two"}})
    assert [row[1] for row in discovery.collect()] == [
        "Quality / lint / One",
        "Quality / lint / Two",
    ]


def test_duplicate_callee_names_fail_closed(discovery):
    caller(discovery)
    callee(discovery, jobs={"one": {"name": "Same"}, "two": {"name": "Same"}})
    with pytest.raises(discovery.ContractError, match="duplicate reusable check"):
        discovery.collect()


@pytest.mark.parametrize("job", [None, "not a job", {"name": 3}])
def test_invalid_callee_job_fails_closed(discovery, job):
    caller(discovery)
    callee(discovery, jobs={"check": job})
    with pytest.raises(discovery.ContractError, match="invalid reusable job"):
        discovery.collect()


def test_existing_direct_jobs_and_matrices_keep_their_names(discovery):
    write_workflow(
        discovery,
        "direct.yml",
        {
            "name": "CI",
            "on": {"pull_request": None},
            "jobs": {
                "lint": {"name": "Lint"},
                "postgres": {
                    "name": "postgres (${{ matrix.pg }})",
                    "strategy": {"matrix": {"pg": [17, 18]}},
                },
            },
        },
    )
    assert discovery.collect() == [
        ("CI", "Lint", "every PR"),
        ("CI", "postgres (17)", "every PR"),
        ("CI", "postgres (18)", "every PR"),
    ]


@pytest.mark.parametrize("merge_trigger", [False, True])
def test_composed_names_still_require_merge_group_on_the_caller(discovery, merge_trigger):
    path = caller(discovery)
    callee(discovery)
    document = yaml.safe_load(path.read_text())
    if merge_trigger:
        document["on"]["merge_group"] = {"types": ["checks_requested"]}
    path.write_text(yaml.safe_dump(document))
    discovery.PROTECTION.write_text(
        json.dumps(
            {
                "branches": {
                    "develop": {
                        "required_status_checks": {"contexts": ["Quality / lint / Lint"]},
                    },
                }
            }
        )
    )
    discovery.MERGE_QUEUE.write_text(
        json.dumps(
            {
                "branches": {
                    "develop": {
                        "merge_method": "SQUASH",
                        "max_entries_to_merge": 3,
                        "min_entries_to_merge": 1,
                        "min_entries_to_merge_wait_minutes": 2,
                        "grouping_strategy": "ALLGREEN",
                    }
                }
            }
        )
    )
    gaps = discovery.merge_group_gaps(discovery.collect())
    assert bool(gaps) is not merge_trigger
    if not merge_trigger:
        assert "Quality / lint / Lint" in gaps[0]


def test_invalid_workflow_call_configuration_is_rejected(discovery):
    caller(discovery)
    callee(discovery, on={"workflow_call": "invalid"})
    with pytest.raises(discovery.ContractError, match="invalid workflow_call"):
        discovery.collect()


@pytest.mark.parametrize("invalid_side", ["caller", "callee"])
def test_invalid_input_mapping_is_rejected(discovery, invalid_side):
    caller(discovery, **({"with": ["bad"]} if invalid_side == "caller" else {}))
    if invalid_side == "callee":
        callee(discovery, on={"workflow_call": {"inputs": ["bad"]}})
    else:
        callee(discovery)
    with pytest.raises(discovery.ContractError, match="invalid reusable input mapping"):
        discovery.collect()


def test_different_callers_bind_their_own_inputs(discovery):
    caller(discovery)
    callee(discovery)
    write_workflow(
        discovery,
        "second.yml",
        {
            "name": "Second",
            "on": {"pull_request": None},
            "jobs": {
                "quality": {
                    "name": "Second caller",
                    "uses": "./.github/workflows/reusable.yml",
                    "with": {"check_name": "Different"},
                }
            },
        },
    )
    assert discovery.collect() == [
        ("Caller", "Quality / lint / Lint", "every PR"),
        ("Second", "Second caller / Different", "every PR"),
    ]
