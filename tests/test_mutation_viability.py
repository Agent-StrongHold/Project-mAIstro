"""The viability classifier's refusals, tested rather than trusted.

This tool subtracts mutants from the mutation gate's denominator. Everything
worth testing here is a case where it must decline to do that, because the only
dangerous failure mode is excluding a mutant a test could actually kill —
that silently raises the score while lowering what the score means.

Each test below corresponds to a specific way the first draft got this wrong.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "mutation_viability.py"


@pytest.fixture(scope="module")
def mv():
    spec = importlib.util.spec_from_file_location("_mutation_viability", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_DEFERRED = (
    "from __future__ import annotations\n\ndef f(x: str | None = None) -> int:\n    return 1\n"
)
_LIVE = "def f(x: str | None = None) -> int:\n    return 1\n"


def _session(
    tmp_path: Path, rows: list[dict], *, specs_only: int = 0, name: str = "session"
) -> Path:
    """Build a minimal cosmic-ray-shaped session database."""
    path = tmp_path / f"{name}.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE mutation_specs (module_path TEXT, operator_name TEXT, "
        "start_pos_row INT, start_pos_col INT, job_id TEXT)"
    )
    conn.execute(
        "CREATE TABLE work_results (worker_outcome TEXT, test_outcome TEXT, diff TEXT, job_id TEXT)"
    )
    for i, r in enumerate(rows):
        conn.execute(
            "INSERT INTO mutation_specs VALUES (?,?,?,?,?)",
            (r.get("module", "m.py"), r.get("op", "core/Op"), r.get("row", 3), 0, f"job{i}"),
        )
        conn.execute(
            "INSERT INTO work_results VALUES (?,?,?,?)",
            (
                r.get("worker", "NORMAL"),
                r.get("outcome", "SURVIVED"),
                r.get("diff", ""),
                f"job{i}",
            ),
        )
    # Specs with no matching result == an interrupted sweep. These must carry
    # the same module as the rows above, or they attach to nothing and the
    # pending count silently reads as zero.
    pending_module = rows[0].get("module", "m.py") if rows else "m.py"
    for j in range(specs_only):
        conn.execute(
            "INSERT INTO mutation_specs VALUES (?,?,?,?,?)",
            (pending_module, "core/Op", 3, 0, f"pending{j}"),
        )
    conn.commit()
    conn.close()
    return path


def _diff(row: int, minus: str, plus: str | None) -> str:
    body = f"@@ -{row},3 +{row},3 @@\n-{minus}\n"
    if plus is not None:
        body += f"+{plus}\n"
    return body


class TestFutureImportGuard:
    """The load-bearing precondition: annotations must be deferred."""

    def test_deferred_module_is_detected(self, mv) -> None:
        assert mv.has_future_annotations(_DEFERRED) is True

    def test_module_without_the_import_is_detected(self, mv) -> None:
        assert mv.has_future_annotations(_LIVE) is False

    def test_annotation_mutant_is_excluded_only_when_annotations_are_deferred(
        self, mv, tmp_path: Path
    ) -> None:
        """The bug this guard exists for.

        Without `from __future__ import annotations`, `str | None` is a live
        expression evaluated at def time — `str + None` raises TypeError on
        import, so any test that imports the module kills it. Stripping
        annotations from both trees makes the two look identical either way, so
        the first draft would have called this provably unkillable and deleted
        it from the denominator.
        """
        row = 3  # the `def f(...)` line in _DEFERRED
        diff = _diff(
            row, "def f(x: str | None = None) -> int:", "def f(x: str + None = None) -> int:"
        )
        session = _session(tmp_path, [{"row": row, "diff": diff}])

        deferred_src = tmp_path / "deferred.py"
        deferred_src.write_text(_DEFERRED)
        report = mv.classify(session, "m.py", deferred_src)
        assert [v.category for v in report.verdicts] == ["non_viable"]

        # Same mutant, same diff, module without the future import: the
        # annotation is evaluated, so it must NOT be excluded.
        live_src = tmp_path / "live.py"
        live_src.write_text(_LIVE)
        live_diff = _diff(
            1, "def f(x: str | None = None) -> int:", "def f(x: str + None = None) -> int:"
        )
        live_report = mv.classify(
            _session(tmp_path, [{"row": 1, "diff": live_diff}], name="live"), "m.py", live_src
        )
        assert live_report.future_annotations is False
        assert [v.category for v in live_report.verdicts] == ["viable"], (
            "an annotation mutant in a module without PEP 563 was excluded; it "
            "raises TypeError on import and any importing test kills it"
        )


class TestDenominatorIsConservative:
    """Only proven-harmless mutants may leave the denominator."""

    def test_invalid_mutants_stay_in_the_denominator(self, mv) -> None:
        """A non-compiling mutant is killable by any test that imports the
        module. That it survived means the scoped tests never import it — a
        coverage gap, not a proof of harmlessness."""
        report = mv.Report(total=10, killed=7)
        report.verdicts = [mv.Verdict("j", 1, 0, "op", "invalid", "x")]

        _killed, denominator, _rate = report.adjusted()

        assert denominator == 10, "an invalid mutant was subtracted from the denominator"

    def test_undetermined_mutants_stay_in_the_denominator(self, mv) -> None:
        report = mv.Report(total=10, killed=7)
        report.verdicts = [mv.Verdict("j", 1, 0, "op", "undetermined", "x")]

        _killed, denominator, _rate = report.adjusted()

        assert denominator == 10

    def test_only_non_viable_is_subtracted(self, mv) -> None:
        report = mv.Report(total=10, killed=7)
        report.verdicts = [
            mv.Verdict("a", 1, 0, "op", "non_viable", "x"),
            mv.Verdict("b", 2, 0, "op", "invalid", "x"),
            mv.Verdict("c", 3, 0, "op", "undetermined", "x"),
        ]

        _killed, denominator, _rate = report.adjusted()

        assert denominator == 9


class TestSkippedBucket:
    """A mutant the pre-exec filter removed is a proven exclusion (#419).

    `mutation_filter_annotations.py` marks annotation-position mutants SKIPPED
    before `exec`, having proved by AST span what this module otherwise proves
    by AST comparison. Such a mutant never ran, so it has no diff, and it used
    to land in `undetermined` -- penalising a file precisely for having had its
    unkillable mutants correctly filtered.
    """

    def test_a_filtered_mutant_is_not_undetermined(self, mv, tmp_path: Path) -> None:
        source = tmp_path / "m.py"
        source.write_text(_DEFERRED)
        session = _session(tmp_path, [{"worker": "SKIPPED", "outcome": None}])

        report = mv.classify(session, "m.py", source)

        assert [v.category for v in report.verdicts] == ["skipped"]
        assert report.undetermined == []

    def test_skipped_is_subtracted_under_the_future_import(self, mv) -> None:
        report = mv.Report(total=10, killed=7, future_annotations=True)
        report.verdicts = [mv.Verdict("j", 1, 0, "op", "skipped", "x")]

        _killed, denominator, rate = report.adjusted()

        assert denominator == 9
        assert rate == pytest.approx(7 / 9)

    def test_skipped_is_not_subtracted_without_the_future_import(self, mv) -> None:
        """Without the import an annotation is a live expression, so a mutation
        there is killable and its exclusion would be unearned -- the same rule
        `non_viable` already follows."""
        report = mv.Report(total=10, killed=7, future_annotations=False)
        report.verdicts = [mv.Verdict("j", 1, 0, "op", "skipped", "x")]

        _killed, denominator, _rate = report.adjusted()

        assert denominator == 10

    def test_the_task_policy_shape_scores_what_actually_ran(self, mv, tmp_path: Path) -> None:
        """The measured regression: 110 executed mutants all killed, beside 99
        filtered annotation mutants, read as 52.6% instead of 100%."""
        source = tmp_path / "m.py"
        source.write_text(_DEFERRED)
        rows = [{"outcome": "KILLED"} for _ in range(110)]
        rows += [{"worker": "SKIPPED", "outcome": None} for _ in range(99)]
        session = _session(tmp_path, rows)

        report = mv.classify(session, "m.py", source)
        killed, denominator, rate = report.adjusted()

        assert (killed, denominator) == (110, 110)
        assert rate == pytest.approx(1.0)


class TestSkippedInTheHumanReport:
    """The printed summary is the only place most readers see the split.

    `adjusted()` can be right while the report says nothing about *why* the
    denominator moved, and a reader comparing a raw 40% against an adjusted
    92% with no line naming the skipped bucket has no way to tell a correct
    exclusion from a bug in this script.
    """

    def test_the_summary_names_the_skipped_count(self, mv, capsys) -> None:
        report = mv.Report(total=10, killed=7, future_annotations=True)
        report.verdicts = [mv.Verdict(f"j{i}", 1, 0, "op", "skipped", "x") for i in range(3)]

        assert _emit_status(mv, report) == 0
        out = capsys.readouterr().out

        assert "skipped    (filtered before exec; annotation-only) : 3" in out
        assert "adjusted  : 7/7 = 100.0%" in out

    def test_without_the_future_import_the_report_says_they_were_kept(self, mv, capsys) -> None:
        """The one case where the count and the denominator disagree, so the
        report has to say so rather than let the reader assume subtraction."""
        report = mv.Report(total=10, killed=7, future_annotations=False)
        report.verdicts = [mv.Verdict("j", 1, 0, "op", "skipped", "x")]

        assert _emit_status(mv, report) == 0
        out = capsys.readouterr().out

        assert "skipped mutants are NOT subtracted here: no future import." in out
        assert "adjusted  : 7/10" in out

    def test_the_subtraction_rule_is_stated_every_time(self, mv, capsys) -> None:
        """Including when nothing was skipped -- the rule is what makes the
        number auditable, and printing it only sometimes is how a reader comes
        to believe `invalid` and `undetermined` are excluded too."""
        report = mv.Report(total=4, killed=4, future_annotations=True)

        assert _emit_status(mv, report) == 0

        assert (
            "(non-viable and skipped are subtracted; invalid and undetermined are not)"
            in capsys.readouterr().out
        )


class TestSessionScoping:
    """A session may hold many modules; a report describes exactly one."""

    def test_other_modules_are_not_counted(self, mv, tmp_path: Path) -> None:
        src = tmp_path / "deferred.py"
        src.write_text(_DEFERRED)
        session = _session(
            tmp_path,
            [
                {"module": "m.py", "outcome": "KILLED"},
                {"module": "other.py", "outcome": "SURVIVED"},
                {"module": "other.py", "outcome": "SURVIVED"},
            ],
        )

        report = mv.classify(session, "m.py", src)

        assert report.total == 1, "another module's mutants were counted"
        assert report.killed == 1

    def test_unknown_module_is_an_error_not_an_empty_pass(self, mv, tmp_path: Path) -> None:
        """A typo'd path must not read as a clean 0/0 sweep."""
        src = tmp_path / "deferred.py"
        src.write_text(_DEFERRED)
        session = _session(tmp_path, [{"module": "m.py"}])

        with pytest.raises(SystemExit):
            mv.classify(session, "typo.py", src)


class TestIncompleteSession:
    def test_pending_work_is_reported_and_refuses_to_score(self, mv, tmp_path: Path) -> None:
        """An interrupted sweep must not be scored on the jobs that finished."""
        src = tmp_path / "deferred.py"
        src.write_text(_DEFERRED)
        session = _session(tmp_path, [{"outcome": "KILLED"}], specs_only=4)

        report = mv.classify(session, "m.py", src)

        assert report.pending == 4
        assert _emit_status(mv, report) == 1, "a partial session was scored anyway"


def _emit_status(mv, report) -> int:
    return mv._emit(report, None)


class TestDiffReconstruction:
    def test_deletion_only_hunk_is_supported(self, mv) -> None:
        """`core/RemoveDecorator` emits a removed line and no added line.

        Rejecting that shape parked every such mutant in `undetermined`, where
        it stayed in the denominator but never showed up as the coverage gap it
        actually is.
        """
        pristine = "a = 1\nb = 2\nc = 3\n"
        out = mv._apply_diff(pristine, _diff(2, "b = 2", None))

        assert out == "a = 1\nc = 3\n"

    def test_replacement_hunk_still_works(self, mv) -> None:
        pristine = "a = 1\nb = 2\nc = 3\n"
        out = mv._apply_diff(pristine, _diff(2, "b = 2", "b = 99"))

        assert out == "a = 1\nb = 99\nc = 3\n"

    def test_unreconstructable_diff_returns_none(self, mv) -> None:
        assert mv._apply_diff("a = 1\n", "no hunk header here") is None


class TestStripperPrecision:
    """What the stripper refuses to erase is what makes exclusion a proof."""

    def test_keyword_only_marker_change_is_not_equivalent(self, mv) -> None:
        """`*,` -> `/,` moves args between posonlyargs and args.

        It looks as cosmetic as a type hint and is not: it changes the call
        contract, so it must survive annotation-stripping as a difference.
        """
        star = "def f(a, *, b): pass\n"
        slash = "def f(a, /, b): pass\n"

        assert mv._normalized(star) != mv._normalized(slash)

    def test_default_value_change_is_not_equivalent(self, mv) -> None:
        """Defaults are evaluated even under PEP 563.

        `max_steps: int = 256` reads like an annotation line, but a mutant on
        the 256 hits live code.
        """
        a = "from __future__ import annotations\ndef f(n: int = 256): pass\n"
        b = "from __future__ import annotations\ndef f(n: int = 257): pass\n"

        assert mv._normalized(a) != mv._normalized(b)

    def test_annotation_change_alone_is_equivalent(self, mv) -> None:
        a = "from __future__ import annotations\ndef f(x: str | None): pass\n"
        b = "from __future__ import annotations\ndef f(x: str + None): pass\n"

        assert mv._normalized(a) == mv._normalized(b)


class TestGate:
    """`gate()` decides the build, so its refusals are the contract.

    The properties below were carried by the inline heredoc this replaced, and
    the point of moving the scoring into a script was to make them testable
    rather than to change them.
    """

    def _module(self, tmp_path: Path, source: str = _DEFERRED) -> str:
        path = tmp_path / "mod.py"
        path.write_text(source)
        return str(path)

    def _manifest(self, tmp_path: Path, session: Path, module: str) -> Path:
        path = tmp_path / "sessions.tsv"
        path.write_text(f"{session}\t{module}\n")
        return path

    def test_a_rate_below_the_threshold_fails_the_build(self, mv, tmp_path: Path) -> None:
        module = self._module(tmp_path)
        session = _session(
            tmp_path,
            [{"module": module, "outcome": "KILLED"}] + [{"module": module}] * 3,
        )

        assert mv.gate([(session, module)], 0.90, None) == 1

    def test_a_rate_above_the_threshold_passes(self, mv, tmp_path: Path) -> None:
        module = self._module(tmp_path)
        session = _session(tmp_path, [{"module": module, "outcome": "KILLED"}] * 10)

        assert mv.gate([(session, module)], 0.90, None) == 0

    def test_zero_mutants_is_an_error_not_a_pass(self, mv, tmp_path: Path) -> None:
        """A config error that produces no mutants must never read as 100%.

        This is the failure mode the gate exists to prevent: a broken
        invocation is indistinguishable from a perfect score unless something
        checks explicitly.
        """
        module = self._module(tmp_path)
        session = _session(tmp_path, [{"module": "other.py", "outcome": "KILLED"}])

        # No specs for the requested module at all.
        with pytest.raises(SystemExit):
            mv.gate([(session, module)], 0.90, None)

    def test_an_incomplete_sweep_refuses_to_score(self, mv, tmp_path: Path) -> None:
        """Unfinished work must not be scored on the jobs that happened to end.

        Counting only completed results would shrink the denominator and
        inflate the rate, so an interrupted run could pass a gate its finished
        mutants had not earned.
        """
        module = self._module(tmp_path)
        session = _session(tmp_path, [{"module": module, "outcome": "KILLED"}] * 10, specs_only=5)

        assert mv.gate([(session, module)], 0.90, None) == 1

    def test_excluding_everything_is_an_error_not_a_pass(self, mv, tmp_path: Path) -> None:
        """If every mutant is non-viable the denominator is zero.

        `0/0` must not be reported as success -- that would turn a file the
        gate cannot meaningfully measure into a file that always passes.
        """
        module = self._module(tmp_path)
        row = 3  # the `def f(...)` line of _DEFERRED
        diff = _diff(
            row, "def f(x: str | None = None) -> int:", "def f(x: str + None = None) -> int:"
        )
        session = _session(tmp_path, [{"module": module, "row": row, "diff": diff}])

        assert mv.gate([(session, module)], 0.90, None) == 1

    def test_the_threshold_is_honoured(self, mv, tmp_path: Path) -> None:
        """Same session, two thresholds, two verdicts."""
        module = self._module(tmp_path)
        rows = [{"module": module, "outcome": "KILLED"}] * 8 + [{"module": module}] * 2
        session = _session(tmp_path, rows)

        assert mv.gate([(session, module)], 0.75, None) == 0
        assert mv.gate([(session, module)], 0.90, None) == 1

    def test_survivors_are_reported_grouped_by_line(self, mv, tmp_path: Path, capsys) -> None:
        """Failure output must say where to look, not dump result rows.

        The version this replaced printed a Python repr of each result dict,
        which named neither the line nor the change.
        """
        module = self._module(tmp_path)
        diff = _diff(4, "    return 1", "    return 2")
        session = _session(
            tmp_path,
            [{"module": module, "row": 4, "diff": diff, "op": "core/NumberReplacer"}] * 3,
        )

        mv.gate([(session, module)], 0.90, None)

        out = capsys.readouterr().out
        assert f"{module}:4" in out
        assert "3 surviving mutants" in out
        assert "return 2" in out

    def test_multiple_modules_are_scored_together(self, mv, tmp_path: Path) -> None:
        """The gate is an aggregate across every mutated file, as before."""
        a = tmp_path / "a.py"
        a.write_text(_DEFERRED)
        b = tmp_path / "b.py"
        b.write_text(_DEFERRED)
        sess_a = _session(tmp_path, [{"module": str(a), "outcome": "KILLED"}] * 10, name="a")
        sess_b = _session(tmp_path, [{"module": str(b)}] * 10, name="b")

        # 10 killed of 20 overall -> 50%, below the gate even though `a` alone
        # would pass.
        assert mv.gate([(sess_a, str(a)), (sess_b, str(b))], 0.90, None) == 1


class TestManifest:
    def test_a_malformed_line_is_rejected(self, mv, tmp_path: Path) -> None:
        path = tmp_path / "m.tsv"
        path.write_text("session-with-no-tab\n")

        with pytest.raises(SystemExit):
            mv._read_pairs(path)

    def test_an_empty_manifest_is_rejected(self, mv, tmp_path: Path) -> None:
        path = tmp_path / "m.tsv"
        path.write_text("\n\n")

        with pytest.raises(SystemExit):
            mv._read_pairs(path)

    def test_blank_lines_are_skipped(self, mv, tmp_path: Path) -> None:
        path = tmp_path / "m.tsv"
        path.write_text("s1.sqlite\tmod_a.py\n\ns2.sqlite\tmod_b.py\n")

        pairs = mv._read_pairs(path)

        assert [m for _s, m in pairs] == ["mod_a.py", "mod_b.py"]
