"""Gate evidence and truthful reporting (#304 / #820).

A required analyzer that never executed must reach the promotion record and
the generated PR text as a blocking ``not_run`` — never as an omission that a
success-shaped sentence renders as a pass. These tests pin:

- ``_lint_gates`` fail-closed behavior: a missing/timed-out required tool is a
  blocking ``not_run`` gate naming the cause; executed gates carry provenance
  (command, tool version, candidate SHA, exit status, output digest) and one
  of exactly two states; unreadable output is a FAILED gate, not a clean one.
- the runner-image parity: the shipped RSI runner installs every required
  analyzer the scorecard names.
- the evidence chain: scorecard → git-notes ``gate_evidence`` → export
  manifest row → ``harvest.pr_body``, where only recorded results are named.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from maistro_evolve.scorecard import GateResult, GateState, Scorecard
from maistro_rsi import candidate_fitness
from maistro_rsi.candidate_fitness import (
    REQUIRED_LINT_TOOL_SPEC,
    FitnessInputs,
    _lint_gates,
    compose_scorecard,
)
from maistro_rsi.harvest import PromotedPatch, manifest_records, pr_body
from maistro_rsi.local_loop import LocalRsiConfig, LocalRsiLoop
from maistro_rsi.trace_notes import TraceNote, read_trace_note, write_trace_note

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _git(path: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(path),
        check=True,
        capture_output=True,
    )


def _candidate_repo(path: Path) -> Path:
    """A minimal git repo with one committed (clean) python file: the shape
    ``_lint_gates`` scores in production — a candidate worktree with a HEAD
    the provenance can pin."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=str(path), check=True, capture_output=True)
    (path / "calc.py").write_text("def double(n):\n    return n * 2\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "candidate")
    return path


def _stub_run_lint_tool(monkeypatch: pytest.MonkeyPatch, results: dict[str, Any]) -> None:
    """Replace the tool runner per tool name: value is a CompletedProcess-like
    result or ``(None, cause)`` for a non-execution. Tools without a stub
    entry run for real."""
    real = candidate_fitness._run_lint_tool

    def fake(argv: list[str], cwd: Path) -> tuple[Any, str | None]:
        for tool, value in results.items():
            if f"-m {tool}" in " ".join(argv) or any(a == tool for a in argv):
                if isinstance(value, tuple):
                    return value
                return value, None
        return real(argv, cwd)

    monkeypatch.setattr(candidate_fitness, "_run_lint_tool", fake)


def _proc(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, "")


# ---------------------------------------------------------------------------
# Required-tool fail-closed (#304)
# ---------------------------------------------------------------------------


class TestRequiredToolFailClosed:
    def test_missing_required_tool_is_a_blocking_not_run_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bandit absent from the runner ⇒ a not_run gate that vetoes, names
        the tool and the cause — not a silent narrowing of the scorecard."""
        repo = _candidate_repo(tmp_path / "r")
        _stub_run_lint_tool(monkeypatch, {"bandit": (None, "missing")})
        gates = _lint_gates(repo, ["calc.py"])
        by_name = {g.name: g for g in gates}
        assert set(by_name) == {"ruff_clean", "mypy_clean", "no_bandit_high"}
        bandit = by_name["no_bandit_high"]
        assert bandit.passed is False
        assert bandit.resolved_state() is GateState.NOT_RUN
        assert "bandit" in bandit.reason and "missing" in bandit.reason
        assert bandit.detail["cause"] == "missing"
        # The other tools still report their real executed results.
        assert by_name["ruff_clean"].resolved_state() is GateState.PASSED

    def test_missing_required_tool_blocks_acceptance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _candidate_repo(tmp_path / "r")
        _stub_run_lint_tool(monkeypatch, {"bandit": (None, "missing")})
        gates = _lint_gates(repo, ["calc.py"])
        sc = compose_scorecard(FitnessInputs(tests_passed=True, lint_gates=gates))
        assert sc.accepted is False
        gate = next(g for g in sc.gates if g.name == "no_bandit_high")
        assert gate.resolved_state() is GateState.NOT_RUN

    def test_wedged_required_tool_is_not_run_with_its_cause(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _candidate_repo(tmp_path / "r")
        _stub_run_lint_tool(monkeypatch, {"mypy": (None, "timeout")})
        gates = _lint_gates(repo, ["calc.py"])
        mypy = next(g for g in gates if g.name == "mypy_clean")
        assert mypy.passed is False
        assert mypy.resolved_state() is GateState.NOT_RUN
        assert mypy.detail["cause"] == "timeout"

    def test_unreadable_tool_output_is_failed_not_clean(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A tool that ran on a findings exit but produced unparseable output
        cannot count as a clean result: the gate records FAILED with its
        provenance."""
        repo = _candidate_repo(tmp_path / "r")
        _stub_run_lint_tool(
            monkeypatch, {"ruff": _proc(stdout="<html>not json</html>", returncode=0)}
        )
        gates = _lint_gates(repo, ["calc.py"])
        ruff = next(g for g in gates if g.name == "ruff_clean")
        assert ruff.passed is False
        assert ruff.resolved_state() is GateState.FAILED
        assert "unreadable" in ruff.reason

    def test_usage_error_exit_is_a_blocking_not_run_not_a_clean_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A tool that starts but exits with a usage/configuration/internal
        error (2) never evaluated the files: its empty stdout must not parse
        as ruff ``[]``, mypy zero errors, or bandit ``{}`` — i.e. a PASSED
        gate. The exit is rejected before parsing and blocks promotion."""
        repo = _candidate_repo(tmp_path / "r")
        for dist, name in (
            ("ruff", "ruff_clean"),
            ("mypy", "mypy_clean"),
            ("bandit", "no_bandit_high"),
        ):
            _stub_run_lint_tool(monkeypatch, {dist: _proc(stdout="", returncode=2)})
            gates = _lint_gates(repo, ["calc.py"])
            gate = next(g for g in gates if g.name == name)
            assert gate.passed is False
            assert gate.resolved_state() is GateState.NOT_RUN
            assert "exit 2" in gate.reason
            assert gate.detail["cause"] == "execution error (exit 2)"

    def test_no_source_files_still_runs_no_gates(self, tmp_path: Path) -> None:
        assert _lint_gates(tmp_path, []) == []

    def test_not_run_gate_is_blocking_and_named_in_explain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _candidate_repo(tmp_path / "r")
        _stub_run_lint_tool(monkeypatch, {"bandit": (None, "missing")})
        sc = compose_scorecard(
            FitnessInputs(tests_passed=True, lint_gates=_lint_gates(repo, ["calc.py"]))
        )
        explain = sc.explain()
        assert "NOT RUN (blocking)" in explain
        assert "no_bandit_high" in explain
        assert sc.accepted is False

    def test_unavailable_gate_is_non_blocking_and_named_in_explain(self) -> None:
        """An optional signal that never executed is reportable but never a
        veto: acceptance reads the resolved state, not the legacy boolean."""
        sc = Scorecard(
            gates=[
                GateResult("optional_probe", False, "measured nothing", state=GateState.UNAVAILABLE)
            ]
        )
        assert "[UNAVAILABLE] optional_probe" in sc.explain()
        assert sc.gates_passed is True
        assert sc.accepted is True


# ---------------------------------------------------------------------------
# Executed-gate provenance (#304 AC-1)
# ---------------------------------------------------------------------------


class TestExecutedGateProvenance:
    def test_every_required_gate_records_what_actually_ran(self, tmp_path: Path) -> None:
        """The REAL tools (installed in this environment, as in the runner
        image) run against a real candidate commit: each gate's result is tied
        to command, tool version, candidate SHA, exit status, output digest."""
        repo = _candidate_repo(tmp_path / "r")
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True
        ).stdout.strip()
        gates = _lint_gates(repo, ["calc.py"])
        assert {g.name for g in gates} == {spec[0] for spec in REQUIRED_LINT_TOOL_SPEC}
        for gate, (_, dist, _argv) in zip(gates, REQUIRED_LINT_TOOL_SPEC, strict=True):
            assert gate.resolved_state() in (GateState.PASSED, GateState.FAILED)
            detail = gate.detail
            argv = detail["command"]
            assert argv, "the executed argv must be recorded"
            assert f"-m {dist}" in " ".join(argv), "the argv names its own tool"
            assert all(f in argv for f in ("calc.py",)), "the argv names the scored files"
            assert isinstance(detail["tool_version"], str) and detail["tool_version"]
            assert detail["candidate_sha"] == sha
            assert detail["exit_status"] == 0
            assert str(detail["output_digest"]).startswith("sha256:")

    def test_version_and_sha_absent_outside_a_repo_are_none_not_invented(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A compose-only context (no git worktree) records honest Nones."""
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "calc.py").write_text("x = 1\n", encoding="utf-8")
        _stub_run_lint_tool(
            monkeypatch,
            {
                "ruff": _proc(stdout="[]"),
                "mypy": _proc(),
                "bandit": _proc(stdout='{"results": []}'),
            },
        )
        gates = _lint_gates(plain, ["calc.py"])
        assert len(gates) == 3
        for gate in gates:
            assert gate.detail["candidate_sha"] is None
            assert str(gate.detail["output_digest"]).startswith("sha256:")

    def test_output_digest_authenticates_stderr_not_stdout_alone(self) -> None:
        """The digest covers both streams: identical stdout with different
        stderr must not collide — a run dying on stderr is not evidence-equivalent
        to a silent clean one. The length-framed combination is pinned exactly so
        the recorded digest stays reproducible from the captured streams."""
        import hashlib

        clean = subprocess.CompletedProcess([], 0, stdout="[]", stderr="")
        noisy = subprocess.CompletedProcess(
            [], 0, stdout="[]", stderr="warning: config ignored\n"
        )
        assert candidate_fitness._output_digest(clean) != candidate_fitness._output_digest(noisy)
        out, err = b"[]", b"warning: config ignored\n"
        framed = b"stdout:%d:" % len(out) + out + b"stderr:%d:" % len(err) + err
        assert candidate_fitness._output_digest(noisy) == (
            "sha256:" + hashlib.sha256(framed).hexdigest()
        )


# ---------------------------------------------------------------------------
# GateState semantics (maistro-evolve scorecard)
# ---------------------------------------------------------------------------


class TestGateState:
    def test_legacy_construction_resolves_from_the_boolean(self) -> None:
        assert GateResult("g", True, "ok").resolved_state() is GateState.PASSED
        assert GateResult("g", False, "bad").resolved_state() is GateState.FAILED

    def test_explicit_state_survives(self) -> None:
        gate = GateResult("g", False, "did not run", state=GateState.NOT_RUN)
        assert gate.resolved_state() is GateState.NOT_RUN

    def test_states_are_distinct_strings(self) -> None:
        values = {s.value for s in GateState}
        assert values == {"passed", "failed", "not_run", "unavailable"}


# ---------------------------------------------------------------------------
# Runner-image parity (#304 definition of done)
# ---------------------------------------------------------------------------


class TestRunnerImageParity:
    def test_runner_image_declares_every_required_analyzer(self) -> None:
        """The scorecard's required analyzer set must be installed in the
        shipped runner image, or every dispatched run dies in a not_run veto
        for an environment reason. Two install sources count:
        - the image's explicit ``uv pip install`` line (bandit, coverage, ...),
        - the locked dev group ``uv sync --frozen`` installs (ruff, mypy are
          root dev-group members, so they ride the locked sync).
        A required tool in NEITHER source is the #304 defect: a gate the image
        can never execute."""
        import tomllib

        dockerfile = (_REPO_ROOT / "Dockerfile.rsi-runner").read_text(encoding="utf-8")
        install_lines = [
            ln.strip()
            for ln in dockerfile.splitlines()
            if ln.strip().startswith("RUN uv pip install")
        ]
        assert install_lines, "runner image lost its analyzer install line"
        explicit = " ".join(install_lines)
        # The image must keep syncing the dev group (no --no-dev): that is how
        # the locked ruff/mypy reach the runner venv.
        sync_lines = [ln for ln in dockerfile.splitlines() if "uv sync" in ln]
        assert any("--frozen" in ln and "--no-dev" not in ln for ln in sync_lines), (
            "runner image must install the locked dev group (ruff/mypy live there)"
        )
        pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        dev_group = " ".join(pyproject["dependency-groups"]["dev"])
        for spec in REQUIRED_LINT_TOOL_SPEC:
            gate, dist = spec[0], spec[1]
            installed_via = (
                "image install line"
                if dist in explicit
                else ("locked dev group" if dist in dev_group else None)
            )
            assert installed_via is not None, (
                f"required gate {gate!r} needs analyzer {dist!r}: installed by neither "
                "Dockerfile.rsi-runner nor the root dev group"
            )
        # coverage backs the tests/coverage gates on the same runner.
        assert "coverage" in explicit


# ---------------------------------------------------------------------------
# The evidence chain: scorecard → note → manifest → PR body (#820)
# ---------------------------------------------------------------------------


def _evidence(
    name: str,
    *,
    state: GateState,
    passed: bool,
    reason: str = "",
    provenance: dict[str, object] | None = None,
) -> dict[str, object]:
    ev: dict[str, object] = {"state": state.value, "passed": passed, "reason": reason}
    if provenance is not None:
        ev["provenance"] = provenance
    return ev


def _trace_note(gate_evidence: dict[str, dict[str, object]] | None) -> TraceNote:
    gates = {name: bool(ev["passed"]) for name, ev in (gate_evidence or {}).items()}
    return TraceNote(
        cycle=1,
        target="t",
        accepted=True,
        kind="new_test",
        model="m",
        files_touched=1,
        gates=gates,
        gate_evidence=gate_evidence,
        note="n",
    )


class TestPromotionEvidenceChain:
    def test_scorecard_trace_records_state_and_provenance(self) -> None:
        sc = Scorecard(
            gates=[
                GateResult("tests_pass", True, "ok"),
                GateResult(
                    "no_bandit_high",
                    False,
                    "bandit did not run (missing)",
                    detail={"cause": "missing", "command": ["bandit"]},
                    state=GateState.NOT_RUN,
                ),
            ]
        )
        trace = LocalRsiLoop._scorecard_trace(sc)
        ev = trace["gate_evidence"]
        assert ev["tests_pass"]["state"] == "passed"
        assert ev["no_bandit_high"]["state"] == "not_run"
        assert ev["no_bandit_high"]["provenance"] == {"cause": "missing", "command": ["bandit"]}
        # The boolean verdict map is unchanged for existing readers.
        assert trace["gates"] == {"tests_pass": True, "no_bandit_high": False}

    def test_promotion_note_and_manifest_carry_gate_evidence(self, tmp_path: Path) -> None:
        """write_trace_note → read_trace_note → export_promotions: the manifest
        row the harvester consumes records exactly which gates ran (and which
        never did) for the promoted commit."""
        evidence = {
            "tests_pass": _evidence("tests_pass", state=GateState.PASSED, passed=True),
            "no_bandit_high": _evidence(
                "no_bandit_high",
                state=GateState.NOT_RUN,
                passed=False,
                reason="bandit did not run (missing)",
                provenance={"cause": "missing", "tool_version": None},
            ),
        }

        # 1) The note round-trips its evidence bundle.
        repo = _candidate_repo(tmp_path / "r")
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True
        ).stdout.strip()
        assert write_trace_note(repo, sha, _trace_note(evidence)) is True
        note = read_trace_note(repo, sha)
        assert note is not None and note.gate_evidence is not None
        assert note.gate_evidence["no_bandit_high"]["state"] == "not_run"

        # 2) The export manifest row projects it (notes are not cloned, so the
        # production path annotates the loop's own baseline clone — mirror it).
        loop = LocalRsiLoop(
            LocalRsiConfig(
                repo_path=str(repo), test_command="exit 0", work_root=str(tmp_path / "w")
            )
        )
        loop._setup_baseline()
        _git(loop._baseline, "commit", "-q", "--allow-empty", "-m", "RSI cycle 1: fix")
        promoted = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(loop._baseline),
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert write_trace_note(loop._baseline, promoted, _trace_note(evidence)) is True
        dest = tmp_path / "export"
        assert loop.export_promotions(dest) == 1
        manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
        assert manifest[0]["gates"] == {"tests_pass": True, "no_bandit_high": False}
        row_evidence = manifest[0]["gate_evidence"]
        assert row_evidence["no_bandit_high"]["state"] == "not_run"
        assert row_evidence["tests_pass"]["state"] == "passed"

    def test_manifest_roundtrip_projects_gate_evidence(self, tmp_path: Path) -> None:
        evidence = {
            "ruff_clean": _evidence(
                "ruff_clean",
                state=GateState.PASSED,
                passed=True,
                provenance={"tool_version": "0.15.12", "exit_status": 0},
            )
        }
        (tmp_path / "manifest.json").write_text(
            json.dumps(
                [
                    {
                        "patch_file": "0001.patch",
                        "file": "a.py",
                        "subject": "s1",
                        "gates": {"ruff_clean": True},
                        "gate_evidence": evidence,
                    }
                ]
            ),
            encoding="utf-8",
        )
        patches = manifest_records(
            json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        )
        assert patches[0].gates == {"ruff_clean": True}
        assert patches[0].gate_evidence is not None
        assert patches[0].gate_evidence["ruff_clean"]["state"] == "passed"


class TestPrBodyTruthfulness:
    def test_body_names_only_recorded_results(self) -> None:
        evidence = {
            "tests_pass": _evidence("tests_pass", state=GateState.PASSED, passed=True),
            "ruff_clean": _evidence(
                "ruff_clean",
                state=GateState.PASSED,
                passed=True,
                provenance={
                    "tool_version": "0.15.12",
                    "exit_status": 0,
                    "output_digest": "sha256:" + "a" * 64,
                },
            ),
            "no_bandit_high": _evidence(
                "no_bandit_high",
                state=GateState.NOT_RUN,
                passed=False,
                reason="bandit did not run (missing) — required gate not_run",
            ),
        }
        patches = [
            PromotedPatch(
                patch_file="0001.patch",
                file="a.py",
                subject="RSI cycle 1: fix",
                gates={name: bool(ev["passed"]) for name, ev in evidence.items()},
                gate_evidence=evidence,
            )
        ]
        body = pr_body("a.py", patches)
        # Recorded results are named, with state and provenance.
        assert "- tests_pass: passed" in body
        assert "- ruff_clean: passed (tool 0.15.12, exit 0" in body
        assert "- no_bandit_high: NOT RUN — blocking" in body
        assert "bandit did not run (missing)" in body
        # No wholesale success sentence, and no gate claimed that never ran.
        assert "full fitness scorecard" not in body
        assert "mypy_clean" not in body
        assert "coverage" not in body.lower().replace("coverage-not-dropped", "")

    def test_body_without_evidence_claims_nothing(self) -> None:
        patches = [PromotedPatch(patch_file="0001.patch", file="a.py", subject="legacy")]
        body = pr_body("a.py", patches)
        assert "No recorded gate evidence" in body
        assert "passed" not in body
        assert "full fitness scorecard" not in body

    def test_worst_recorded_state_wins_across_the_group(self) -> None:
        """A per-file PR ships every promotion in the group, so a gate that is
        not_run on ANY promotion is reported as not_run for the group."""
        evidence_pass = {
            "ruff_clean": _evidence(
                "ruff_clean",
                state=GateState.PASSED,
                passed=True,
                provenance={"tool_version": "1", "exit_status": 0},
            )
        }
        evidence_not_run = {
            "ruff_clean": _evidence(
                "ruff_clean", state=GateState.NOT_RUN, passed=False, reason="missing"
            )
        }
        patches = [
            PromotedPatch(
                patch_file="0001.patch",
                file="a.py",
                subject="s1",
                gates={"ruff_clean": True},
                gate_evidence=evidence_pass,
            ),
            PromotedPatch(
                patch_file="0002.patch",
                file="a.py",
                subject="s2",
                gates={"ruff_clean": False},
                gate_evidence=evidence_not_run,
            ),
        ]
        body = pr_body("a.py", patches)
        assert "- ruff_clean: NOT RUN — blocking" in body

    def test_unavailable_outlives_passed_across_the_group(self) -> None:
        """A gate recorded passed on one promotion but unavailable (never
        executed) on another must not render as passed for the group — the
        group PR ships both patches, so the unexecuted state survives."""
        evidence_pass = {
            "tests_pin_behavior": _evidence(
                "tests_pin_behavior",
                state=GateState.PASSED,
                passed=True,
                provenance={"tool_version": "1", "exit_status": 0},
            )
        }
        evidence_unavailable = {
            "tests_pin_behavior": _evidence(
                "tests_pin_behavior",
                state=GateState.UNAVAILABLE,
                passed=False,
                reason="probe measured nothing",
            )
        }
        patches = [
            PromotedPatch(
                patch_file="0001.patch",
                file="a.py",
                subject="s1",
                gates={"tests_pin_behavior": True},
                gate_evidence=evidence_pass,
            ),
            PromotedPatch(
                patch_file="0002.patch",
                file="a.py",
                subject="s2",
                gates={"tests_pin_behavior": False},
                gate_evidence=evidence_unavailable,
            ),
        ]
        body = pr_body("a.py", patches)
        assert "- tests_pin_behavior: unavailable — not executed" in body
        assert "- tests_pin_behavior: passed" not in body

    def test_mixed_group_marks_unevidenced_promotions_unverified(self) -> None:
        """A group mixing an evidenced promotion with a legacy row (neither
        ``gates`` nor ``gate_evidence``) names the legacy patch unverified —
        the recorded rows do not vouch for outcomes that are unknown."""
        evidence = {
            "ruff_clean": _evidence(
                "ruff_clean",
                state=GateState.PASSED,
                passed=True,
                provenance={"tool_version": "1", "exit_status": 0},
            )
        }
        patches = [
            PromotedPatch(
                patch_file="0001.patch",
                file="a.py",
                subject="evidenced s1",
                gates={"ruff_clean": True},
                gate_evidence=evidence,
            ),
            PromotedPatch(patch_file="0002.patch", file="a.py", subject="legacy s2"),
        ]
        body = pr_body("a.py", patches)
        assert "- ruff_clean: passed" in body
        assert "- legacy s2: no recorded gate evidence — unverified" in body
        assert "No recorded gate evidence on any promotion" not in body

    def test_failed_result_is_rendered_failed(self) -> None:
        evidence = {
            "mypy_clean": _evidence(
                "mypy_clean",
                state=GateState.FAILED,
                passed=False,
                reason="2 type error(s)",
                provenance={"tool_version": "2.3.1", "exit_status": 0},
            )
        }
        patches = [
            PromotedPatch(
                patch_file="0001.patch",
                file="a.py",
                subject="s",
                gates={"mypy_clean": False},
                gate_evidence=evidence,
            )
        ]
        body = pr_body("a.py", patches)
        assert "- mypy_clean: FAILED" in body

    def test_unavailable_optional_gate_is_reported_not_claimed(self) -> None:
        """An optional signal that never executed (state unavailable) is named
        as such — never silently dropped and never rendered as a pass."""
        evidence = {
            "tests_pin_behavior": _evidence(
                "tests_pin_behavior",
                state=GateState.UNAVAILABLE,
                passed=False,
                reason="probe measured nothing",
            )
        }
        patches = [
            PromotedPatch(
                patch_file="0001.patch",
                file="a.py",
                subject="s",
                gates={"tests_pin_behavior": False},
                gate_evidence=evidence,
            )
        ]
        body = pr_body("a.py", patches)
        assert "- tests_pin_behavior: unavailable — not executed" in body
        assert "probe measured nothing" in body

    def test_an_evidence_row_without_a_state_fails_closed_in_rendering(self) -> None:
        """A recorded row that somehow lacks a state renders FAILED, not
        passed: unparseable evidence must never read as success."""
        patches = [
            PromotedPatch(
                patch_file="0001.patch",
                file="a.py",
                subject="s",
                gates={"ruff_clean": False},
                gate_evidence={"ruff_clean": {"passed": True, "reason": ""}},
            )
        ]
        body = pr_body("a.py", patches)
        assert "- ruff_clean: FAILED" in body

    def test_harvest_body_from_a_legacy_manifest_is_unverified(self, tmp_path: Path) -> None:
        """A pre-#304 manifest row (no gate fields) renders as unverified —
        never as the old hard-coded full-pass sentence."""
        (tmp_path / "manifest.json").write_text(
            json.dumps([{"patch_file": "0001.patch", "file": "a.py", "subject": "s1"}]),
            encoding="utf-8",
        )
        patches = manifest_records(
            json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        )
        body = pr_body("a.py", patches)
        assert "No recorded gate evidence" in body
        assert "bandit" not in body and "mypy" not in body
