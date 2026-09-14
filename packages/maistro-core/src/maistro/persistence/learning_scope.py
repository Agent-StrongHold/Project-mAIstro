"""Shared learning visibility predicates for memory and SQL stores."""

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
    """Apply the exact scope requested by a learning read.

    ``org_id`` is always bound, including the empty value, so an unscoped read
    cannot become a wildcard. The narrower axes are optional because callers
    that do not have that identity must retain the existing org-wide behavior.
    """
    if (getattr(learning, "org_id", "") or "") != org_id:
        return False
    for field, requested in (
        ("team_id", team_id),
        ("user_id", user_id),
        ("agent_id", agent_id),
    ):
        if requested and getattr(learning, field, None) != requested:
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
            clauses.append(f"{field} = {next(placeholders)}")
            params.append(requested)
    return " AND ".join(clauses), params


__all__ = ["learning_scope_predicate", "matches_learning_scope"]
