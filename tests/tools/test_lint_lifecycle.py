"""Tests for the lifecycle linter and its baseline ratchet (ADR-097, SPEC-232).

The linter is a CI gate, so the property that matters is that it *fails* in
both directions: on a new violation, and on a stale baseline entry whose
violation no longer occurs. A gate that silently passes is worse than no gate —
it reads as evidence the defect class is handled. Same posture as
tests/test_check_reachability.py.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "lint_lifecycle.py"
BASELINE = ROOT / "quality" / "lifecycle-baseline.json"


@pytest.fixture(scope="module")
def lint():
    spec = importlib.util.spec_from_file_location("lint_lifecycle", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_spec(
    tmp_path: Path,
    *,
    status: str,
    history: str = "",
    body: str = "",
    tests_field: str = "tests: []",
) -> Path:
    path = tmp_path / "SPEC-999-fixture.md"
    path.write_text(
        "---\n"
        "id: SPEC-999\n"
        "title: Fixture\n"
        "kind: spec\n"
        f"status: {status}\n"
        "created: 2026-01-01\n"
        "owners: ['@nobody']\n"
        f"{tests_field}\n"
        f"{history}"
        "---\n"
        f"{body}",
        encoding="utf-8",
    )
    return path


# ── The gate fails both directions ──────────────────────────────────────────


def test_repo_corpus_passes_the_gate():
    """The committed baseline is the current truth — otherwise the first CI run
    after any merge fails for reasons unrelated to that merge."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_new_violation_not_in_baseline_fails(lint, tmp_path):
    path = _write_spec(tmp_path, status="Implemented", tests_field="tests: []")
    errors = lint.lint_file(path)
    assert any("requires field 'tests'" in e for e in errors)
    new, stale = lint.apply_baseline(errors, lint.load_baseline())
    assert new, "a violation absent from the baseline must surface as NEW"
    assert not stale or errors, "fixture must not mask the stale direction"


def test_stale_baseline_entry_fails(lint):
    new, stale = lint.apply_baseline([], {"docs/specs/SPEC-000-gone.md: fixed long ago"})
    assert stale == ["docs/specs/SPEC-000-gone.md: fixed long ago"]
    assert not new


def test_matching_baseline_passes(lint):
    err = "docs/specs/SPEC-000-x.md: status 'Implemented' requires field 'tests'"
    new, stale = lint.apply_baseline([err], {err})
    assert not new and not stale


def test_baseline_file_matches_its_own_contract(lint):
    """The committed baseline exactly equals currently accepted violations.

    Zero is a valid and preferred steady state; a ratchet must not require debt
    to remain merely so the test has something to count.
    """
    baseline = lint.load_baseline()
    errors = set(lint.collect_errors(["docs/adr", "docs/specs"]))
    assert baseline == errors
    for key in baseline:
        assert ": " in key, f"baseline keys are `path: message` strings, got {key!r}"


# ── Backwards corrections require a reason ──────────────────────────────────


def test_backwards_transition_without_reason_fails(lint, tmp_path):
    history = "history:\n  - status: Implemented\n  - status: In Progress\n"
    path = _write_spec(tmp_path, status="In Progress", history=history)
    errors = lint.lint_file(path)
    assert any("backwards correction requires a `reason`" in e for e in errors)


def test_backwards_transition_with_reason_passes(lint, tmp_path):
    history = (
        "history:\n"
        "  - status: Implemented\n"
        "  - status: In Progress\n"
        "    reason: two of four phases turned out to be missing\n"
    )
    path = _write_spec(tmp_path, status="In Progress", history=history)
    errors = lint.lint_file(path)
    assert not any("backwards" in e for e in errors), errors


def test_whitespace_reason_does_not_unlock_backwards(lint, tmp_path):
    history = "history:\n  - status: Implemented\n  - status: In Progress\n    reason: '  '\n"
    path = _write_spec(tmp_path, status="In Progress", history=history)
    errors = lint.lint_file(path)
    assert any("backwards correction requires a `reason`" in e for e in errors)


def test_reason_does_not_excuse_forward_invalid_transitions(lint, tmp_path):
    """A reason legalises only genuinely backwards hops — not terminal-to-
    terminal moves or duplicates the transition tables reject."""
    history = (
        "history:\n"
        "  - status: Superseded\n"
        "  - status: Deprecated\n"
        "    reason: not a correction, just an invalid hop\n"
    )
    path = _write_spec(tmp_path, status="Deprecated", history=history)
    errors = lint.lint_file(path)
    assert any("invalid transition 'Superseded' → 'Deprecated'" in e for e in errors)


def test_reason_does_not_excuse_duplicate_entries(lint, tmp_path):
    history = (
        "history:\n"
        "  - status: Implemented\n"
        "  - status: Implemented\n"
        "    reason: still implemented\n"
    )
    path = _write_spec(tmp_path, status="Implemented", history=history, tests_field="tests: [x.py]")
    errors = lint.lint_file(path)
    assert any("invalid transition 'Implemented' → 'Implemented'" in e for e in errors)


# ── Gherkin fences count as acceptance criteria ─────────────────────────────


def test_gherkin_scenarios_without_heading_are_criteria(lint, tmp_path):
    body = "# Fixture\n\n```gherkin\n@AC-1\nScenario: it works\n  Then it works\n```\n"
    path = _write_spec(tmp_path, status="Implemented", tests_field="tests: [x.py]", body=body)
    errors = lint.lint_file(path)
    assert not any("Acceptance Criteria" in e for e in errors), errors


def test_no_criteria_anywhere_still_fails(lint, tmp_path):
    path = _write_spec(
        tmp_path, status="Implemented", tests_field="tests: [x.py]", body="# Prose only\n"
    )
    errors = lint.lint_file(path)
    assert any("Acceptance Criteria" in e for e in errors)


# ── Deprecated is reachable for specs ───────────────────────────────────────


def test_spec_deprecated_reachable_from_deferred(lint, tmp_path):
    history = (
        "history:\n"
        "  - status: Deferred\n"
        "  - status: Deprecated\n"
        "    reason: subject deleted from the codebase while deferred\n"
    )
    path = _write_spec(tmp_path, status="Deprecated", history=history)
    assert lint.lint_file(path) == []


def test_spec_deprecated_entry_requires_reason(lint, tmp_path):
    """A contract withdrawal must say why — even on a forward transition."""
    history = "history:\n  - status: Deferred\n  - status: Deprecated\n"
    path = _write_spec(tmp_path, status="Deprecated", history=history)
    errors = lint.lint_file(path)
    assert any("'Deprecated' history entry requires a non-empty `reason`" in e for e in errors)


# ── Gherkin-only criteria still reach traceability ──────────────────────────


def test_extract_ac_ids_reads_gherkin_tags_without_heading(lint, tmp_path):
    """SPEC-160's shape: fence-only criteria, no AC heading. Accepting the
    document while extracting no ids would exempt it from traceability."""
    body = (
        "# Fixture\n\n```gherkin\n@AC-1\nScenario: a\n  Then a\n\n"
        "@AC-2\nScenario: b\n  Then b\n```\n"
    )
    path = _write_spec(tmp_path, status="Implemented", tests_field="tests: [x.py]", body=body)
    assert lint.extract_ac_ids(path) == ["SPEC-999/AC-1", "SPEC-999/AC-2"]


def test_extract_ac_ids_dedupes_heading_and_gherkin_forms(lint, tmp_path):
    body = (
        "## Acceptance Criteria\n\n- **AC-1** stated in bold\n\n"
        "```gherkin\n@AC-1\nScenario: same criterion restated\n  Then a\n```\n"
    )
    path = _write_spec(tmp_path, status="Implemented", tests_field="tests: [x.py]", body=body)
    assert lint.extract_ac_ids(path) == ["SPEC-999/AC-1"]


def test_vestigial_statuses_rejected(lint, tmp_path):
    path = _write_spec(tmp_path, status="Blocked")
    errors = lint.lint_file(path)
    assert any("invalid status 'Blocked'" in e for e in errors)
