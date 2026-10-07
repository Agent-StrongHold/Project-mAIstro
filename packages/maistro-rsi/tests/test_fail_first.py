"""The fail-first evidence contract (#392): gate, probes, and anti-manufacturing.

Pure tests cover the promotion gate's rejection matrix on composed evidence;
integration tests run the REAL git+pytest probe against throwaway repos (the
same mechanism ``test_red_green_evidence`` exercises, now asserting the full
record: base/candidate SHAs, failing identities, failure digest, reproducibility,
and the manufacturing guards).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from maistro_evolve.improvement import ImprovementKind
from maistro_rsi import fail_first
from maistro_rsi.candidate_fitness import (
    FitnessInputs,
    _mean_quality_at_base,
    compose_scorecard,
)
from maistro_rsi.fail_first import (
    EvidenceContract,
    FailFirstEvidence,
    collect_fail_first_evidence,
    fail_first_gate,
    failure_digest,
    resolve_contract,
)
from maistro_rsi.local_loop import _DEFAULT_OBJECTIVE
from maistro_rsi.trace_notes import TraceNote

_PYTEST_RUNNABLE = (
    subprocess.run([sys.executable, "-m", "pytest", "--version"], capture_output=True).returncode
    == 0
)


def _evidence(**over: object) -> FailFirstEvidence:
    """A fully VALID evidence record; keyword overrides break it."""
    base: dict[str, object] = {
        "base_sha": "b" * 40,
        "candidate_sha": "c" * 40,
        "failing_tests": ["test_src.py::test_f"],
        "failure_digest": failure_digest(["test_src.py::test_f"]),
        "passing_on_candidate": True,
        "candidate_changed_rc": 0,
        "baseline_changed_rc": 1,
        "reproducible": True,
        "config_tainted": False,
        "related": True,
    }
    base.update(over)
    return FailFirstEvidence(**base)  # type: ignore[arg-type]


def _gate(inputs: FitnessInputs):
    return next(g for g in compose_scorecard(inputs).gates if g.name == "fail_first_evidence")


# ---------------------------------------------------------------------------
# Contract resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("declared", "src", "tests", "want"),
    [
        (None, ["m.py"], ["test_m.py"], EvidenceContract.BEHAVIOR),
        ("bug_fix", ["m.py"], ["test_m.py"], EvidenceContract.BEHAVIOR),
        ("new_test", ["m.py"], ["test_m.py"], EvidenceContract.BEHAVIOR),
        ("spec", ["m.py"], ["test_m.py"], EvidenceContract.BEHAVIOR),
        ("doc", ["m.py"], ["test_m.py"], EvidenceContract.REFACTOR),
        ("refactor", ["m.py"], [], EvidenceContract.REFACTOR),
        (None, [], ["test_m.py"], EvidenceContract.CHARACTERIZATION),
        (None, [], [], EvidenceContract.DOCUMENTATION),
        ("backlog", [], [], EvidenceContract.DOCUMENTATION),
    ],
)
def test_contract_resolution(
    declared: str | None, src: list[str], tests: list[str], want: EvidenceContract
) -> None:
    assert resolve_contract(declared, src, tests) is want


def test_default_generic_slot_resolves_to_behavior_contract() -> None:
    # The no-scout fallback slot is declared NEW_TEST (not DOC) precisely so a
    # source-touching candidate under the default objective owes fail-first
    # evidence — the same guarantee as the scout-typed fixer slots (#392).
    assert ImprovementKind.NEW_TEST not in (
        ImprovementKind.REFACTOR,
        ImprovementKind.DOC,
    )
    assert resolve_contract("new_test", ["m.py"], ["test_m.py"]) is EvidenceContract.BEHAVIOR


def test_default_objective_demands_fail_first_proof() -> None:
    assert "FAILS against the current code" in _DEFAULT_OBJECTIVE
    assert "NOT improvement evidence" in _DEFAULT_OBJECTIVE
    # The unenforceable docstring/type-hint escape hatch is gone: a source
    # change the harness cannot prove fail-first must not be offered.
    assert "type hint" not in _DEFAULT_OBJECTIVE


# ---------------------------------------------------------------------------
# The promotion gate: rejection matrix (pure)
# ---------------------------------------------------------------------------


def test_behavior_contract_rejects_missing_evidence() -> None:
    gate = _gate(
        FitnessInputs(tests_passed=True, changed_src=["m.py"], changed_tests=["test_m.py"])
    )
    assert gate.passed is False
    assert "missing fail-first evidence" in gate.reason


def test_source_change_without_any_test_is_missing_evidence() -> None:
    gate = _gate(FitnessInputs(tests_passed=True, changed_src=["m.py"], changed_tests=[]))
    assert gate.passed is False
    assert "missing fail-first evidence" in gate.reason


def test_characterization_only_candidate_cannot_satisfy_improvement_evidence() -> None:
    # A test that passes on the base revision (a behavior snapshot) is not
    # fail-first evidence for a source change — exactly the hole #392 closes.
    ev = _evidence(failing_tests=[], failure_digest="", baseline_changed_rc=0)
    gate = _gate(
        FitnessInputs(
            tests_passed=True, changed_src=["m.py"], changed_tests=["test_m.py"], fail_first=ev
        )
    )
    assert gate.passed is False
    assert "already pass on the base revision" in gate.reason
    assert "characterization" in gate.reason


def test_already_passing_but_green_candidate_still_rejected() -> None:
    ev = _evidence(failing_tests=[], failure_digest="", baseline_changed_rc=0)
    assert ev.status == "already_passing"


def test_non_reproducible_evidence_rejected() -> None:
    ev = _evidence(reproducible=False)
    gate = _gate(
        FitnessInputs(
            tests_passed=True, changed_src=["m.py"], changed_tests=["test_m.py"], fail_first=ev
        )
    )
    assert gate.passed is False
    assert "not reproducible" in gate.reason


def test_config_taint_voids_evidence() -> None:
    ev = _evidence(config_tainted=True)
    gate = _gate(
        FitnessInputs(
            tests_passed=True, changed_src=["m.py"], changed_tests=["test_m.py"], fail_first=ev
        )
    )
    assert gate.passed is False
    assert "configuration/oracle" in gate.reason


def test_unrelated_failing_test_rejected() -> None:
    ev = _evidence(related=False)
    gate = _gate(
        FitnessInputs(
            tests_passed=True, changed_src=["m.py"], changed_tests=["test_m.py"], fail_first=ev
        )
    )
    assert gate.passed is False
    assert "unrelated" in gate.reason


def test_valid_evidence_passes_and_records_the_full_proof() -> None:
    ev = _evidence()
    gate = _gate(
        FitnessInputs(
            tests_passed=True, changed_src=["m.py"], changed_tests=["test_m.py"], fail_first=ev
        )
    )
    assert gate.passed is True
    detail = gate.detail
    assert detail["base_sha"] == "b" * 40
    assert detail["candidate_sha"] == "c" * 40
    assert detail["failing_tests"] == ["test_src.py::test_f"]
    assert detail["failure_digest"].startswith("sha256:")
    assert detail["passing_on_candidate"] is True
    assert detail["reproducible"] is True


def test_valid_evidence_satisfies_even_a_declared_refactor_contract() -> None:
    # Fail-first proof is strictly stronger than the refactor alternative.
    gate = fail_first_gate(EvidenceContract.REFACTOR, _evidence())
    assert gate.passed is True


# ---------------------------------------------------------------------------
# Alternative evidence contracts (pure)
# ---------------------------------------------------------------------------


def test_refactor_contract_requires_a_measured_quality_delta() -> None:
    no_baseline = fail_first_gate(EvidenceContract.REFACTOR, None, quality_delta=None)
    assert no_baseline.passed is False  # fail closed: unverifiable ≠ pass
    no_improvement = fail_first_gate(EvidenceContract.REFACTOR, None, quality_delta=0.0)
    assert no_improvement.passed is False
    improvement = fail_first_gate(EvidenceContract.REFACTOR, None, quality_delta=0.05)
    assert improvement.passed is True
    assert "code-quality composite improved" in improvement.reason


def test_declared_refactor_contract_wiring_judges_the_measured_delta(
    tmp_path: Path, monkeypatch
) -> None:
    """End-to-end wiring (#392): a source-touching candidate DECLARED refactor
    owes no red test, but the loop must actually measure the alternative —
    the code-quality composite of the changed files against their baseline
    versions — and reject the candidate when that delta is absent or does not
    improve. The fail-first gate is the enforcement point either way."""
    from maistro_rsi import candidate_fitness

    repo = _repo(tmp_path)
    (repo / "src.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "candidate refactor")

    monkeypatch.setattr(candidate_fitness, "_run", lambda *a, **k: (True, "exit 0"))
    monkeypatch.setattr(candidate_fitness, "measure_coverage_detailed", lambda *a, **k: (80.0, {}))

    def evaluate() -> object:
        return candidate_fitness.evaluate_candidate(
            str(repo),
            ["src.py"],
            test_command="exit 0",
            baseline_ref="base",
            baseline_coverage=80.0,
            declared_kind=ImprovementKind.REFACTOR,
        )

    def ff_gate(card: object):  # type: ignore[no-untyped-def]
        return next(g for g in card.gates if g.name == "fail_first_evidence")

    # Improvement: the alternative contract is met and recorded.
    monkeypatch.setattr(candidate_fitness, "_mean_quality", lambda *a, **k: (0.9, "cand"))
    monkeypatch.setattr(candidate_fitness, "_mean_quality_at_base", lambda *a, **k: 0.7)
    improved = evaluate()
    gate = ff_gate(improved)
    assert improved.accepted is True
    assert gate.passed is True
    assert gate.detail["contract"] == "refactor"
    assert gate.detail["quality_delta"] == pytest.approx(0.2)

    # No improvement: the same wiring rejects — "clarity" without a measured
    # delta is not evidence.
    monkeypatch.setattr(candidate_fitness, "_mean_quality", lambda *a, **k: (0.6, "cand"))
    regressed = evaluate()
    gate = ff_gate(regressed)
    assert regressed.accepted is False
    assert gate.passed is False
    assert "did not improve" in gate.reason

    # Unverifiable (no baseline composite): fails closed, never passes.
    monkeypatch.setattr(candidate_fitness, "_mean_quality_at_base", lambda *a, **k: None)
    unverifiable = evaluate()
    gate = ff_gate(unverifiable)
    assert unverifiable.accepted is False
    assert "fail closed" in gate.reason


def test_characterization_contract_is_the_test_only_alternative() -> None:
    ok = fail_first_gate(EvidenceContract.CHARACTERIZATION, None, net_new_tests=1)
    assert ok.passed is True
    assert "never fail-first credit" in ok.reason
    strong_assertions = fail_first_gate(
        EvidenceContract.CHARACTERIZATION, None, assertion_score=0.6
    )
    assert strong_assertions.passed is True
    vacuous = fail_first_gate(EvidenceContract.CHARACTERIZATION, None)
    assert vacuous.passed is False
    assert "verifies nothing new" in vacuous.reason


def test_documentation_contract_passes_without_code_evidence() -> None:
    gate = fail_first_gate(EvidenceContract.DOCUMENTATION, None)
    assert gate.passed is True


def test_composed_scorecard_vetoes_behavior_candidate_without_evidence() -> None:
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            baseline_coverage=80.0,
            candidate_coverage=82.0,
            changed_src=["pkg/mod.py"],
            changed_tests=["pkg/tests/test_mod.py"],
        )
    )
    assert sc.accepted is False
    gate = next(g for g in sc.gates if g.name == "fail_first_evidence")
    assert gate.passed is False


# ---------------------------------------------------------------------------
# Status ordering (identity → greenness → reproducibility → guards)
# ---------------------------------------------------------------------------


def test_status_precedence() -> None:
    assert _evidence(related=False).status == "unrelated"
    assert _evidence(config_tainted=True, related=False).status == "config_tainted"
    assert _evidence(reproducible=False, config_tainted=True).status == "non_reproducible"
    assert _evidence(passing_on_candidate=False, reproducible=False).status == (
        "not_green_on_candidate"
    )
    assert _evidence(failing_tests=[]).status == "already_passing"
    assert _evidence().status == "valid"


# ---------------------------------------------------------------------------
# Parsing and static relatedness
# ---------------------------------------------------------------------------


def test_failure_ids_parse_failed_and_error_lines() -> None:
    out = (
        "....\n"
        "FAILED test_src.py::test_f - assert 1 == 2\n"
        "FAILED test_src.py::TestG::test_g - KeyError: 'k'\n"
        "ERROR test_new.py - ImportError: cannot import name 'thing'\n"
        "FAILED test_src.py::test_f - assert 1 == 2\n"  # duplicate ignored
    )
    assert fail_first._failure_ids(out) == [
        "test_src.py::test_f",
        "test_src.py::TestG::test_g",
        "test_new.py",
    ]


def test_related_detection_matches_changed_module_imports(tmp_path: Path) -> None:
    (tmp_path / "test_mod.py").write_text(
        "from helper import g\n\ndef test_g():\n    assert g() == 5\n", encoding="utf-8"
    )

    def _host_read(rel: str) -> str:
        return (tmp_path / rel).read_text(encoding="utf-8")

    assert fail_first._has_related_failure(
        _host_read, ["test_mod.py::test_g"], ["pkg/sub/helper.py"]
    )
    # No reference to the changed module anywhere → unrelated.
    assert not fail_first._has_related_failure(
        _host_read, ["test_mod.py::test_g"], ["completely/other.py"]
    )


def test_related_detection_tolerates_transport_and_parse_failures() -> None:
    """A contained read that dies mid-flight (Docker gone, exec timeout) is
    'no import surface', never a crash (#614) — and unparsable test source
    falls back to the textual import match instead of raising."""

    def _unreadable(rel: str) -> str:
        raise RuntimeError("sandbox transport died")

    assert not fail_first._has_related_failure(_unreadable, ["test_mod.py::test_g"], ["helper.py"])

    def _syntax_error(rel: str) -> str:
        return "from helper import g\n def broken(:\n"

    assert fail_first._has_related_failure(_syntax_error, ["test_mod.py::test_g"], ["helper.py"])

    def _null_bytes(rel: str) -> str:
        return "import helper\x00"

    assert fail_first._has_related_failure(_null_bytes, ["test_mod.py::test_g"], ["helper.py"])


def test_failure_digest_is_stable_and_identity_sensitive() -> None:
    a = failure_digest(["t.py::test_a", "t.py::test_b"])
    b = failure_digest(["t.py::test_b", "t.py::test_a"])
    assert a == b  # order-independent
    assert a != failure_digest(["t.py::test_a"])


# ---------------------------------------------------------------------------
# The refactor contract's baseline half: real git (git show + real scorer)
# ---------------------------------------------------------------------------


def test_refactor_baseline_quality_scores_the_base_revision(tmp_path: Path) -> None:
    """_mean_quality_at_base scores the changed files AS THEY WERE on the
    baseline ref — the left side of the refactor contract's quality delta."""
    repo = _repo(tmp_path)
    baseline_quality = _mean_quality_at_base(repo, "base", ["src.py"])
    assert baseline_quality is not None
    assert 0.0 <= baseline_quality <= 1.0


def test_refactor_baseline_quality_skips_files_absent_on_base(tmp_path: Path) -> None:
    """A NEW module has no baseline version to improve upon — it contributes
    nothing to the mean; when NO changed file is readable on the base the
    refactor contract has no verifiable left side and gets None (fail closed)."""
    repo = _repo(tmp_path)
    (repo / "newmod.py").write_text("def h():\n    return 7\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "candidate adds newmod")

    mixed = _mean_quality_at_base(repo, "HEAD~1", ["src.py", "newmod.py"])
    assert mixed is not None  # src.py is readable on the base: it scores
    only_new = _mean_quality_at_base(repo, "HEAD~1", ["newmod.py"])
    assert only_new is None  # nothing readable: the contract cannot verify


# ---------------------------------------------------------------------------
# The real probe (git + pytest)
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.co")
    _git(repo, "config", "user.name", "t")
    (repo / "src.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")
    _git(repo, "branch", "base")
    return repo


def _commit_candidate(repo: Path) -> None:
    (repo / "src.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    (repo / "test_src.py").write_text(
        "from src import f\n\ndef test_f():\n    assert f() == 2\n", encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "candidate")


@pytest.mark.skipif(not _PYTEST_RUNNABLE, reason="pytest not runnable as a subprocess")
def test_probe_records_the_full_red_green_proof(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _commit_candidate(repo)
    base_sha = subprocess.run(
        ["git", "rev-parse", "base"], cwd=str(repo), capture_output=True, text=True
    ).stdout.strip()
    candidate_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True
    ).stdout.strip()

    ev = collect_fail_first_evidence(repo, "base", ["src.py"], ["test_src.py"], timeout=120)

    assert ev is not None
    assert ev.status == "valid"
    # The recorded revisions pin the exact base and candidate.
    assert ev.base_sha == base_sha
    assert ev.candidate_sha == candidate_sha
    assert ev.failing_tests == ["test_src.py::test_f"]
    assert ev.failure_digest == failure_digest(ev.failing_tests)
    assert ev.passing_on_candidate is True
    assert ev.reproducible is True  # second base probe reproduced the red
    assert ev.related is True  # the failing test imports the changed module
    # Red→green signal view shares the same probe's exit codes.
    tdd = ev.tdd_view(["test_src.py"])
    assert tdd.baseline_changed_rc not in (None, 0)
    assert tdd.candidate_changed_rc == 0
    # The candidate source was restored after the probes.
    assert "return 2" in (repo / "src.py").read_text(encoding="utf-8")


@pytest.mark.skipif(not _PYTEST_RUNNABLE, reason="pytest not runnable as a subprocess")
def test_probe_flags_flaky_red_as_non_reproducible(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    _commit_candidate(repo)
    calls = {"n": 0}

    def fake_run(
        repo_dir: object,
        selectors: object,
        *,
        timeout: int = 600,
        extra_args=(),
        interpreter=None,
        execute=None,
    ):
        calls["n"] += 1
        if calls["n"] == 1:
            return 0, ""  # candidate: green
        if calls["n"] == 2:
            return 1, "FAILED test_src.py::test_f - assert 1 == 2\n"  # base probe 1: red
        return 0, ""  # base probe 2: green — the red did not reproduce

    monkeypatch.setattr(fail_first, "run_test_selection", fake_run)
    ev = collect_fail_first_evidence(repo, "base", ["src.py"], ["test_src.py"], timeout=120)
    assert ev is not None
    assert ev.status == "non_reproducible"
    assert ev.failing_tests == ["test_src.py::test_f"]
    assert ev.reproducible is False
    assert "return 2" in (repo / "src.py").read_text(encoding="utf-8")


@pytest.mark.skipif(not _PYTEST_RUNNABLE, reason="pytest not runnable as a subprocess")
def test_probe_skips_second_run_when_already_passing(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    _commit_candidate(repo)
    calls = {"n": 0}

    def fake_run(
        repo_dir: object,
        selectors: object,
        *,
        timeout: int = 600,
        extra_args=(),
        interpreter=None,
        execute=None,
    ):
        calls["n"] += 1
        return 0, ""  # green everywhere: a characterization snapshot

    monkeypatch.setattr(fail_first, "run_test_selection", fake_run)
    ev = collect_fail_first_evidence(repo, "base", ["src.py"], ["test_src.py"], timeout=120)
    assert ev is not None
    assert ev.status == "already_passing"
    assert calls["n"] == 2  # candidate + one base probe; no wasted second run


@pytest.mark.skipif(not _PYTEST_RUNNABLE, reason="pytest not runnable as a subprocess")
def test_probe_handles_new_source_module_written_test_first(tmp_path: Path) -> None:
    """A candidate that adds a NEW module and its test proves fail-first by
    ImportError: with the module removed (its base state is absence), the
    test cannot even import it — red on base, green once the module lands."""
    repo = _repo(tmp_path)
    (repo / "newmod.py").write_text("def h():\n    return 7\n", encoding="utf-8")
    (repo / "test_newmod.py").write_text(
        "from newmod import h\n\ndef test_h():\n    assert h() == 7\n", encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "candidate: new module + test written first")

    ev = collect_fail_first_evidence(repo, "base", ["newmod.py"], ["test_newmod.py"], timeout=120)

    assert ev is not None
    assert ev.status == "valid"
    assert ev.failing_tests == ["test_newmod.py"]  # file-level: ImportError on base
    assert ev.reproducible is True
    # The new module was restored after the probe.
    assert (repo / "newmod.py").is_file()


@pytest.mark.skipif(not _PYTEST_RUNNABLE, reason="pytest not runnable as a subprocess")
def test_probe_handles_candidate_deletion_without_resurrecting(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "gone.py").write_text("z = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add gone.py")
    # `base` (from _repo) still points at the commit before gone.py existed.
    (repo / "gone.py").unlink()
    (repo / "src.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    (repo / "test_src.py").write_text(
        "import os\n\nfrom src import f\n\n"
        "def test_f():\n    assert f() == 2\n\n"
        "def test_gone_is_gone():\n    assert not os.path.exists('gone.py')\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "candidate: delete gone.py, fix f")

    ev = collect_fail_first_evidence(
        repo, "base", ["src.py", "gone.py"], ["test_src.py"], timeout=120
    )

    assert ev is not None
    assert ev.status == "valid"
    assert ev.passing_on_candidate is True
    # The deletion survived the probe: gone.py was NOT resurrected.
    assert not (repo / "gone.py").is_file()


@pytest.mark.skipif(not _PYTEST_RUNNABLE, reason="pytest not runnable as a subprocess")
def test_config_edit_taints_otherwise_valid_evidence(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _commit_candidate(repo)
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\naddopts = '-q'\n", "utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "config edit")

    clean = collect_fail_first_evidence(repo, "base", ["src.py"], ["test_src.py"], timeout=120)
    assert clean is not None and clean.status == "valid"

    tainted = collect_fail_first_evidence(
        repo,
        "base",
        ["src.py"],
        ["test_src.py"],
        timeout=120,
        config_files_changed=["pyproject.toml"],
    )
    assert tainted is not None
    assert tainted.status == "config_tainted"
    # Same probe results — only the manufacturing guard flips the verdict.
    assert tainted.failing_tests == clean.failing_tests


def test_test_only_diff_collects_no_evidence(tmp_path: Path) -> None:
    # Nothing source-touching: a test-only diff never claims fail-first.
    assert collect_fail_first_evidence(tmp_path, "base", [], ["test_x.py"], timeout=60) is None
    assert collect_fail_first_evidence(tmp_path, "base", ["m.py"], [], timeout=60) is None


# ---------------------------------------------------------------------------
# The promotion record carries the evidence
# ---------------------------------------------------------------------------


def test_trace_note_roundtrips_fail_first_record() -> None:
    note = TraceNote(
        cycle=3,
        target="pkg/mod.py",
        accepted=True,
        kind="bug_fix",
        model="m",
        files_touched=2,
        fail_first={
            "status": "valid",
            "base_sha": "b" * 40,
            "candidate_sha": "c" * 40,
            "failing_tests": ["test_mod.py::test_f"],
            "failure_digest": "sha256:deadbeef",
            "passing_on_candidate": True,
        },
    )
    back = TraceNote.from_json(note.to_json())
    assert back.fail_first is not None
    assert back.fail_first["status"] == "valid"
    assert back.fail_first["failure_digest"] == "sha256:deadbeef"


def test_older_note_without_fail_first_still_parses() -> None:
    note = TraceNote(cycle=1, target="t", accepted=True, kind="doc", model="m", files_touched=1)
    back = TraceNote.from_json(note.to_json())
    assert back.fail_first is None
