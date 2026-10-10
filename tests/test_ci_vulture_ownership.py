"""Preserve Vulture's event, environment and trusted-base contract when deduplicating."""

from __future__ import annotations

import copy
import json
import re
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCAN = (
    "uv run python scripts/check-vulture-baseline.py packages/*/src "
    "--min-confidence 60 --exclude '*/third_party/*'"
)
PROTECTED = {"develop", "integration", "main"}
PR_ACTIONS = {"opened", "reopened", "synchronize"}
OWNERS = {"quality.yml": "quality-gate", "vulture-ratchet.yml": "exact-debt-ledger"}
FALLBACK = (
    "github.event_name == 'push' && github.ref != 'refs/heads/develop' && "
    "github.ref != 'refs/heads/integration' && github.ref != 'refs/heads/main'"
)
BASE = """${{ github.event_name == 'pull_request'
    && format('origin/{0}', github.base_ref)
    || github.event_name == 'merge_group' && github.event.merge_group.base_sha
    || github.ref == 'refs/heads/develop' && github.event.before
    || github.ref == 'refs/heads/integration' && github.event.before
    || github.ref == 'refs/heads/main' && github.event.before || 'origin/develop' }}"""


def _normalized(value):
    return " ".join(value.split())


def _events(document):
    return document.get("on", document.get(True))


@pytest.fixture(scope="module")
def documents():
    return {
        "workflows": {
            path.name: yaml.safe_load(path.read_text())
            for path in (ROOT / ".github/workflows").iterdir()
            if path.suffix in {".yml", ".yaml"}
        },
        "protection": json.loads((ROOT / ".github/branch-protection.json").read_text()),
    }


def _assert_execution(scope):
    assert "continue-on-error" not in scope
    assert "shell" not in scope and "working-directory" not in scope
    defaults = scope.get("defaults", {}).get("run", {})
    assert "shell" not in defaults and "working-directory" not in defaults


def _assert_contract(documents):
    workflows = documents["workflows"]
    # Count every workflow, including reusable callers: adding a new owner must
    # establish an event/profile partition, never silently duplicate the scan.
    found = [
        (path, job_id)
        for path, document in workflows.items()
        for job_id, job in document.get("jobs", {}).items()
        for step in job.get("steps", [])
        if "check-vulture-baseline.py" in step.get("run", "")
    ]
    assert sorted(found) == sorted(OWNERS.items())
    prefixes = documents["protection"]["topic_branch_policy"]["prefixes"]
    for path, job_id in OWNERS.items():
        document = workflows[path]
        events = _events(document)
        assert set(events) == {"pull_request", "merge_group", "push"}
        assert events["pull_request"] is None
        assert events["merge_group"] == {"types": ["checks_requested"]}
        expected_pushes = PROTECTED | (
            {f"{prefix}/*" for prefix in prefixes} if path == "quality.yml" else set()
        )
        assert set(events["push"]) == {"branches"}
        assert set(events["push"]["branches"]) == expected_pushes
        job = document["jobs"][job_id]
        assert not {"if", "strategy", "uses", "needs"}.intersection(job)
        assert job["runs-on"] == "ubuntu-latest"
        for scope in (document, job):
            _assert_execution(scope)
        assert not document.get("env")
        assert _normalized(job["env"]["RATCHET_BASE_REV"]) == _normalized(BASE)
        # No profile/path overrides may redirect uv or bypass base resolution.
        assert not {
            "PYTHONPATH",
            "UV_PROJECT",
            "UV_PROJECT_ENVIRONMENT",
            "UV_NO_SYNC",
            "UV_WORKING_DIRECTORY",
            "VIRTUAL_ENV",
        }.intersection(job["env"])
        steps = job["steps"]
        owner = next(step for step in steps if "check-vulture-baseline.py" in step.get("run", ""))
        assert _normalized(owner["run"]) == SCAN
        assert owner.get("if") == (FALLBACK if path == "quality.yml" else None)
        required = [
            next(step for step in steps if step.get("uses", "").startswith("actions/checkout@")),
            next(step for step in steps if step.get("uses") == "./.github/actions/setup-uv"),
            next(step for step in steps if step.get("run") == "uv python install 3.12"),
            next(step for step in steps if step.get("run") == "uv sync --locked --all-extras"),
            owner,
        ]
        assert [steps.index(step) for step in required] == sorted(
            steps.index(step) for step in required
        )
        assert required[0]["with"] == {"fetch-depth": 0}
        assert sum(step.get("uses", "").startswith("actions/checkout@") for step in steps) == 1
        for step in required:
            _assert_execution(step)
            assert not step.get("env")
            if step is not owner:
                assert "if" not in step
        for branch in ("develop", "main"):
            contexts = documents["protection"]["branches"][branch]["required_status_checks"][
                "contexts"
            ]
            assert job.get("name", job_id) in contexts
    # The independent dedicated job's provenance and shipped-surface verdicts
    # remain mandatory prerequisites, with their existing commands intact.
    steps = workflows["vulture-ratchet.yml"]["jobs"]["exact-debt-ledger"]["steps"]
    scan = next(step for step in steps if "check-vulture-baseline.py" in step.get("run", ""))
    for script in ("check-ratchet-provenance.py", "check-shipped-surface-truth.py"):
        step = next(step for step in steps if step.get("run") == f"uv run python scripts/{script}")
        assert "if" not in step
        _assert_execution(step)
        assert not step.get("env")
        assert steps.index(step) < steps.index(scan)


def test_deployed_vulture_ownership_contract(documents):
    _assert_contract(documents)
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    assert [package["version"] for package in lock["package"] if package["name"] == "vulture"] == [
        "2.16"
    ]


def _receives(document, event, branch, action):
    events = _events(document)
    if event not in events:
        return False
    trigger = events[event]
    if event == "pull_request":
        return action in (trigger or {}).get("types", PR_ACTIONS)
    if event == "merge_group":
        return action in trigger["types"]
    return any(
        re.fullmatch(re.escape(pattern).replace(r"\*", "[^/]*"), branch)
        for pattern in trigger["branches"]
    )


def _allows(condition, event, branch):
    if condition is None:
        return True
    context = {"github.event_name": event, "github.ref": f"refs/heads/{branch}"}
    decisions = []
    for comparison in condition.split(" && "):
        match = re.fullmatch(r"(github\.[\w.]+) (==|!=) '([^']*)'", comparison)
        assert match is not None, f"unreviewed ownership expression: {condition}"
        key, operator, value = match.groups()
        decisions.append((context[key] == value) == (operator == "=="))
    return all(decisions)


@pytest.mark.parametrize(
    "event,branch,action,expected",
    [
        *(
            ("pull_request", branch, action, ["vulture-ratchet.yml"])
            for branch in ("develop", "feature/stacked-parent")
            for action in sorted(PR_ACTIONS)
        ),
        *(("push", branch, "", ["vulture-ratchet.yml"]) for branch in sorted(PROTECTED)),
        *(
            ("push", f"{prefix}/topic", "", ["quality.yml"])
            for prefix in ("feat", "bug", "fix", "idea", "doc", "docs", "chore")
        ),
        (
            "merge_group",
            "gh-readonly-queue/develop/pr-1",
            "checks_requested",
            ["vulture-ratchet.yml"],
        ),
        # These contexts were never Vulture producers. Widening either trigger
        # demands an explicit owner decision; Ruff's CI edited fallback stays separate.
        ("pull_request", "develop", "edited", []),
        ("workflow_call", "develop", "", []),
        ("workflow_dispatch", "develop", "", []),
        ("push", "merge/main-into-integration", "", []),
        ("push", "feature/unsupported", "", []),
        ("push", "feat/nested/topic", "", []),
    ],
)
def test_actual_event_matrix_has_exactly_the_existing_owner(
    documents, event, branch, action, expected
):
    _assert_contract(documents)
    owners = []
    for path, job_id in OWNERS.items():
        document = documents["workflows"][path]
        if _receives(document, event, branch, action):
            owners.extend(
                path
                for step in document["jobs"][job_id]["steps"]
                if "check-vulture-baseline.py" in step.get("run", "")
                and _allows(step.get("if"), event, branch)
            )
    assert owners == expected


@pytest.mark.parametrize("path", OWNERS)
@pytest.mark.parametrize(
    "mutation",
    [
        "remove",
        "duplicate",
        "conditional",
        "tolerate",
        "different-scope",
        "update",
        "shell",
        "cwd",
        "environment",
        "checkout",
        "depth",
        "matrix",
        "needs",
        "base",
        "candidate-base",
        "unlocked",
        "sync-late",
        "setup-conditional",
        "python",
        "required-status",
        "pr-filter",
        "edited",
        "reusable",
        "push-filter",
        "missing-queue",
    ],
)
def test_owner_mutations_fail_closed(documents, path, mutation):
    changed = copy.deepcopy(documents)
    document = changed["workflows"][path]
    job = document["jobs"][OWNERS[path]]
    steps = job["steps"]
    owner = next(step for step in steps if "check-vulture-baseline.py" in step.get("run", ""))
    events = _events(document)
    sync = next(step for step in steps if step.get("run") == "uv sync --locked --all-extras")
    setup = next(step for step in steps if step.get("uses") == "./.github/actions/setup-uv")
    python = next(step for step in steps if step.get("run") == "uv python install 3.12")
    contexts = changed["protection"]["branches"]["develop"]["required_status_checks"]["contexts"]
    mutations = {
        "remove": lambda: steps.remove(owner),
        "duplicate": lambda: changed["workflows"].update(
            {"reusable-duplicate.yml": copy.deepcopy(document)}
        ),
        "conditional": lambda: owner.update({"if": "false"}),
        "tolerate": lambda: job.update({"continue-on-error": True}),
        "different-scope": lambda: owner.update(
            {"run": owner["run"].replace("packages/*/src", "packages/maistro-core/src")}
        ),
        "update": lambda: owner.update({"run": owner["run"] + " --update"}),
        "shell": lambda: document.update(
            {"defaults": {"run": {"shell": 'bash -c "source {0}; true"'}}}
        ),
        "cwd": lambda: owner.update({"working-directory": "packages/maistro-core"}),
        "environment": lambda: owner.update({"env": {"RATCHET_BASE_REV": "HEAD"}}),
        "checkout": lambda: steps[0]["with"].update({"ref": "develop"}),
        "depth": lambda: steps[0]["with"].update({"fetch-depth": 1}),
        "matrix": lambda: job.update({"strategy": {"matrix": {"python": ["3.12", "3.13"]}}}),
        "needs": lambda: job.update({"needs": "possibly-skipped-job"}),
        "base": lambda: job["env"].update({"RATCHET_BASE_REV": "HEAD"}),
        "candidate-base": lambda: job["env"].update(
            {
                "RATCHET_BASE_REV": job["env"]["RATCHET_BASE_REV"].replace(
                    "'origin/develop'", "github.event.before"
                )
            }
        ),
        "unlocked": lambda: sync.update({"run": "uv sync --all-extras"}),
        "sync-late": lambda: (steps.remove(sync), steps.append(sync)),
        "setup-conditional": lambda: setup.update({"if": "false"}),
        "python": lambda: python.update({"run": "uv python install 3.13"}),
        "required-status": lambda: contexts.remove(job.get("name", OWNERS[path])),
        "pr-filter": lambda: events.update({"pull_request": {"branches": ["main"]}}),
        "edited": lambda: events.update(
            {"pull_request": {"types": [*sorted(PR_ACTIONS), "edited"]}}
        ),
        "reusable": lambda: events.update({"workflow_call": None}),
        "push-filter": lambda: events["push"]["branches"].append("!develop"),
        "missing-queue": lambda: events.pop("merge_group"),
    }
    mutations[mutation]()
    with pytest.raises((AssertionError, StopIteration)):
        _assert_contract(changed)


@pytest.mark.parametrize(
    "condition",
    [None, "true", "github.event_name == 'push'", "github.event_name != 'pull_request'"],
)
def test_duplicate_or_queue_overlap_is_not_a_valid_fallback(documents, condition):
    changed = copy.deepcopy(documents)
    steps = changed["workflows"]["quality.yml"]["jobs"]["quality-gate"]["steps"]
    next(step for step in steps if "check-vulture-baseline.py" in step.get("run", ""))["if"] = (
        condition
    )
    with pytest.raises(AssertionError):
        _assert_contract(changed)


@pytest.mark.parametrize(
    "script", ["check-ratchet-provenance.py", "check-shipped-surface-truth.py"]
)
def test_dedicated_prerequisite_cannot_run_after_scan(documents, script):
    changed = copy.deepcopy(documents)
    steps = changed["workflows"]["vulture-ratchet.yml"]["jobs"]["exact-debt-ledger"]["steps"]
    prerequisite = next(
        step for step in steps if step.get("run") == f"uv run python scripts/{script}"
    )
    steps.remove(prerequisite)
    steps.extend([prerequisite, {"run": "echo trailing step"}])
    with pytest.raises(AssertionError):
        _assert_contract(changed)
