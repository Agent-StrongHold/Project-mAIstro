"""Shared learning visibility predicates for memory and SQL stores.

These live in the memory layer rather than `maistro.persistence` on purpose:
the persistence package imports asyncpg eagerly, and the in-memory store must
stay importable in asyncpg-free environments — hive-conductor consumes
maistro-core via sys.path and deliberately restates only the deps its own code
paths need. Persistence already imports memory at module level (`pg_learnings`
uses `maistro.memory.vectors` the same way), so this placement keeps the
dependency arrow pointing the one allowed direction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


def matches_learning_scope(
    learning: object,
    *,
    org_id: str,
    team_id: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> bool:
    """Apply the scope a learning read requests, admitting shared rows.

    ``org_id`` is always bound, including the empty value, so an unscoped read
    cannot become a wildcard. The narrower axes are optional because callers
    that do not have that identity must retain the existing org-wide behavior.

    A requested axis also admits rows whose value on that axis is empty: the
    empty string is the shared-within-org bucket, so narrowing to one agent
    must not hide the learnings the org shares. ``None`` counts as shared too,
    because the PostgreSQL store reads ``agent_id = ''`` back as ``None`` — a
    row must not change visibility by passing through a round trip. ``org_id``
    has no such bucket: ``org_id = ''`` is a scope, not a wildcard.
    """
    if (getattr(learning, "org_id", "") or "") != org_id:
        return False
    for field, requested in (
        ("team_id", team_id),
        ("user_id", user_id),
        ("agent_id", agent_id),
    ):
        if requested:
            owned = getattr(learning, field, "") or ""
            if owned and owned != requested:
                return False
    return True


def learning_scope_predicate(
    *,
    org_id: str,
    team_id: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    placeholders: Iterator[str],
) -> tuple[str, list[str]]:
    """Return the same scope decision as :func:`matches_learning_scope` in SQL."""
    clauses = [f"org_id = {next(placeholders)}"]
    params = [org_id]
    for field, requested in (
        ("team_id", team_id),
        ("user_id", user_id),
        ("agent_id", agent_id),
    ):
        if requested:
            marker = next(placeholders)
            # The shared-bucket widening from matches_learning_scope: a row
            # with an empty value on the requested axis belongs to the whole
            # org, so a scoped read must still see it. org_id above stays
            # exact — there is no global bucket.
            clauses.append(f"({field} = {marker} OR {field} = '')")
            params.append(requested)
    return " AND ".join(clauses), params


__all__ = ["learning_scope_predicate", "matches_learning_scope"]
