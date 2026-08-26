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
