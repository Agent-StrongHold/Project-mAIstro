"""Static checks for Alembic revision metadata."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "alembic" / "versions"


def _literal_assignment(path: Path, name: str) -> str | None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
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
    referenced = {revision for revision in down_revisions if revision is not None}
    assert referenced <= revision_ids, (
        f"unknown migration parents: {sorted(referenced - revision_ids)}"
    )
    heads = revision_ids - referenced
    assert len(heads) == 1, f"expected one migration head, found {sorted(heads)}"
