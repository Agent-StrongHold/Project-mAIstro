"""#392: no RSI code-improvement objective is improved without prior failing evidence."""

from __future__ import annotations

import subprocess
from pathlib import Path

from maistro_evolve.improvement import ImprovementKind
from maistro_evolve.scorecard import GateResult
from maistro_evolve.tdd_gate import TddEvidence
from maistro_rsi.candidate_fitness import FitnessInputs, compose_scorecard
from maistro_rsi.fail_first import (
    DOC_CONTRACT,
    FAIL_FIRST_CLAUSE,
    FAIL_FIRST_GATE,
    REFACTOR_CONTRACT,
    SPEC_DRAFT_CONTRACT,
    assess_promotion_evidence,
    failure_output_digest,
    introduced_test_ids,
    match_introduced_failure,
    python_sources_are_doc_only,
)
from maistro_rsi.local_loop import _DEFAULT_OBJECTIVE, _fixer_objective, _targeted_objective
from maistro_rsi.trace_notes import RewardVector, TraceNote


def _tdd(**overrides: object) -> TddEvidence:
    evidence = TddEvidence(
        changed_tests=["tests/test_pkg.py"],
        baseline_changed_rc=1,
        candidate_changed_rc=0,
        base_sha="a" * 40,
        candidate_sha="b" * 40,
        failing_test_id="tests/test_pkg.py::test_f",
        failure_output_digest="d" * 64,
        introduced_test_ids=["tests/test_pkg.py::test_f"],
        baseline_failure_ids=["tests/test_pkg.py::test_f"],
    )
    for key, value in overrides.items():
        setattr(evidence, key, value)
    return evidence


def _assess(
    evidence: TddEvidence,
    *,
    objective: str = "",
    changed: list[str] | None = None,
    config: list[str] | None = None,
    tests_passed: bool = True,
    doc_only_py: bool = False,
) -> GateResult:
    return assess_promotion_evidence(
        objective=objective,
        changed_files=changed if changed is not None else ["pkg.py", "tests/test_pkg.py"],
        config_files_changed=config or [],
        tests_passed=tests_passed,
        tdd=evidence,
        doc_only_py=doc_only_py,
    )


def test_objective_without_prior_failing_evidence_cannot_be_promoted() -> None:
    bug = _fixer_objective("pkg.py", ImprovementKind.BUG_FIX, "fix the off-by-one")
    gate = _assess(
        TddEvidence(base_sha="a" * 40, candidate_sha="b" * 40),
        objective=bug,
        changed=["pkg.py"],
    )
    scorecard = compose_scorecard(FitnessInputs(tests_passed=True, fail_first_gate=gate))
    assert gate.passed is False
    assert "missing fail-first evidence" in gate.reason
    assert scorecard.accepted is False
    assert scorecard.composite == 0.0


def test_characterization_only_candidate_is_not_improvement_evidence() -> None:
    gate = _assess(
        _tdd(
            baseline_changed_rc=None,
            failing_test_id="",
            failure_output_digest="",
            baseline_failure_ids=[],
            introduced_test_ids=["tests/test_pkg.py::test_snapshot"],
        ),
        objective=_DEFAULT_OBJECTIVE,
        changed=["tests/test_pkg.py"],
    )
    assert gate.passed is False
    assert "characterization-only" in gate.reason
    assert (
        compose_scorecard(FitnessInputs(tests_passed=True, fail_first_gate=gate)).accepted is False
    )


def test_already_passing_on_the_base_is_rejected() -> None:
    gate = _assess(_tdd(baseline_changed_rc=0, failing_test_id="", failure_output_digest=""))
    assert gate.passed is False
    assert "already-passing" in gate.reason


def test_unrelated_failure_is_rejected() -> None:
    gate = _assess(
        _tdd(
            failing_test_id="",
            failure_output_digest="",
            baseline_failure_ids=["tests/test_pkg.py::test_old"],
            introduced_test_ids=["tests/test_pkg.py::test_f"],
        )
    )
    assert gate.passed is False
    assert "unrelated" in gate.reason


def test_config_or_oracle_edit_cannot_manufacture_failure() -> None:
    gate = _assess(_tdd(), config=["pytest.ini"])
    assert gate.passed is False
    assert "configuration/oracle" in gate.reason


def test_non_reproducible_baseline_run_is_rejected() -> None:
    gate = _assess(_tdd(baseline_execution_failed=True, baseline_changed_rc=1))
    assert gate.passed is False
    assert "non-reproducible" in gate.reason

    missing_sha = _assess(_tdd(base_sha=""))
    assert missing_sha.passed is False
    assert "non-reproducible" in missing_sha.reason


def test_valid_fail_first_record_is_promotable_and_complete() -> None:
    gate = _assess(_tdd(), objective=_DEFAULT_OBJECTIVE)
    assert gate.passed is True
    assert gate.name == FAIL_FIRST_GATE
    assert gate.detail["contract"] == "fail-first"
    assert gate.detail["base_sha"] == "a" * 40
    assert gate.detail["candidate_sha"] == "b" * 40
    assert gate.detail["failing_test_id"] == "tests/test_pkg.py::test_f"
    assert gate.detail["failure_output_digest"] == "d" * 64
    assert gate.detail["passed"] is True
    assert (
        compose_scorecard(FitnessInputs(tests_passed=True, fail_first_gate=gate)).accepted is True
    )


def test_refactor_and_documentation_contracts_do_not_require_a_red_test() -> None:
    refactor_obj = _fixer_objective("pkg.py", ImprovementKind.REFACTOR, "rename the helper")
    refactor = _assess(
        TddEvidence(base_sha="a" * 40, candidate_sha="b" * 40),
        objective=refactor_obj,
        changed=["pkg.py"],
    )
    assert refactor.passed is True
    assert refactor.detail["contract"] == "refactor"
    assert refactor.detail["failing_test_id"] == ""

    doc_obj = _fixer_objective("pkg.py", ImprovementKind.DOC, "clarify the docstring")
    doc = _assess(
        TddEvidence(base_sha="a" * 40, candidate_sha="b" * 40),
        objective=doc_obj,
        changed=["pkg.py"],
        doc_only_py=True,
    )
    assert doc.passed is True
    assert doc.detail["contract"] == "documentation"

    # A docstring objective cannot be satisfied by editing the test oracle.
    cheated = _assess(
        _tdd(),
        objective=doc_obj,
        changed=["pkg.py", "tests/test_pkg.py"],
        doc_only_py=True,
    )
    assert cheated.passed is False

    draft = _assess(
        TddEvidence(),
        objective=_fixer_objective("pkg.py", ImprovementKind.BACKLOG, "sketch it"),
        changed=["docs/specs/SPEC-1.md"],
    )
    assert draft.passed is True
    assert draft.detail["contract"] == "spec-draft"


def test_behavior_changing_objective_rejects_a_refactor_shaped_diff() -> None:
    bug = _fixer_objective("pkg.py", ImprovementKind.BUG_FIX, "fix the off-by-one")
    gate = _assess(
        TddEvidence(base_sha="a" * 40, candidate_sha="b" * 40),
        objective=bug,
        changed=["pkg.py"],
    )
    assert FAIL_FIRST_CLAUSE in bug
    assert REFACTOR_CONTRACT not in bug
    assert gate.passed is False
    assert "missing fail-first evidence" in gate.reason


def test_default_objective_matches_sibling_fail_first_guarantee() -> None:
    sibling = _fixer_objective("pkg/mod.py", ImprovementKind.BUG_FIX, "fix it")
    feature = _fixer_objective("pkg/mod.py", ImprovementKind.FEATURE, "grow it")
    assert FAIL_FIRST_CLAUSE in _DEFAULT_OBJECTIVE
    assert FAIL_FIRST_CLAUSE in _targeted_objective("pkg/mod.py")
    assert FAIL_FIRST_CLAUSE in sibling
    assert FAIL_FIRST_CLAUSE in feature
    assert REFACTOR_CONTRACT in _DEFAULT_OBJECTIVE
    assert DOC_CONTRACT in _DEFAULT_OBJECTIVE
    assert SPEC_DRAFT_CONTRACT not in _DEFAULT_OBJECTIVE


def test_trace_note_records_the_fail_first_fields() -> None:
    note = TraceNote(
        cycle=1,
        target="pkg.py",
        accepted=True,
        kind="bug_fix",
        model="m",
        files_touched=2,
        reward=RewardVector(delta_pass=1.0, composite=0.5),
        gates={FAIL_FIRST_GATE: True},
        fail_first={
            "base_sha": "a" * 40,
            "failing_test_id": "tests/test_pkg.py::test_f",
            "failure_output_digest": "d" * 64,
            "candidate_sha": "b" * 40,
            "passed": True,
            "contract": "fail-first",
        },
    )
    restored = TraceNote.from_json(note.to_json())
    assert restored.fail_first == note.fail_first
    assert (
        TraceNote.from_json(
            TraceNote(
                cycle=0,
                target="t",
                accepted=False,
                kind="doc",
                model="",
                files_touched=0,
            ).to_json()
        ).fail_first
        is None
    )


def test_introduced_test_identity_ignores_an_unrelated_failure() -> None:
    introduced = introduced_test_ids(
        {"tests/test_pkg.py": "def test_old():\n    assert True\n"},
        {
            "tests/test_pkg.py": (
                "def test_old():\n    assert True\n\ndef test_f():\n    assert False\n"
            )
        },
    )
    assert introduced == {"tests/test_pkg.py::test_f"}
    output = (
        "FAILED tests/test_pkg.py::test_old - assert True\n"
        "FAILED tests/test_pkg.py::test_f[1] - x\n"
    )
    assert (
        match_introduced_failure(
            ["tests/test_pkg.py::test_old", "tests/test_pkg.py::test_f[1]"], introduced
        )
        == "tests/test_pkg.py::test_f"
    )
    assert failure_output_digest(output)


def test_doc_only_python_change_ignores_docstrings_and_annotations() -> None:
    before = 'def f(x: int) -> int:\n    """old"""\n    return x\n'
    after = 'def f(x: str) -> str:\n    """new docs"""\n    return x\n'
    assert python_sources_are_doc_only([(before, after)])
    behavior = 'def f(x: int) -> int:\n    """old"""\n    return x + 1\n'
    assert not python_sources_are_doc_only([(before, behavior)])
    assert not python_sources_are_doc_only([("", after)])


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def test_evaluate_candidate_rejects_characterization_and_accepts_fail_first(
    tmp_path: Path, monkeypatch
) -> None:
    """The evaluator path, not just the pure gate: real git SHAs and a real red run."""
    from maistro_evolve.mutation_probe import MutationProbe
    from maistro_rsi import candidate_fitness

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.co")
    _git(repo, "config", "user.name", "t")
    (repo / "pkg.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "branch", "base")

    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    monkeypatch.setattr(candidate_fitness, "_run", lambda *_a, **_k: (True, "exit 0"))
    monkeypatch.setattr(
        candidate_fitness, "measure_coverage_detailed", lambda *_a, **_k: (None, {})
    )
    monkeypatch.setattr(candidate_fitness, "_lint_gates", lambda *_a, **_k: [])
    monkeypatch.setattr(
        candidate_fitness,
        "probe_diff_mutations",
        lambda *_a, **_k: MutationProbe(available=False),
    )
    monkeypatch.setattr(
        candidate_fitness,
        "collect_inventory",
        lambda *_a, **_k: candidate_fitness.InventoryResult(),
    )

    # Characterization: snapshot the current return value. Already green.
    (repo / "test_pkg.py").write_text(
        "from pkg import f\n\ndef test_f():\n    assert f() == 1\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "characterization")
    characterized = candidate_fitness.evaluate_candidate(
        repo,
        ["test_pkg.py"],
        test_command="exit 0",
        baseline_ref="base",
        target=_DEFAULT_OBJECTIVE,
    )
    char_gate = next(g for g in characterized.gates if g.name == FAIL_FIRST_GATE)
    assert char_gate.passed is False
    assert "characterization-only" in char_gate.reason
    assert characterized.accepted is False

    # Fail-first: the same test demands the fixed behavior and the code changes.
    (repo / "pkg.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    (repo / "test_pkg.py").write_text(
        "from pkg import f\n\ndef test_f():\n    assert f() == 2\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fix")
    promoted = candidate_fitness.evaluate_candidate(
        repo,
        ["pkg.py", "test_pkg.py"],
        test_command="exit 0",
        baseline_ref="base",
        target=_fixer_objective("pkg.py", ImprovementKind.BUG_FIX, "return 2"),
    )
    ff = next(g for g in promoted.gates if g.name == FAIL_FIRST_GATE)
    assert ff.passed is True, ff.reason
    assert ff.detail["contract"] == "fail-first"
    assert ff.detail["failing_test_id"] == "test_pkg.py::test_f"
    assert ff.detail["passed"] is True
    assert len(str(ff.detail["base_sha"])) == 40
    assert len(str(ff.detail["candidate_sha"])) == 40
    assert len(str(ff.detail["failure_output_digest"])) == 64
    assert promoted.accepted is True
