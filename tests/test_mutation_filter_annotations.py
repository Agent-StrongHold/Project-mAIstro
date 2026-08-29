"""Tests for the annotation-mutant filter (#419).

Under `from __future__ import annotations` an annotation is a *string*. Python
never evaluates it, so a mutation inside one changes nothing a test could
observe — it survives by construction, costs a full test-command run, and lands
in the survivor list for a human to triage as "equivalent", every time.

Measured on this repository: 1,861 union nodes in annotation position across
the 682 files under `packages/*/src` that carry the future import. At six
operators apiece that is ~11,166 unkillable mutants and, at the 5.9s/mutant
this repository achieves, ~18 hours of runner time producing no signal.

The whole risk of this filter is in the other direction: skipping a mutant a
test *could* have killed silently lowers the bar. So the cases below are
organised around telling the two apart, and the runtime-union case is the one
that matters most — it is the same operator, in the same file, distinguished
only by position.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mutation_filter_annotations.py"


@pytest.fixture(scope="module")
def filt():
    spec = importlib.util.spec_from_file_location("mutation_filter_annotations", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _span_of(filt, source: str, needle: str):
    """The (start, end) of `needle` in `source`, as cosmic-ray reports it."""
    for lineno, line in enumerate(source.splitlines(), 1):
        col = line.find(needle)
        if col != -1:
            return (lineno, col), (lineno, col + len(needle))
    raise AssertionError(f"{needle!r} not in source")


FUTURE = "from __future__ import annotations\n"


class TestWhatIsSkipped:
    def test_a_return_annotation_union_is_inside_an_annotation(self, filt):
        src = FUTURE + "def f(x: int) -> str | None:\n    return None\n"
        assert filt.is_annotation_mutant(
            filt.annotation_spans(src), *_span_of(filt, src, "str | None")
        )

    def test_a_parameter_annotation_union_is_too(self, filt):
        src = FUTURE + "def f(x: int | None) -> str:\n    return ''\n"
        assert filt.is_annotation_mutant(
            filt.annotation_spans(src), *_span_of(filt, src, "int | None")
        )

    def test_an_annotated_assignment_is_too(self, filt):
        src = FUTURE + "value: int | None = None\n"
        assert filt.is_annotation_mutant(
            filt.annotation_spans(src), *_span_of(filt, src, "int | None")
        )

    @pytest.mark.parametrize(
        "signature",
        [
            "def f(*args: int | None) -> None: ...",
            "def f(**kw: int | None) -> None: ...",
            "def f(*, key: int | None) -> None: ...",
            "def f(pos: int | None, /) -> None: ...",
        ],
    )
    def test_every_parameter_kind_is_covered(self, filt, signature):
        """One missed argument kind is a silent hole: those mutants keep
        running forever and keep surviving."""
        src = FUTURE + signature + "\n"
        assert filt.is_annotation_mutant(
            filt.annotation_spans(src), *_span_of(filt, src, "int | None")
        )

    def test_an_async_function_is_covered(self, filt):
        src = FUTURE + "async def f() -> str | None:\n    return None\n"
        assert filt.annotation_spans(src)


class TestWhatMustNotBeSkipped:
    """Skipping a killable mutant silently lowers the bar — the failure this
    filter must not have."""

    def test_a_runtime_union_is_not_an_annotation(self, filt):
        """`isinstance(node, A | B)` IS evaluated and its mutants ARE killable.
        Same operator, same file, told apart only by position — which is why
        this filter is positional rather than a regex over operator names."""
        src = (
            FUTURE
            + "import ast\n\n\ndef f(node: ast.AST) -> bool:\n    return isinstance(node, ast.Name | ast.Attribute)\n"
        )
        assert not filt.is_annotation_mutant(
            filt.annotation_spans(src), *_span_of(filt, src, "ast.Name | ast.Attribute")
        )

    def test_a_default_value_is_not_an_annotation(self, filt):
        src = FUTURE + "def f(mask: int = 1 | 2) -> None: ...\n"
        assert not filt.is_annotation_mutant(
            filt.annotation_spans(src), *_span_of(filt, src, "1 | 2")
        )

    def test_a_body_expression_is_not_an_annotation(self, filt):
        src = FUTURE + "def f(a: int, b: int) -> int:\n    return a | b\n"
        assert not filt.is_annotation_mutant(
            filt.annotation_spans(src), *_span_of(filt, src, "a | b")
        )

    def test_without_the_future_import_nothing_is_skipped(self, filt):
        """There an annotation is evaluated at definition time, so mutating it
        is fair game and a test can kill it."""
        src = "def f(x: int) -> str | None:\n    return None\n"
        assert filt.annotation_spans(src) == []

    def test_a_mutation_straddling_an_annotation_edge_is_not_skipped(self, filt):
        """Wholly inside, not partly. An unobserved shape should fail toward
        running the mutant rather than silently dropping it."""
        src = FUTURE + "def f(x: int | None) -> None: ...\n"
        spans = filt.annotation_spans(src)
        (start, _end) = _span_of(filt, src, "int | None")
        beyond = (start[0], 999)
        assert not filt.is_annotation_mutant(spans, start, beyond)

    def test_an_unparseable_file_skips_nothing(self, filt):
        """A syntax error is somebody else's finding. Guessing here would drop
        every mutant in the file."""
        assert filt.annotation_spans(FUTURE + "def (\n") == []


class TestAgainstTheRealTree:
    """The file this was measured on, asserted at both ends."""

    def test_the_gate_scripts_annotation_union_is_skipped(self, filt):
        src = (ROOT / "scripts" / "check-cross-package-imports.py").read_text(encoding="utf-8")
        spans = filt.annotation_spans(src)
        assert spans, "no annotations found; the future-import check may have broken"
        assert filt.is_annotation_mutant(spans, *_span_of(filt, src, "Path | None"))

    def test_the_same_files_runtime_union_is_not(self, filt):
        """`isinstance(node, ast.FunctionDef | ...)` in the same file, which a
        test does kill. Both assertions have to hold on one real file or the
        filter is measuring something other than position."""
        src = (ROOT / "scripts" / "check-cross-package-imports.py").read_text(encoding="utf-8")
        spans = filt.annotation_spans(src)
        assert not filt.is_annotation_mutant(
            spans, *_span_of(filt, src, "ast.FunctionDef | ast.AsyncFunctionDef")
        )


class _Mutation:
    """The fields of cosmic-ray's `MutationSpec` this filter reads."""

    def __init__(self, module_path, start_pos, end_pos):
        self.module_path = module_path
        self.start_pos = start_pos
        self.end_pos = end_pos


class _Item:
    def __init__(self, job_id, mutations):
        self.job_id = job_id
        self.mutations = mutations


class _WorkDB:
    """Enough of cosmic-ray's WorkDB to drive the filter.

    A fake rather than a real session: building one needs `cosmic-ray init`,
    which needs a whole config and a source tree, and none of that is what
    these cases are about. The end-to-end wiring is covered by running the
    filter against a real session — 11 skipped on one gate, 33 on another.
    """

    def __init__(self, items):
        self.pending_work_items = items
        self.results = {}

    def set_result(self, job_id, result):
        self.results[job_id] = result


class TestTheFilterLoop:
    """The loop that decides what to skip. Until now it was proven only by a
    manual run against a real session, which is not a thing CI can repeat."""

    @pytest.fixture
    def module(self, tmp_path):
        path = tmp_path / "target.py"
        path.write_text(
            FUTURE + "def f(x: int | None) -> str:\n    return str(x or 1 | 2)\n",
            encoding="utf-8",
        )
        return path

    def _run(self, filt, db, report=False):
        import argparse

        filt.AnnotationsFilter().filter(db, argparse.Namespace(report=report))

    def test_an_annotation_mutant_is_marked_skipped(self, filt, module):
        span = _span_of(filt, module.read_text(), "int | None")
        db = _WorkDB([_Item("job-1", [_Mutation(module, *span)])])
        self._run(filt, db)
        assert "job-1" in db.results
        assert db.results["job-1"].worker_outcome.name == "SKIPPED"

    def test_a_runtime_mutant_is_left_pending(self, filt, module):
        """`1 | 2` in the body is evaluated, so its mutants are killable and
        must reach the worker."""
        span = _span_of(filt, module.read_text(), "1 | 2")
        db = _WorkDB([_Item("job-2", [_Mutation(module, *span)])])
        self._run(filt, db)
        assert db.results == {}

    def test_the_reason_reaches_the_result(self, filt, module):
        """Someone reading the session later needs to know why a job was
        skipped rather than run — "SKIPPED" alone looks like a crash."""
        span = _span_of(filt, module.read_text(), "int | None")
        db = _WorkDB([_Item("job-3", [_Mutation(module, *span)])])
        self._run(filt, db)
        assert "type annotation" in db.results["job-3"].output

    def test_one_item_is_skipped_once_however_many_mutations_it_carries(self, filt, module):
        """`set_result` is per job. Counting per mutation would report more
        skips than there are jobs."""
        span = _span_of(filt, module.read_text(), "int | None")
        item = _Item("job-4", [_Mutation(module, *span), _Mutation(module, *span)])
        db = _WorkDB([item])
        self._run(filt, db)
        assert list(db.results) == ["job-4"]

    def test_an_unreadable_module_skips_nothing(self, filt, tmp_path):
        """A path that cannot be read yields no spans, so nothing is filtered —
        the safe direction, since the mutant then simply runs."""
        db = _WorkDB([_Item("job-5", [_Mutation(tmp_path / "gone.py", (1, 0), (1, 9))])])
        self._run(filt, db)
        assert db.results == {}

    def test_each_module_is_parsed_once(self, filt, module, monkeypatch):
        """The cache is what keeps this proportional: a packet has hundreds of
        mutants in one file, and re-parsing per mutant would cost more than the
        mutants it saves."""
        calls = []
        original = filt.annotation_spans
        monkeypatch.setattr(filt, "annotation_spans", lambda src: calls.append(1) or original(src))
        span = _span_of(filt, module.read_text(), "int | None")
        db = _WorkDB([_Item(f"job-{i}", [_Mutation(module, *span)]) for i in range(5)])
        self._run(filt, db)
        assert len(calls) == 1
        assert len(db.results) == 5

    def test_the_report_counts_mutants_and_files(self, filt, module, capsys):
        span = _span_of(filt, module.read_text(), "int | None")
        db = _WorkDB([_Item("job-6", [_Mutation(module, *span)])])
        self._run(filt, db, report=True)
        out = capsys.readouterr().out
        assert "skipped 1 annotation mutant(s) across 1 file(s)" in out

    def test_it_stays_quiet_without_report(self, filt, module, capsys):
        span = _span_of(filt, module.read_text(), "int | None")
        db = _WorkDB([_Item("job-7", [_Mutation(module, *span)])])
        self._run(filt, db)
        assert capsys.readouterr().out == ""


class TestTheCommandLine:
    def test_report_is_an_accepted_flag(self, filt):
        import argparse

        parser = argparse.ArgumentParser()
        filt.AnnotationsFilter().add_args(parser)
        assert parser.parse_args(["--report"]).report is True

    def test_report_defaults_off(self, filt):
        import argparse

        parser = argparse.ArgumentParser()
        filt.AnnotationsFilter().add_args(parser)
        assert parser.parse_args([]).report is False

    def test_the_description_is_the_module_docstring(self, filt):
        """`--help` is where someone finds out why their mutant vanished."""
        assert "annotation" in filt.AnnotationsFilter().description()
