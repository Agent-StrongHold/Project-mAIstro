"""Tests for the diff-scoped mutation PR gate runner (#330).

The runner owns the gate's honesty: fail fast on the first un-baselined
survivor, derive each group's per-mutant timeout from its own measured
baseline, refuse red/empty/zero conditions, and leave report-only sources
neither passing nor failing. The cosmic-ray executions are stubbed; the
decision logic — the part that decides whether insecure code merges — is real.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mutation_pr_gate.py"
SOURCE = "packages/maistro-core/src/maistro/security/secret_equal.py"
TESTS = "packages/maistro-core/tests/security/test_secret_equal.py"


@pytest.fixture(scope="module")
def gate():
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("_mutation_pr_gate", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _report(killed: int, viable: list[dict], adjusted_total: int | None = None) -> dict:
    """A viability-report shape. `viable` lists surviving viable mutants;
    `adjusted_total` is the denominator (killed + surviving, exclusions gone)."""
    denominator = killed + len(viable) if adjusted_total is None else adjusted_total
    return {
        "module": SOURCE,
        "future_annotations": True,
        "pending": 0,
        "raw": {"killed": killed, "total": denominator},
        "adjusted": {
            "killed": killed,
            "total": denominator,
            "rate": killed / denominator if denominator else 0.0,
        },
        "viable": viable,
        "non_viable": [],
        "invalid": [],
        "undetermined": [],
    }


def _survivor(line: int, operator: str) -> dict:
    return {"line": line, "col": 4, "operator": operator, "source": "x == y", "mutated": "x != y"}


def _baseline_entry(rate: float, survivors: list[str]) -> dict:
    return {
        "version": 2,
        "entries": {
            SOURCE: {
                "killed": 10,
                "viable": round(10 / rate) if rate else 0,
                "kill_rate": rate,
                "survivor_ids": survivors,
            }
        },
    }


class TestTimeoutDerivation:
    def test_config_timeout_comes_from_the_baseline_not_a_constant(self, gate):
        config = gate.cosmic_config(SOURCE, TESTS, "/pp", timeout=45.0)
        assert "timeout = 45.0" in config
        assert "test_secret_equal.py" in config

    def test_a_tiny_baseline_still_gets_a_floor(self, gate):
        config = gate.cosmic_config(SOURCE, TESTS, "/pp", timeout=0.1)
        assert f"timeout = {gate.MIN_TIMEOUT_SECONDS:.1f}" in config
        # The pytest per-test timeout scales with the same baseline.
        assert "--timeout=10.0" in config

    def test_the_timeout_scales_with_the_measured_baseline(self, gate):
        config = gate.cosmic_config(SOURCE, TESTS, "/pp", timeout=120.0)
        assert "timeout = 120.0" in config


class TestToolchainFingerprint:
    def test_the_fingerprint_is_a_stable_hash_of_the_toolchain(self, gate):
        first = gate.tool_fingerprint()
        second = gate.tool_fingerprint()
        assert first == second
        assert first.startswith("sha256:")

    def test_environment_records_the_runner_and_versions(self, gate):
        env = gate.environment()
        assert {"runner", "python_version", "cosmic_ray_version", "pytest_version"} <= set(env)
        assert env["tool_fingerprint"] == gate.tool_fingerprint()


class TestBaselineReading:
    def test_a_missing_baseline_aborts_the_gate(self, gate, tmp_path):
        with pytest.raises(SystemExit):
            gate.read_baseline(tmp_path / "absent.json")

    def test_a_malformed_baseline_aborts_the_gate(self, gate, tmp_path):
        path = tmp_path / "baseline.json"
        path.write_text("[]", encoding="utf-8")
        with pytest.raises(SystemExit):
            gate.read_baseline(path)

    def test_a_valid_baseline_loads(self, gate, tmp_path):
        path = tmp_path / "baseline.json"
        path.write_text(json.dumps(_baseline_entry(0.9, [])), encoding="utf-8")
        assert SOURCE in gate.read_baseline(path)["entries"]


class TestCombineReports:
    def test_group_reports_sum_into_one_source_report(self, gate):
        combined = gate.combine_reports(
            [_report(3, [], adjusted_total=4), _report(2, [_survivor(9, "core/Comparison")])]
        )
        assert combined["raw"]["killed"] == 5
        assert combined["raw"]["total"] == 7
        assert combined["adjusted"]["total"] == 7
        assert combined["adjusted"]["rate"] == pytest.approx(5 / 7)

    def test_survivor_identities_are_stable_across_sessions(self, gate):
        identities = gate.survivor_identities(_report(0, [_survivor(9, "core/Comparison")]))
        assert identities == ["L9:4 core/Comparison | x == y => x != y"]
        again = gate.survivor_identities(_report(0, [_survivor(9, "core/Comparison")]))
        assert identities == again


class TestRunGroupScopesToItsOwnLines:
    """Each group's session must be restricted to its own changed lines, not
    the whole PR diff — otherwise mutants outside a group's selection are
    scored against tests that cannot see them and survive artificially."""

    def _fake_run(self, gate, calls):
        def fake_run(argv, **kwargs):
            argv = [str(part) for part in argv]
            calls.append(argv)
            if any(part.endswith("mutation_viability.py") for part in argv):
                report = Path(argv[argv.index("--json") + 1])
                report.write_text(json.dumps(_report(1, [])), encoding="utf-8")

            class _Done:
                returncode = 0

            return _Done()

        return fake_run

    def test_the_diff_scope_call_carries_the_groups_lines(self, gate, tmp_path, monkeypatch):
        source = tmp_path / "mod.py"
        source.write_text("def f(x):\n    return x\n", encoding="utf-8")
        monkeypatch.setattr(gate, "measure_baseline", lambda *a, **k: 1.0)
        calls: list[list[str]] = []
        monkeypatch.setattr(gate.subprocess, "run", self._fake_run(gate, calls))

        gate.run_group(
            str(source),
            {"lines": [4, 7], "tests": [TESTS]},
            0,
            artifacts=tmp_path,
            diff_path=tmp_path / "mod.diff",
            pythonpath="/pp",
            timeout_factor=4.0,
        )

        scope_calls = [c for c in calls if any(p.endswith("mutation_diff_scope.py") for p in c)]
        assert len(scope_calls) == 1
        restrict = scope_calls[0][scope_calls[0].index("--restrict-lines") + 1]
        assert restrict == "4,7"

    def test_measurement_mode_without_a_diff_stays_whole_file(self, gate, tmp_path, monkeypatch):
        source = tmp_path / "mod.py"
        source.write_text("def f(x):\n    return x\n", encoding="utf-8")
        monkeypatch.setattr(gate, "measure_baseline", lambda *a, **k: 1.0)
        calls: list[list[str]] = []
        monkeypatch.setattr(gate.subprocess, "run", self._fake_run(gate, calls))

        gate.run_group(
            str(source),
            {"lines": [], "tests": [TESTS]},
            0,
            artifacts=tmp_path,
            diff_path=None,
            pythonpath="/pp",
            timeout_factor=4.0,
        )

        assert not any(p.endswith("mutation_diff_scope.py") for c in calls for p in c)


class TestTheGateDecisions:
    def _run(
        self,
        gate,
        tmp_path,
        baseline,
        reports,
        *,
        monkeypatch,
    ):
        monkeypatch.setattr(
            gate,
            "run_group",
            lambda source, group, index, **kwargs: (reports[index], 1.0),
        )

        class _FakeSelection:
            def __init__(self) -> None:
                self.groups = [
                    {"lines": [10], "tests": ["tests/test_secret_equal.py::test_x"]},
                ]
                self.no_coverage: list[int] = []

        monkeypatch.setattr(gate, "select", lambda *a, **k: _FakeSelection())
        return gate.gate_source(
            SOURCE,
            TESTS,
            artifacts=tmp_path,
            baseline=baseline,
            diff_path=None,
            changed_lines=[10],
            timeout_factor=4.0,
            commit="c0ffee",
            env=gate.environment(),
        )

    def test_a_baselined_survivor_passes(self, gate, tmp_path, monkeypatch):
        identity = "L9:4 core/Comparison | x == y => x != y"
        baseline = _baseline_entry(0.9, [identity])
        report = _report(9, [_survivor(9, "core/Comparison")])  # 9/10 = 90%
        checkpoint, decision = self._run(
            gate, tmp_path, baseline, [report], monkeypatch=monkeypatch
        )
        assert decision == "pass"
        assert checkpoint["verified_commit"] == "c0ffee"

    def test_an_un_baselined_survivor_fails_fast(self, gate, tmp_path, monkeypatch):
        # The recorded baseline knows nothing of this survivor; the gate must
        # stop and fail rather than score the rest of the sweep.
        baseline = _baseline_entry(0.9, [])
        report = _report(3, [_survivor(9, "core/Comparison")])
        with pytest.raises(SystemExit):
            self._run(gate, tmp_path, baseline, [report], monkeypatch=monkeypatch)

    def test_a_rate_drop_below_the_reviewed_floor_fails(self, gate, tmp_path, monkeypatch):
        identity = "L9:4 core/Comparison | x == y => x != y"
        # Every survivor is baselined, but the kill rate collapsed below the
        # reviewed floor — the rate check must catch what the survivor check
        # cannot.
        baseline = _baseline_entry(0.95, [identity])
        report = _report(3, [_survivor(9, "core/Comparison")], adjusted_total=100)
        with pytest.raises(SystemExit):
            self._run(gate, tmp_path, baseline, [report], monkeypatch=monkeypatch)

    def test_zero_viable_mutants_is_a_failure_never_a_pass(self, gate, tmp_path, monkeypatch):
        baseline = _baseline_entry(0.9, [])
        report = _report(0, [], adjusted_total=0)
        with pytest.raises(SystemExit):
            self._run(gate, tmp_path, baseline, [report], monkeypatch=monkeypatch)

    def test_an_unmeasured_source_is_report_only(self, gate, tmp_path, monkeypatch):
        # Monotonic expansion: a source with no reviewed entry can neither pass
        # nor fail a PR; its survivors are published for the baseline review.
        baseline = {"version": 2, "entries": {}}
        report = _report(3, [_survivor(9, "core/Comparison")])
        checkpoint, decision = self._run(
            gate, tmp_path, baseline, [report], monkeypatch=monkeypatch
        )
        assert decision == "report-only"
        assert checkpoint["survivor_ids"]


class TestMeasurementMode:
    """`--scope all` (the nightly) gives one whole-file group; the refusal
    paths are the gate's honesty for the selection it was handed."""

    def test_measurement_mode_selects_the_whole_file(self, gate, tmp_path, monkeypatch):
        seen: dict = {}

        def fake_run_group(source, group, index, **kwargs):
            seen["group"] = group
            seen["diff_path"] = kwargs.get("diff_path")
            return _report(5, []), 1.0

        monkeypatch.setattr(gate, "run_group", fake_run_group)
        checkpoint, decision = gate.gate_source(
            SOURCE,
            TESTS,
            artifacts=tmp_path,
            baseline=_baseline_entry(0.9, []),
            diff_path=tmp_path / "unused.diff",
            changed_lines=None,
            timeout_factor=4.0,
            commit="c0ffee",
            env=gate.environment(),
        )
        assert decision == "pass"
        assert seen["group"] == {"lines": [], "tests": [TESTS]}
        assert seen["diff_path"] is None, "whole-file measurement has no diff to restrict to"
        assert checkpoint["verified_commit"] == "c0ffee"

    def test_a_changed_line_with_no_selected_test_refuses(self, gate, tmp_path, monkeypatch):
        class _Selection:
            groups: ClassVar[list] = [{"lines": [9], "tests": ["t"]}]
            no_coverage: ClassVar[list] = [9]

        monkeypatch.setattr(gate, "select", lambda *a, **k: _Selection())
        with pytest.raises(SystemExit):
            gate.gate_source(
                SOURCE,
                TESTS,
                artifacts=tmp_path,
                baseline=_baseline_entry(0.9, []),
                diff_path=None,
                changed_lines=[9],
                timeout_factor=4.0,
                commit="c",
                env=gate.environment(),
            )

    def test_zero_selected_tests_refuses(self, gate, tmp_path, monkeypatch):
        class _Selection:
            groups: ClassVar[list] = []
            no_coverage: ClassVar[list] = []

        monkeypatch.setattr(gate, "select", lambda *a, **k: _Selection())
        with pytest.raises(SystemExit):
            gate.gate_source(
                SOURCE,
                TESTS,
                artifacts=tmp_path,
                baseline=_baseline_entry(0.9, []),
                diff_path=None,
                changed_lines=[9],
                timeout_factor=4.0,
                commit="c",
                env=gate.environment(),
            )


class TestTheBaselineRunItself:
    """`measure_baseline` times the real selected-test run and refuses red —
    a mutant measured against a red baseline proves nothing (#330)."""

    @staticmethod
    def _completed(returncode: int, stdout: str = ""):
        import types

        done = types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")
        return done

    def test_a_green_baseline_returns_its_wall_seconds(self, gate, monkeypatch):
        seen: dict = {}

        def fake_run(argv, **kwargs):
            seen["argv"] = [str(part) for part in argv]
            seen["env"] = kwargs["env"]
            return self._completed(0)

        monkeypatch.setattr(gate.subprocess, "run", fake_run)
        seconds = gate.measure_baseline("tests/test_mod.py::test_add", "/pp", ["-x"])
        assert seconds >= 0.0
        assert "-m" in seen["argv"] and "pytest" in seen["argv"]
        assert seen["env"]["PYTHONPATH"] == "/pp"

    def test_a_red_baseline_aborts(self, gate, monkeypatch, capsys):
        monkeypatch.setattr(
            gate.subprocess,
            "run",
            lambda argv, **kwargs: self._completed(1, stdout="1 failed"),
        )
        with pytest.raises(SystemExit):
            gate.measure_baseline("tests/test_mod.py", "/pp", [])
        err = capsys.readouterr().err
        assert "baseline is red" in err


class TestUnusableBaselines:
    def test_unparseable_json_aborts(self, gate, tmp_path):
        path = tmp_path / "baseline.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(SystemExit):
            gate.read_baseline(path)

    def test_entries_that_are_not_an_object_aborts(self, gate, tmp_path):
        path = tmp_path / "baseline.json"
        path.write_text('{"entries": ["not", "an", "object"]}', encoding="utf-8")
        with pytest.raises(SystemExit):
            gate.read_baseline(path)


class TestTheCli:
    """`main` owns the plumbing the workflow actually invokes: target rows,
    selection input, telemetry artifacts, and the refusal to run against
    nothing."""

    def _targets(self, tmp_path: Path) -> Path:
        targets = tmp_path / "targets.tsv"
        targets.write_text(f"{SOURCE}\t{TESTS}\n", encoding="utf-8")
        return targets

    def _baseline(self, tmp_path: Path) -> Path:
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps(_baseline_entry(0.9, [])), encoding="utf-8")
        return baseline

    def test_a_run_records_telemetry_and_checkpoints(self, gate, tmp_path, monkeypatch):
        selection_dir = tmp_path / "selection"
        selection_dir.mkdir()
        identifier = gate.mutation_packet.safe_id(SOURCE)
        (selection_dir / f"{identifier}.selection.json").write_text(
            json.dumps({"changed_lines": [9]}), encoding="utf-8"
        )

        def fake_gate(source, tests, **kwargs):
            return {"source": source, "killed_mutants": 9, "viable_mutants": 10}, "pass"

        monkeypatch.setattr(gate, "gate_source", fake_gate)
        artifacts = tmp_path / "artifacts"
        rc = gate.main(
            [
                str(self._targets(tmp_path)),
                "--artifacts",
                str(artifacts),
                "--baseline",
                str(self._baseline(tmp_path)),
                "--selection-dir",
                str(selection_dir),
                "--scope",
                "changed",
                "--commit",
                "c0ffee",
            ]
        )
        assert rc == 0
        telemetry = (artifacts / "mutation-telemetry.jsonl").read_text(encoding="utf-8")
        assert json.loads(telemetry.splitlines()[-1])["decision"] == "pass"
        assert (artifacts / f"{identifier}.checkpoint.json").is_file()

    def test_measurement_scope_needs_no_selection_input(self, gate, tmp_path, monkeypatch):
        captured: dict = {}

        def fake_gate(source, tests, **kwargs):
            captured["changed_lines"] = kwargs["changed_lines"]
            captured["diff_path"] = kwargs["diff_path"]
            return {"source": source}, "pass"

        monkeypatch.setattr(gate, "gate_source", fake_gate)
        rc = gate.main(
            [
                str(self._targets(tmp_path)),
                "--artifacts",
                str(tmp_path / "artifacts"),
                "--baseline",
                str(self._baseline(tmp_path)),
                "--scope",
                "all",
                "--commit",
                "c0ffee",
            ]
        )
        assert rc == 0
        assert captured["changed_lines"] is None
        assert captured["diff_path"] is None

    def test_a_run_against_nothing_is_not_a_pass(self, gate, tmp_path):
        targets = tmp_path / "targets.tsv"
        targets.write_text("\n", encoding="utf-8")
        rc = gate.main(
            [
                str(targets),
                "--artifacts",
                str(tmp_path / "artifacts"),
                "--baseline",
                str(self._baseline(tmp_path)),
                "--scope",
                "all",
            ]
        )
        assert rc == 1

    def test_changed_scope_without_selection_or_diff_is_an_error(self, gate, tmp_path):
        rc = gate.main(
            [
                str(self._targets(tmp_path)),
                "--artifacts",
                str(tmp_path / "artifacts"),
                "--baseline",
                str(self._baseline(tmp_path)),
                "--diff-dir",
                str(tmp_path / "absent"),
                "--scope",
                "changed",
            ]
        )
        assert rc == 1
