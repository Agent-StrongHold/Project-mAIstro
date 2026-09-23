"""Every declared correlation field has a production producer (#63).

`FIELD_NAMES` is a promise to a log reader: filter on any of these and the
lines of that execution come back. A field nothing binds keeps that promise
only in the docs. This scans production code for `bind_execution_context(...)`
calls and requires each declared field to be bound by at least one, apart from
a reviewed allowlist whose entries name the slice that owes the producer.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping
from pathlib import Path

import pytest

from maistro.observability import correlation

#: Declared fields with no production producer yet, each naming its owner.
#: Shrinks as those slices land; an entry whose field gains a producer fails
#: `test_the_allowlist_names_only_fields_still_without_a_producer`.
_AWAITING_PRODUCER: Mapping[str, str] = {
    "invocation_id": "#63 invocation-binding slice",
    "session_id": "#63 session slice",
}

_BINDER = "bind_execution_context"


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists() and (parent / "packages").is_dir():
            return parent
    raise AssertionError("could not locate the repository root from the test file")


def _production_files() -> list[Path]:
    packages = _repo_root() / "packages"
    roots = [*sorted(packages.glob("*/src")), packages / "hive-conductor" / "backend"]
    return sorted(
        path
        for root in roots
        for path in root.rglob("*.py")
        if "tests" not in path.relative_to(root).parts
    )


def _is_blank(value: ast.expr) -> bool:
    """A literal `None` or `""` binds nothing: blanks leave the context as it was."""
    return isinstance(value, ast.Constant) and value.value in (None, "")


def _bound_fields(tree: ast.AST) -> set[str]:
    """Keyword names passed to `bind_execution_context` calls in `tree`.

    A `**ids` splat names nothing statically, so it produces nothing here: a
    producer has to be legible at the call site to count.
    """
    bound: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name != _BINDER:
            continue
        bound.update(kw.arg for kw in node.keywords if kw.arg and not _is_blank(kw.value))
    return bound


def _produced_fields(files: Iterable[Path]) -> set[str]:
    produced: set[str] = set()
    for path in files:
        produced |= _bound_fields(ast.parse(path.read_text(), filename=str(path)))
    return produced


def _unproduced(declared: Iterable[str], produced: set[str]) -> list[str]:
    return [
        field for field in declared if field not in produced and field not in _AWAITING_PRODUCER
    ]


@pytest.fixture(scope="module")
def produced() -> set[str]:
    return _produced_fields(_production_files())


class TestEveryDeclaredFieldHasAProducer:
    def test_every_declared_field_is_bound_in_production(self, produced: set[str]) -> None:
        missing = _unproduced(correlation.FIELD_NAMES, produced)
        assert missing == [], (
            f"declared correlation fields no production code binds: {missing}. "
            f"Bind them via {_BINDER}(...) on the real path, or add a reviewed "
            "allowlist entry naming the owning slice/issue."
        )

    def test_the_allowlist_names_only_fields_still_without_a_producer(
        self, produced: set[str]
    ) -> None:
        stale = sorted(set(_AWAITING_PRODUCER) & produced)
        assert stale == [], (
            f"these fields now have a producer; drop them from the allowlist: {stale}"
        )

    def test_the_allowlist_names_only_declared_fields(self) -> None:
        assert set(_AWAITING_PRODUCER) <= set(correlation.FIELD_NAMES)

    def test_every_allowlist_entry_names_its_owner(self) -> None:
        assert all("#" in owner for owner in _AWAITING_PRODUCER.values())

    def test_a_newly_declared_field_without_a_producer_fails(
        self, produced: set[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(correlation, "FIELD_NAMES", (*correlation.FIELD_NAMES, "planted_id"))
        assert _unproduced(correlation.FIELD_NAMES, produced) == ["planted_id"]


class TestTheScan:
    def test_the_corpus_covers_every_known_bind_site(self) -> None:
        """A guard whose corpus misses the producers guards nothing."""
        root = _repo_root()
        scanned = {str(path.relative_to(root)) for path in _production_files()}
        assert {
            "packages/maistro-core/src/maistro/observability/middleware.py",
            "packages/maistro-core/src/maistro/runs/execution.py",
            "packages/hive-conductor/backend/services/scheduler.py",
        } <= scanned
        assert not any("/tests/" in path for path in scanned)

    def test_a_qualified_and_a_bare_call_are_both_read(self) -> None:
        source = (
            "correlation.bind_execution_context(run_id=r)\n"
            "with bind_execution_context(attempt_id=a, workspace_id=w): pass\n"
        )
        assert _bound_fields(ast.parse(source)) == {"run_id", "attempt_id", "workspace_id"}

    def test_a_blank_literal_is_not_a_producer(self) -> None:
        source = "bind_execution_context(session_id=None, invocation_id='')"
        assert _bound_fields(ast.parse(source)) == set()

    def test_a_splat_is_not_a_producer(self) -> None:
        assert _bound_fields(ast.parse("bind_execution_context(**ids)")) == set()

    def test_another_call_with_the_same_keywords_is_not_a_producer(self) -> None:
        assert _bound_fields(ast.parse("structlog.bind(session_id=s)")) == set()
