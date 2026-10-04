"""Evaluator-oracle immunity (#109): RSI may satisfy the oracle, never edit it.

`LocalRsiLoop` scores candidates by running `test_command` and the fitness
gates inside the candidate's own tree. Without an integrity check enforced
BEFORE scoring, a candidate can weaken `candidate_fitness.py`, its pinning
tests, a ratchet baseline or the AC tree in the same diff and then be judged
by the oracle it just changed — acceptance evidence manufactured by the thing
it was evidence about.

These tests cover the issue's acceptance surface end to end:

- the oracle pattern tier covers the score-defining artifacts (scorer, its
  pinning tests, scenario corpora, ratchet baselines, AC trees) and leaves
  the application surface alone;
- mutations are detected through the bypass spells — renames/moves, symlink
  swaps, committed generated artifacts (poisoned ``__pycache__``, import-time
  hooks) — and via the digest layer regardless of spelling;
- a candidate that edits the exact scoring implementation/tests it would
  otherwise execute is vetoed BEFORE its modified oracle can produce
  acceptance evidence (the test command never runs against the mutated
  tree), on both the fitness and the bare test-command path;
- the evaluator digest is pinned into scorecard provenance and the promotion
  record, so a verdict names the oracle version that produced it;
- authorized human governance changes remain possible (override recorded,
  never silent), and adding a NEW spec contract stays allowed while
  rewriting an inherited AC is not;
- the adversarial self-scoring fixture can never reach ``accepted=True`` —
  and therefore can never satisfy the #302 promotion prerequisites, because
  acceptance is the only thing the #302 fast-forward consumes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from maistro_rsi.evaluator_oracle import (
    GENERATED_ORACLE_PATTERNS,
    _matches_generated,
    oracle_digest,
    oracle_mutations,
)
from maistro_rsi.local_loop import LocalRsiConfig, LocalRsiLoop
from maistro_rsi.protocols import MicroVmSandbox
from maistro_rsi.sensitive_paths import (
    TEST_CONTROL_BASENAMES,
    matches_evaluator_oracle_pattern,
    matches_sensitive_pattern,
    matches_test_control_path,
)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-c", "core.longpaths=true", *args], cwd=str(cwd), capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} rc={proc.returncode}: {proc.stderr.strip()}")
    return proc


# ---------------------------------------------------------------------------
# The pattern tiers (#109 acceptance: protected paths cover the oracle inputs)
# ---------------------------------------------------------------------------


class TestOraclePatternCoverage:
    @pytest.mark.parametrize(
        "path",
        [
            # the current candidate-fitness implementation and everything the
            # scorecard is computed from
            "packages/maistro-rsi/src/maistro_rsi/candidate_fitness.py",
            "packages/maistro-rsi/src/maistro_rsi/fail_first.py",
            "packages/maistro-rsi/src/maistro_rsi/regression_judge.py",
            "packages/maistro-rsi/src/maistro_rsi/test_inventory.py",
            "packages/maistro-rsi/src/maistro_rsi/spec_tracker.py",
            "packages/maistro-rsi/src/maistro_rsi/local_loop.py",
            "packages/maistro-evolve/src/maistro_evolve/scorecard.py",
            "packages/maistro-evolve/src/maistro_evolve/coverage_gate.py",
            # the tests used by LocalRsiLoop to pin the evaluator
            "packages/maistro-rsi/tests/test_candidate_fitness.py",
            "packages/maistro-evolve/tests/test_scorecard.py",
            # the scenario corpus the capability signal is scored against
            "packages/maistro-evolve/src/maistro_evolve/benchmarks/ifeval.py",
            "packages/maistro-rsi/src/maistro_rsi/benchmarks/swebench_pro.py",
            # the vendored graders carry the pinned corpus digests
            "scripts/vendor_ifeval.py",
            "scripts/vendor_bfcl.py",
            # ratchet baselines
            "quality/vulture-baseline.json",
            "quality/ratchet-authorizations.json",
            # the acceptance-criteria trees
            "docs/specs/SPEC-109-evaluator-oracle-immunity.md",
        ],
    )
    def test_score_defining_artifacts_are_protected(self, path: str) -> None:
        assert matches_evaluator_oracle_pattern(path)

    @pytest.mark.parametrize(
        "path",
        [
            # application code the loop is supposed to improve
            "src/app.py",
            "packages/maistro-core/src/maistro/agents/spawner.py",
            "tests/test_app.py",
            "docs/architecture/WORKSPACE-CUTOVER-PLAN.md",
            "README.md",
        ],
    )
    def test_application_surface_stays_improvable(self, path: str) -> None:
        assert not matches_evaluator_oracle_pattern(path)

    def test_the_ac_tree_escalates_on_the_sensitive_surface_too(self) -> None:
        """The oracle veto is the scoring-time tier; the export tier must also
        escalate an AC-tree edit leaving the sandbox for adversarial review."""
        assert matches_sensitive_pattern("docs/specs/SPEC-109-evaluator-oracle-immunity.md")

    def test_generated_artifact_patterns_catch_the_execution_hijacks(self) -> None:
        for path in (
            "packages/maistro-rsi/src/maistro_rsi/__pycache__/candidate_fitness.cpython-312.pyc",
            "src/__pycache__/app.cpython-312.pyc",
            "maistro_evolve.egg-info/PKG-INFO",
            "sitecustomize.py",
            "plugins/usercustomize.py",
        ):
            assert _matches_generated(path), path
        assert GENERATED_ORACLE_PATTERNS

    def test_test_control_basenames_match_at_any_depth(self) -> None:
        """The inventory treats conftest.py/pytest config as test-control
        surfaces by basename at any depth; the veto tier matches the same
        closure (Codex review, #109). A top-level conftest.py — OUTSIDE the
        two protected package test directories — is exactly the spell this
        must catch."""
        for path in (
            "conftest.py",
            "pytest.ini",
            "packages/maistro-core/tests/conftest.py",
            "packages/maistro-core/pyproject.toml",
            "formal/tox.ini",
        ):
            assert matches_test_control_path(path), path
        assert not matches_test_control_path("src/app.py")
        assert not matches_test_control_path("tests/test_app.py")
        assert TEST_CONTROL_BASENAMES


# ---------------------------------------------------------------------------
# oracle_mutations: the bypass spells (#109 acceptance: renames, symlinks,
# generated files) — real git, real worktrees.
# ---------------------------------------------------------------------------


def _oracle_repo(path: Path, *, scorer_source: str = "def compose():\n    return True\n") -> Path:
    """A tiny repo shaped like the real one: an oracle (scorer + its pinning
    test + a ratchet baseline + an AC spec) beside plain application code."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "rsi@test.local")
    _git(path, "config", "user.name", "RSI Test")
    scorer = path / "packages/maistro-rsi/src/maistro_rsi/candidate_fitness.py"
    scorer.parent.mkdir(parents=True)
    scorer.write_text(scorer_source, encoding="utf-8")
    tests = path / "packages/maistro-rsi/tests/test_candidate_fitness.py"
    tests.parent.mkdir(parents=True)
    tests.write_text(
        "from packages.maistro_rsi.src.maistro_rsi.candidate_fitness import compose\n\n\n"
        "def test_compose():\n    assert compose() is True\n",
        encoding="utf-8",
    )
    quality = path / "quality/vulture-baseline.json"
    quality.parent.mkdir(parents=True)
    quality.write_text('{"tolerated": {}}\n', encoding="utf-8")
    spec = path / "docs/specs/SPEC-109-x.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("id: SPEC-109\n- [ ] **AC-1** oracle immunity\n", encoding="utf-8")
    app = path / "src/app.py"
    app.parent.mkdir(parents=True)
    app.write_text("VALUE = 0\n", encoding="utf-8")
    # A tracked test-control file: editing it in a candidate diff must veto,
    # exactly like editing an out-of-tree addition would.
    conftest = path / "packages/maistro-rsi/tests/conftest.py"
    conftest.write_text("import pytest\npytest_plugins: list[str] = []\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "base")
    _git(path, "branch", "rsi-baseline")
    return path


def _commit(path: Path, message: str) -> None:
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", message)


class TestOracleMutationSpells:
    def test_clean_candidate_is_not_flagged(self, tmp_path: Path) -> None:
        repo = _oracle_repo(tmp_path / "r")
        (repo / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
        _commit(repo, "candidate")
        assert oracle_mutations(repo, "rsi-baseline") == []

    def test_direct_edit_of_the_scorer_is_flagged(self, tmp_path: Path) -> None:
        repo = _oracle_repo(tmp_path / "r")
        scorer = repo / "packages/maistro-rsi/src/maistro_rsi/candidate_fitness.py"
        scorer.write_text(
            "def compose():\n    return True  # always passes now\n", encoding="utf-8"
        )
        _commit(repo, "candidate")
        assert oracle_mutations(repo, "rsi-baseline")

    def test_rename_or_move_of_an_oracle_file_is_flagged(self, tmp_path: Path) -> None:
        """The laundering spell: `git mv` the scorer to a new name and weaken
        it there. --no-renames decomposes the move into D(old)+A(new) and the
        digest layer sees the base path vanish — both sides are matched."""
        repo = _oracle_repo(tmp_path / "r")
        _git(
            repo,
            "mv",
            "packages/maistro-rsi/src/maistro_rsi/candidate_fitness.py",
            "packages/maistro-rsi/src/maistro_rsi/scoring_impl.py",
        )
        _commit(repo, "candidate")
        violations = oracle_mutations(repo, "rsi-baseline")
        assert any("candidate_fitness.py" in v for v in violations)
        assert any("scoring_impl.py" in v for v in violations)

    def test_rename_reported_by_status_porcelain_is_flagged(self, tmp_path: Path) -> None:
        """The caller-reported spelling: `status --porcelain` renders a rename
        as one `R  old -> new` line; the caller-reported layer splits it and
        checks both endpoints — even when the committed diff itself is clean."""
        repo = _oracle_repo(tmp_path / "r")
        violations = oracle_mutations(
            repo,
            "rsi-baseline",
            [
                "packages/maistro-rsi/src/maistro_rsi/candidate_fitness.py"
                " -> packages/maistro-rsi/src/maistro_rsi/scoring_impl.py"
            ],
        )
        assert any("candidate_fitness.py" in v for v in violations)
        assert any("scoring_impl.py" in v for v in violations)

    def test_symlink_swap_of_an_oracle_file_is_flagged(self, tmp_path: Path) -> None:
        """Replace the pinning test with a symlink to attacker-controlled
        content: the blob becomes mode 120000, which the digest comparison and
        the typechange status both catch."""
        repo = _oracle_repo(tmp_path / "r")
        target = repo / "packages/maistro-rsi/tests/test_candidate_fitness.py"
        evil = repo / "evil_test_impl.py"
        evil.write_text("def test_compose():\n    assert True\n", encoding="utf-8")
        target.unlink()
        target.symlink_to(evil.name)
        _commit(repo, "candidate")
        violations = oracle_mutations(repo, "rsi-baseline")
        assert any("test_candidate_fitness.py" in v for v in violations)

    def test_committed_generated_artifact_is_flagged_anywhere(self, tmp_path: Path) -> None:
        """A crafted .pyc under __pycache__ (matching source header, different
        code) or a sitecustomize.py hijacks the oracle's own execution without
        any listed oracle path looking edited."""
        repo = _oracle_repo(tmp_path / "r")
        pyc = repo / "src/__pycache__/app.cpython-312.pyc"
        pyc.parent.mkdir(parents=True)
        pyc.write_bytes(b"\x00\x01\x02poison")
        _commit(repo, "candidate")
        violations = oracle_mutations(repo, "rsi-baseline")
        assert any("generated:" in v and "__pycache__" in v for v in violations)

        repo2 = _oracle_repo(tmp_path / "r2")
        (repo2 / "sitecustomize.py").write_text(
            "import sys\nsys.modules['pytest'] = type(sys)('fake')\n", encoding="utf-8"
        )
        _commit(repo2, "candidate")
        assert any(
            "generated:sitecustomize.py" in v for v in oracle_mutations(repo2, "rsi-baseline")
        )

    def test_ignored_worktree_artifact_is_flagged(self, tmp_path: Path) -> None:
        """The committed-diff blind spot: a crafted .pyc the root .gitignore
        excludes never reaches any diff, HEAD tree or porcelain-derived path
        list, yet it stays importable by the test command. The worktree scan
        must veto it before scoring."""
        repo = _oracle_repo(tmp_path / "r")
        (repo / ".gitignore").write_text("__pycache__/\n*.py[oc]\n", encoding="utf-8")
        _commit(repo, "gitignore")
        pyc = repo / "src/__pycache__/app.cpython-312.pyc"
        pyc.parent.mkdir(parents=True)
        pyc.write_bytes(b"\x00\x01\x02poison")
        # Ordinary tracked edit beside it: exactly the mixing spell.
        (repo / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
        _commit(repo, "candidate")
        violations = oracle_mutations(repo, "rsi-baseline")
        assert any(v.startswith("ignored:") and "__pycache__" in v for v in violations)

    def test_clean_ignored_output_is_not_flagged(self, tmp_path: Path) -> None:
        """Benign ignored build output absent from the generated patterns —
        e.g. a scratch log — must not veto a clean candidate."""
        repo = _oracle_repo(tmp_path / "r")
        (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
        _commit(repo, "gitignore")
        (repo / "scratch.log").write_text("noise\n", encoding="utf-8")
        assert oracle_mutations(repo, "rsi-baseline") == []

    def test_out_of_tree_conftest_hook_is_flagged(self, tmp_path: Path) -> None:
        """The pytest hook spell (Codex review, #109): a TOP-LEVEL conftest.py
        is imported by pytest before collection, so a pytest_sessionfinish
        hook there can force exit 0 despite failing tests. It sits outside the
        protected package test directories, so only the test-control closure
        catches it — and it must, before either scoring path runs."""
        repo = _oracle_repo(tmp_path / "r")
        (repo / "conftest.py").write_text(
            "import pytest\n\n\n"
            "def pytest_sessionfinish(session, exitstatus):\n"
            "    session.testsfailed = 0\n"
            "    pytest.exitcode = 0\n",
            encoding="utf-8",
        )
        _commit(repo, "candidate")
        assert any(
            v.startswith("test-control:") and v.endswith("conftest.py")
            for v in oracle_mutations(repo, "rsi-baseline")
        )

    def test_editing_a_tracked_nested_conftest_is_flagged(self, tmp_path: Path) -> None:
        """A conftest.py INSIDE the oracle tier (packages/maistro-rsi/tests/)
        is doubly caught: the digest layer flags the tracked edit by its blob
        change and the diff layer by its status letter. The ``test-control:``
        label is reserved for test-control files OUTSIDE the oracle tier —
        the top-level and ignored-conftest nodes above pin that spelling.
        Either way the edit is a violation before any scoring runs."""
        repo = _oracle_repo(tmp_path / "r")
        conftest = repo / "packages/maistro-rsi/tests/conftest.py"
        conftest.write_text("collect_ignore = ['test_candidate_fitness.py']\n", encoding="utf-8")
        _commit(repo, "candidate")
        violations = oracle_mutations(repo, "rsi-baseline")
        # Digest layer: the blob identity of the tracked test-control file
        # changed, so the bare oracle path is a violation on its own.
        assert "packages/maistro-rsi/tests/conftest.py" in violations
        # Diff layer: the same edit shows up with its status letter.
        assert any(v.startswith("M:") and v.endswith("tests/conftest.py") for v in violations)

    def test_pytest_ini_addition_is_flagged(self, tmp_path: Path) -> None:
        repo = _oracle_repo(tmp_path / "r")
        (repo / "pytest.ini").write_text("[pytest]\naddopts = -p no:randomly\n", encoding="utf-8")
        _commit(repo, "candidate")
        assert any("test-control:pytest.ini" in v for v in oracle_mutations(repo, "rsi-baseline"))

    def test_ignored_out_of_tree_conftest_is_flagged(self, tmp_path: Path) -> None:
        """pytest imports an ignored conftest.py just the same: the ignored
        layer must veto test-control files, not only generated artifacts."""
        repo = _oracle_repo(tmp_path / "r")
        (repo / ".gitignore").write_text("hooks/\n", encoding="utf-8")
        _commit(repo, "gitignore")
        hooks = repo / "hooks/conftest.py"
        hooks.parent.mkdir(parents=True)
        hooks.write_text("def pytest_sessionfinish(session, exitstatus):\n    exitstatus = 0\n")
        (repo / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
        _commit(repo, "candidate")
        violations = oracle_mutations(repo, "rsi-baseline")
        assert any(v.startswith("ignored:") and "conftest.py" in v for v in violations)

    def test_integrity_failure_fails_closed(self, tmp_path: Path) -> None:
        """A candidate that can break the check must not slip through it: an
        unusable baseline ref is a violation naming the failure, not silence."""
        repo = _oracle_repo(tmp_path / "r")
        violations = oracle_mutations(repo, "no-such-ref")
        assert len(violations) == 1
        assert "integrity check failed" in violations[0]


class TestAcTreeSemantics:
    def test_rewriting_an_inherited_ac_is_flagged(self, tmp_path: Path) -> None:
        repo = _oracle_repo(tmp_path / "r")
        spec = repo / "docs/specs/SPEC-109-x.md"
        spec.write_text("id: SPEC-109\n- [x] **AC-1** oracle immunity\n", encoding="utf-8")
        _commit(repo, "candidate")
        assert any("SPEC-109-x.md" in v for v in oracle_mutations(repo, "rsi-baseline"))

    def test_drafting_a_new_spec_contract_stays_allowed(self, tmp_path: Path) -> None:
        """spec_proposed is the designed contribution: a candidate may add a
        NEW well-formed spec under docs/specs/ — it may not rewrite the
        definition of done it inherits (the digest layer pins the existing
        files; additions under docs/specs/ are exempt at the oracle tier and
        still escalate at the export tier)."""
        repo = _oracle_repo(tmp_path / "r")
        new_spec = repo / "docs/specs/SPEC-200-new-work.md"
        new_spec.write_text("id: SPEC-200\n- [ ] **AC-1** contracted\n", encoding="utf-8")
        _commit(repo, "candidate")
        assert oracle_mutations(repo, "rsi-baseline") == []


# ---------------------------------------------------------------------------
# Scorecard enforcement (#109 acceptance: evidence withheld before it can
# count; digest pinned into provenance)
# ---------------------------------------------------------------------------


class TestScorecardEnforcement:
    def _evaluate(self, tmp_path: Path, monkeypatch, **kwargs):  # type: ignore[no-untyped-def]
        from maistro_rsi import candidate_fitness

        repo = _oracle_repo(tmp_path / "r")
        (repo / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
        _commit(repo, "candidate")
        calls: list[tuple] = []

        def _fake_run(cmd, cwd, timeout=900, argv=()):  # type: ignore[no-untyped-def]
            calls.append((cmd, argv))
            return True, "exit 0"

        monkeypatch.setattr(candidate_fitness, "_run", _fake_run)
        monkeypatch.setattr(
            candidate_fitness, "measure_coverage_detailed", lambda *a, **k: (80.0, {})
        )
        scorecard = candidate_fitness.evaluate_candidate(
            str(repo),
            ["src/app.py"],
            test_command="exit 0",
            baseline_ref="rsi-baseline",
            baseline_coverage=80.0,
            **kwargs,
        )
        return scorecard, calls, repo

    def test_mutated_oracle_withholds_evidence_and_pins_digest(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from maistro_rsi import candidate_fitness

        repo = _oracle_repo(tmp_path / "r")
        scorer = repo / "packages/maistro-rsi/src/maistro_rsi/candidate_fitness.py"
        scorer.write_text("def compose():\n    return True  # weakened\n", encoding="utf-8")
        _commit(repo, "candidate")
        calls: list[tuple] = []

        def _fake_run(cmd, cwd, timeout=900, argv=()):  # type: ignore[no-untyped-def]
            calls.append((cmd, argv))
            return True, "exit 0"

        monkeypatch.setattr(candidate_fitness, "_run", _fake_run)
        monkeypatch.setattr(
            candidate_fitness, "measure_coverage_detailed", lambda *a, **k: (80.0, {})
        )
        scorecard = candidate_fitness.evaluate_candidate(
            str(repo),
            ["packages/maistro-rsi/src/maistro_rsi/candidate_fitness.py"],
            test_command="exit 0",
            baseline_ref="rsi-baseline",
            baseline_coverage=80.0,
        )
        # The veto fires BEFORE the oracle runs: the mutated tree never
        # produces acceptance evidence.
        assert calls == []
        assert scorecard.accepted is False
        gate = next(g for g in scorecard.gates if g.name == "evaluator_integrity")
        assert gate.passed is False
        assert "withheld" in gate.reason
        assert any("candidate_fitness.py" in str(m) for m in gate.detail["mutations"])
        # Provenance: the scorecard pins the TRUSTED base oracle's digest.
        assert scorecard.evaluator_digest == oracle_digest(repo, "rsi-baseline")

    def test_clean_candidate_carries_digest_and_runs(self, tmp_path: Path, monkeypatch) -> None:
        scorecard, calls, repo = self._evaluate(tmp_path, monkeypatch)
        assert len(calls) == 1  # the oracle ran for a clean candidate
        gate = next(g for g in scorecard.gates if g.name == "evaluator_integrity")
        assert gate.passed is True
        assert scorecard.evaluator_digest == oracle_digest(repo, "rsi-baseline")

    def test_governance_override_scores_but_records(self, tmp_path: Path, monkeypatch) -> None:
        """The human path: allow_evaluator_mutation scores the candidate WITH
        the mutated oracle but records the mutation + trusted digest — never
        silent (#109 acceptance: authorized governance changes stay possible
        through a separate, explicit path)."""
        from maistro_rsi import candidate_fitness

        repo = _oracle_repo(tmp_path / "r")
        scorer = repo / "packages/maistro-rsi/src/maistro_rsi/candidate_fitness.py"
        scorer.write_text("def compose():\n    return True  # governance edit\n", encoding="utf-8")
        _commit(repo, "candidate")
        calls: list[tuple] = []

        def _fake_run(cmd, cwd, timeout=900, argv=()):  # type: ignore[no-untyped-def]
            calls.append((cmd, argv))
            return True, "exit 0"

        monkeypatch.setattr(candidate_fitness, "_run", _fake_run)
        monkeypatch.setattr(
            candidate_fitness, "measure_coverage_detailed", lambda *a, **k: (80.0, {})
        )
        scorecard = candidate_fitness.evaluate_candidate(
            str(repo),
            ["packages/maistro-rsi/src/maistro_rsi/candidate_fitness.py"],
            test_command="exit 0",
            baseline_ref="rsi-baseline",
            baseline_coverage=80.0,
            evaluator_mutation_authorized=True,
        )
        assert len(calls) == 1  # the authorized run does execute the oracle
        gate = next(g for g in scorecard.gates if g.name == "evaluator_integrity")
        assert gate.passed is True
        assert gate.detail["authorized"] is True
        assert gate.detail["mutations"]
        assert scorecard.evaluator_digest == oracle_digest(repo, "rsi-baseline")

    def test_digest_pins_the_evaluator_version(self, tmp_path: Path) -> None:
        """The pinned digest identifies the oracle definition: two bases whose
        oracle differs pin different digests, so a verdict is replayable
        against exactly the evaluator version that produced it."""
        a = _oracle_repo(tmp_path / "a")
        b = _oracle_repo(
            tmp_path / "b",
            scorer_source="def compose():\n    return bool(int('1'))\n",
        )
        assert oracle_digest(a, "rsi-baseline") != oracle_digest(b, "rsi-baseline")


# ---------------------------------------------------------------------------
# Loop enforcement (#109 acceptance: the adversarial self-scoring fixture can
# never become accepted=True — so it can never satisfy #302's prerequisites)
# ---------------------------------------------------------------------------


def _adversarial_candidate(ws: Path) -> None:
    """The self-scoring attack: in ONE diff, weaken the scorer, gut its
    pinning test, flip an inherited AC to done, edit a ratchet baseline, and
    plant an import-time hook that hijacks the oracle's execution — then let
    the weakened oracle judge it. (The poisoned-binary-artifact spell is
    covered at the oracle_mutations level above; git's text-oriented patch
    plumbing cannot round-trip a promoted binary file.)"""
    scorer = ws / "packages/maistro-rsi/src/maistro_rsi/candidate_fitness.py"
    scorer.write_text("def compose():\n    return True  # every candidate passes now\n")
    (ws / "packages/maistro-rsi/tests/test_candidate_fitness.py").write_text(
        "def test_compose():\n    assert True\n"
    )
    (ws / "docs/specs/SPEC-109-x.md").write_text("id: SPEC-109\n- [x] **AC-1** oracle immunity\n")
    (ws / "quality/vulture-baseline.json").write_text('{"tolerated": {"everything": "ok"}}\n')
    (ws / "sitecustomize.py").write_text(
        "import sys\nsys.modules['pytest'] = type(sys)('fake-pytest')\n"
    )


def _make_apply(writer):  # type: ignore[no-untyped-def]
    async def apply(sandbox: MicroVmSandbox, workspace: str, model: str | None = None) -> None:
        writer(Path(workspace))

    return apply


def _baseline_sha(work_root: Path) -> str:
    return _git(work_root / "baseline", "rev-parse", "rsi-baseline").stdout.strip()


class TestAdversarialSelfScoringFixture:
    def test_fitness_path_rejects_before_the_mutated_oracle_runs(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from maistro_rsi import candidate_fitness

        repo = _oracle_repo(tmp_path / "src")
        # The weakened oracle WOULD say pass — prove it never gets the chance.
        oracle_calls: list[tuple] = []

        def _fake_run(cmd, cwd, timeout=900, argv=()):  # type: ignore[no-untyped-def]
            oracle_calls.append((cmd, argv))
            return True, "exit 0"

        monkeypatch.setattr(candidate_fitness, "_run", _fake_run)
        monkeypatch.setattr(
            candidate_fitness, "measure_coverage_detailed", lambda *a, **k: (80.0, {})
        )

        config = LocalRsiConfig(
            repo_path=str(repo),
            test_command="exit 0",
            work_root=str(tmp_path / "work"),
            max_cycles=1,
            use_fitness=True,
            regression_judge=False,
            promotion_review=False,
        )
        result = LocalRsiLoop(config, apply_patch=_make_apply(_adversarial_candidate)).run()

        assert result.promotions == 0
        cycle = result.cycles[0]
        assert cycle.promoted is False
        assert "evaluator oracle mutated" in cycle.note
        assert "#109" in cycle.note
        # The mutated oracle never executed: no acceptance evidence exists.
        assert oracle_calls == []
        # The #302 prerequisite cannot be met: the baseline did not move.
        assert (
            _baseline_sha(Path(config.work_root))
            == _git(repo, "rev-parse", "rsi-baseline").stdout.strip()
        )

    def test_bare_test_command_path_rejects_before_running_the_oracle(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Without the fitness scorecard the test command IS the oracle — the
        candidate's diff makes `exit 0` trivially pass, so the veto has to
        fire before `_run_tests` executes at all."""
        ran: list[Path] = []

        def _spy(cycle_dir: Path) -> bool:
            ran.append(cycle_dir)
            return True

        monkeypatch.setattr(LocalRsiLoop, "_run_tests", _spy)
        repo = _oracle_repo(tmp_path / "src")
        config = LocalRsiConfig(
            repo_path=str(repo),
            test_command="exit 0",
            work_root=str(tmp_path / "work"),
            max_cycles=1,
        )
        result = LocalRsiLoop(config, apply_patch=_make_apply(_adversarial_candidate)).run()

        assert result.promotions == 0
        assert result.cycles[0].promoted is False
        assert "evaluator oracle mutated" in result.cycles[0].note
        assert ran == []  # the mutated oracle never produced its "pass"
        assert (
            _baseline_sha(Path(config.work_root))
            == _git(repo, "rev-parse", "rsi-baseline").stdout.strip()
        )

    def test_without_the_guard_the_fixture_would_self_score(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Counterfactual, on the bare path where the test command is the ONLY
        oracle evidence: with the integrity check disabled the SAME candidate
        promotes (its own diff made `exit 0` the whole verdict). The fitness
        path has additional fail-first layers, which is exactly why the veto
        must fire BEFORE evidence production — the last line of defense can't
        be the first one."""
        repo = _oracle_repo(tmp_path / "src")
        config = LocalRsiConfig(
            repo_path=str(repo),
            test_command="exit 0",
            work_root=str(tmp_path / "work"),
            max_cycles=1,
        )
        monkeypatch.setattr(LocalRsiLoop, "_evaluator_integrity", lambda self, cdir: ([], None))
        result = LocalRsiLoop(config, apply_patch=_make_apply(_adversarial_candidate)).run()
        assert result.promotions == 1

    def test_authorized_override_promotes_with_recorded_evidence(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Human governance path: with the override the same candidate is
        scored (and, the bare path being trivially green, promoted) — but the
        promotion record carries the mutated paths and the trusted digest, so
        the decision is replayable and reviewable. Never silent."""
        import json

        from maistro_rsi.trace_notes import read_trace_note

        repo = _oracle_repo(tmp_path / "src")
        config = LocalRsiConfig(
            repo_path=str(repo),
            test_command="exit 0",
            work_root=str(tmp_path / "work"),
            max_cycles=1,
            allow_evaluator_mutation=True,
        )
        result = LocalRsiLoop(config, apply_patch=_make_apply(_adversarial_candidate)).run()

        assert result.promotions == 1
        note = read_trace_note(Path(result.baseline_dir), result.cycles[0].sha)
        assert note is not None
        evaluator = note.evaluator
        assert evaluator is not None
        assert evaluator["authorized"] is True
        assert evaluator["mutations"]
        assert evaluator["evaluator_digest"] == oracle_digest(
            Path(result.baseline_dir), f"{result.cycles[0].sha}^"
        )
        # The export manifest — the #302 harvest surface that opens PRs —
        # carries the same provenance, so an authorized oracle override is
        # visible to the reviewer before the promotion merges.
        export_dir = tmp_path / "export"
        exporter = LocalRsiLoop(config, apply_patch=None)
        exporter._baseline = Path(result.baseline_dir)
        exporter._start_ref = f"{result.cycles[0].sha}^"  # range covers the promotion
        exporter.export_promotions(export_dir, clear=True)
        manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest, "expected the promotion to be exported"
        assert manifest[0]["evaluator_digest"] == evaluator["evaluator_digest"]
        assert manifest[0]["evaluator_authorized"] is True

    def test_clean_candidate_still_promotes(self, tmp_path: Path) -> None:
        """The guard must not convert the loop into a no-op: a legitimate
        application improvement keeps promoting — and, since the bare path
        has no scorecard, the promotion record still pins the trusted oracle
        digest on the clean decision (empty mutations, unauthorized), so the
        acceptance is replayable against the oracle version that judged it."""
        import json

        from maistro_rsi.trace_notes import read_trace_note

        repo = _oracle_repo(tmp_path / "src")

        def improve(ws: Path) -> None:
            (ws / "src/app.py").write_text("VALUE = 1\n")

        config = LocalRsiConfig(
            repo_path=str(repo),
            test_command="exit 0",
            work_root=str(tmp_path / "work"),
            max_cycles=1,
        )
        result = LocalRsiLoop(config, apply_patch=_make_apply(improve)).run()
        assert result.promotions == 1

        note = read_trace_note(Path(result.baseline_dir), result.cycles[0].sha)
        assert note is not None
        evaluator = note.evaluator
        assert evaluator is not None
        assert evaluator["verdict"] == "clean"
        assert evaluator["mutations"] == []
        assert evaluator["authorized"] is False
        assert evaluator["evaluator_digest"] == oracle_digest(
            Path(result.baseline_dir), f"{result.cycles[0].sha}^"
        )

        export_dir = tmp_path / "export"
        exporter = LocalRsiLoop(config, apply_patch=None)
        exporter._baseline = Path(result.baseline_dir)
        exporter._start_ref = f"{result.cycles[0].sha}^"
        exporter.export_promotions(export_dir, clear=True)
        manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest, "expected the promotion to be exported"
        assert manifest[0]["evaluator_digest"] == evaluator["evaluator_digest"]
        assert manifest[0]["evaluator_authorized"] is False


# ---------------------------------------------------------------------------
# Merge-path defense in depth: the combined diff is re-checked too
# ---------------------------------------------------------------------------


def test_merge_dir_rescoring_carries_the_integrity_gate(tmp_path: Path, monkeypatch) -> None:
    """`_select_and_merge` re-scores the merged worktree through
    `_fitness_decision` without precomputed evidence — the integrity check
    must be re-derived there, so a combination can never launder what its
    parts individually avoided."""
    from maistro_rsi.local_loop import LocalRsiLoop

    repo = _oracle_repo(tmp_path / "src")
    loop = LocalRsiLoop(
        LocalRsiConfig(
            repo_path=str(repo),
            test_command="exit 0",
            work_root=str(tmp_path / "work"),
            use_fitness=True,
            regression_judge=False,
            promotion_review=False,
        ),
        apply_patch=None,
    )
    loop._setup_baseline()
    # A worktree with an oracle mutation committed (as _run_variant would).
    cdir = tmp_path / "merge-branch"
    _git(
        loop._baseline, "worktree", "add", "-q", "-b", "rsi/merge-probe", str(cdir), "rsi-baseline"
    )
    (cdir / "src/app.py").write_text("VALUE = 1\n")
    scorer = cdir / "packages/maistro-rsi/src/maistro_rsi/candidate_fitness.py"
    scorer.write_text("def compose():\n    return True  # merged weakening\n")
    _commit(cdir, "merged candidate")

    accepted, _composite, reason, _tp, _judge, trace = loop._fitness_decision(
        1, cdir, ["src/app.py", "packages/maistro-rsi/src/maistro_rsi/candidate_fitness.py"]
    )
    assert accepted is False
    assert "evaluator_integrity" in reason
    assert trace["evaluator"]["mutations"]
