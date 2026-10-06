"""Cited `tests:` paths must resolve to a real file (#812).

`schema.FrontMatter` validates `tests:` as a list of strings and nothing
more, so a document could cite `packages/x/tests/test_gone.py` long after
that file was deleted — or never existed — and remain registry-green while
other gates treat the entry as proof (ADR-097's lifecycle machine requires
non-empty `tests:` for specs claiming Tests Passing / Implemented). A
decision can therefore cite evidence that is not there.

The check is deliberately about *resolution*, not relevance: an entry may
cite a single test (`path::test_case` — everything from `::` on is a node
id, so only the file portion is resolved) or a whole suite directory
(SPEC-200 cites `packages/maistro-bootstrap/tests/`). Either form must
name a path that exists under the repository root; a path that escapes the
root cannot be evidence in this repository at all.

Failing on an unresolved path is a lint error, not a warning: a dead
citation is not a style problem, it is a false evidence claim, and the
strict gate (`maistro-registry.cli lint . --strict`) is where the CI
workflow enforces it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from maistro_registry.schema import FrontMatter


@dataclass(frozen=True)
class TestPathProblem:
    """One `tests:` entry whose file portion does not resolve under `root`."""

    source: str
    entry: str
    file_portion: str
    reason: str

    def render(self) -> str:
        return f"{self.source}.tests -> {self.entry}: {self.reason}"


def file_portion_of(entry: str) -> str:
    """The file part of a pytest-style `path::node::id` reference."""
    return entry.split("::", 1)[0].strip()


def _resolution_failure(portion: str, root: Path) -> str | None:
    """Why `portion` does not resolve under `root`, or None when it does."""
    if not portion:
        return "cites an empty file path"
    try:
        resolved_root = root.resolve()
        resolved = (root / portion).resolve()
    except OSError:
        return "cannot be resolved"
    # A path outside the repository cannot be cited as in-repo evidence,
    # however real the file it lands on happens to be.
    if not resolved.is_relative_to(resolved_root):
        return "escapes the repository root"
    if not resolved.exists():
        return "does not exist under the repository root"
    return None


def check_test_paths(front_matters: Iterable[FrontMatter], root: Path) -> list[TestPathProblem]:
    """Every `tests:` entry that fails to resolve, in walk order.

    Directories resolve too: a suite-directory citation is evidence about
    the suite, and existence is the question this check answers (SPEC-200).
    """
    root = Path(root)
    problems: list[TestPathProblem] = []
    for fm in front_matters:
        source = f"{fm.repo.value}#{fm.id}"
        for entry in fm.tests:
            portion = file_portion_of(entry)
            reason = _resolution_failure(portion, root)
            if reason is not None:
                problems.append(
                    TestPathProblem(source=source, entry=entry, file_portion=portion, reason=reason)
                )
    return problems
