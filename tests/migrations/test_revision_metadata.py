"""Static checks for Alembic revision metadata."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "alembic" / "versions"


def _literal_assignment(path: Path, name: str) -> str | tuple[str, ...] | None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
        if isinstance(node.value, ast.Tuple):
            # A merge revision points at every branch head it joins
            # (`down_revision = ("a", "b")`). Reading those as "no
            # down_revision" made every merged branch look like a surviving
            # head.
            parts: list[str] = []
            for element in node.value.elts:
                if not (isinstance(element, ast.Constant) and isinstance(element.value, str)):
                    return None
                parts.append(element.value)
            return tuple(parts)
    return None


def test_migration_revision_ids_are_unique() -> None:
    """Concurrent migration work must not silently create duplicate IDs."""
    revisions = {path: _literal_assignment(path, "revision") for path in VERSIONS.glob("*.py")}
    present = [revision for revision in revisions.values() if revision is not None]
    assert len(present) == len(set(present)), (
        "duplicate Alembic revision IDs: "
        f"{[revision for revision in present if present.count(revision) > 1]}"
    )


def test_migration_chain_has_one_head() -> None:
    """Every migration except the root must point at an existing revision."""
    revisions = {path: _literal_assignment(path, "revision") for path in VERSIONS.glob("*.py")}
    down_revisions = {_literal_assignment(path, "down_revision") for path in revisions}
    revision_ids = {revision for revision in revisions.values() if revision is not None}
    referenced: set[str] = set()
    for down_revision in down_revisions:
        if isinstance(down_revision, str):
            referenced.add(down_revision)
        elif isinstance(down_revision, tuple):
            referenced.update(down_revision)
    assert referenced <= revision_ids, (
        f"unknown migration parents: {sorted(referenced - revision_ids)}"
    )
    heads = revision_ids - referenced
    assert len(heads) == 1, f"expected one migration head, found {sorted(heads)}"
