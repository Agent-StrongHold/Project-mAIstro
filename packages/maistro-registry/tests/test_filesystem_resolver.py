"""Focused tmp-tree tests for `FilesystemResolver` (#814).

Resolution must follow the *declared* front-matter id, never the filename.
A file whose name implies one id while its front matter declares another
makes only the declared id resolve: the filename is storage metadata and
cannot establish an identity the front matter withholds.

Mutation provenance (AC-4): every `is False` assertion below fails under at
least one of the two known resolver mutations —

- `return True` (unconditional success) is killed by the disagreement,
  missing-id, invalid-id, undeclared-id, and template tests;
- the old filename-prefix matcher (`f.name.startswith(f"{item_id}-")` over
  a non-recursive `iterdir()`) is killed by the disagreement, missing-id,
  invalid-id, and nested-path tests.
"""

from __future__ import annotations

from pathlib import Path

from maistro_registry.cli import main
from maistro_registry.linker import FilesystemResolver


def _doc(item_id: str, *, kind: str = "adr") -> str:
    """A minimal *valid* front-matter record declaring `item_id`."""
    return f"""---
id: {item_id}
title: "The {item_id} record"
repo: maistro-engine
kind: {kind}
status: Proposed
created: 2026-06-10
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts: []
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# {item_id}: body
"""


def _resolver(root: Path) -> FilesystemResolver:
    return FilesystemResolver(engine_root=root)


def test_declared_id_resolves(tmp_path: Path) -> None:
    adr = tmp_path / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "ADR-030-example.md").write_text(_doc("ADR-030"))

    assert _resolver(tmp_path).resolve("maistro-engine", "ADR-030") is True


def test_filename_cannot_establish_an_undeclared_id(tmp_path: Path) -> None:
    """Filename says ADR-010, front matter says ADR-020: only ADR-020 exists."""
    adr = tmp_path / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "ADR-010-mislabeled.md").write_text(_doc("ADR-020"))

    resolver = _resolver(tmp_path)
    assert resolver.resolve("maistro-engine", "ADR-010") is False
    assert resolver.resolve("maistro-engine", "ADR-020") is True


def test_duplicate_declared_id_still_resolves(tmp_path: Path) -> None:
    """Two files declaring one id: the id exists; ambiguity is the walk's
    DUPLICATE finding (`find_duplicate_ids`), not a resolver question."""
    adr = tmp_path / "docs" / "adr"
    specs = tmp_path / "docs" / "specs"
    adr.mkdir(parents=True)
    specs.mkdir(parents=True)
    (adr / "ADR-040-first.md").write_text(_doc("ADR-040"))
    (specs / "ADR-040-second.md").write_text(_doc("ADR-040", kind="spec"))

    assert _resolver(tmp_path).resolve("maistro-engine", "ADR-040") is True


def test_missing_front_matter_declares_nothing(tmp_path: Path) -> None:
    """A walked file without a front-matter block contributes no id, however
    canonical its filename — the old filename matcher resolved it anyway."""
    adr = tmp_path / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "ADR-050-no-front-matter.md").write_text("# prose only, no front matter\n")

    assert _resolver(tmp_path).resolve("maistro-engine", "ADR-050") is False


def test_invalid_front_matter_declares_nothing(tmp_path: Path) -> None:
    """An id that fails the schema pattern is not an identity, so the
    filename-implied id must not resolve."""
    adr = tmp_path / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "ADR-060-bad-id.md").write_text(_doc("ADR-60"))  # two digits: illegal

    assert _resolver(tmp_path).resolve("maistro-engine", "ADR-060") is False


def test_undeclared_id_does_not_resolve_even_when_records_exist(tmp_path: Path) -> None:
    """Kills the 'any record file exists → resolve' mutant: a matching id
    must be *declared*, not merely accompanied by neighboring files."""
    adr = tmp_path / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "ADR-030-real.md").write_text(_doc("ADR-030"))

    assert _resolver(tmp_path).resolve("maistro-engine", "SPEC-001") is False


def test_nested_spec_paths_are_indexed(tmp_path: Path) -> None:
    """The walk is `docs/specs/**/*.md`; the old `iterdir()` matcher never
    saw nested spec files at all."""
    nested = tmp_path / "docs" / "specs" / "auth"
    nested.mkdir(parents=True)
    (nested / "SPEC-177-login.md").write_text(_doc("SPEC-177", kind="spec"))

    assert _resolver(tmp_path).resolve("maistro-engine", "SPEC-177") is True


def test_template_files_are_not_records(tmp_path: Path) -> None:
    """The resolver consumes the registry *walk*, templates included in its
    skips — a scaffolding placeholder declares no resolvable id."""
    adr = tmp_path / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "ADR-000-template.md").write_text(_doc("ADR-000"))

    assert _resolver(tmp_path).resolve("maistro-engine", "ADR-000") is False


def test_non_engine_repos_stay_optimistic(tmp_path: Path) -> None:
    """Documented posture: single-repo runs must not false-flag cross-repo
    references; `GitHubResolver` owns cross-repo accuracy."""
    assert _resolver(tmp_path).resolve("some-other-repo", "ADR-999") is True


def test_missing_engine_root_resolves_nothing(tmp_path: Path) -> None:
    """A root with no walked files declares no ids; resolution fails closed."""
    resolver = _resolver(tmp_path / "does-not-exist")

    assert resolver.resolve("maistro-engine", "ADR-030") is False


def test_lint_flags_a_reference_only_the_filename_implies(tmp_path: Path, capsys) -> None:
    """End-to-end through `lint` (#814's original defect): a relationship
    pointing at a filename-implied id dangles; the declared id resolves.

    Under the old filename-prefix resolver the first assertion fails —
    the implied id resolved and no DANGLING line was printed for it.
    """
    adr = tmp_path / "docs" / "adr"
    adr.mkdir(parents=True)
    referencing = _doc("ADR-030").replace(
        "related: []",
        "related: ['maistro-engine#ADR-010', 'maistro-engine#ADR-020']",
    )
    (adr / "ADR-030-referencing.md").write_text(referencing)
    (adr / "ADR-010-mislabeled.md").write_text(_doc("ADR-020"))

    assert main(["lint", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "-> maistro-engine#ADR-010 (DANGLING)" in out
    assert "-> maistro-engine#ADR-020 (DANGLING)" not in out
