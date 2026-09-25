"""Shared learning visibility predicates for memory and SQL stores."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

#: The one optional axis whose empty value widens a read rather than matching
#: nothing. A learning with no ``agent_id`` is the org-wide shared pool every
#: agent-scoped read still sees — the convention both SQL twins shipped with
#: (``(agent_id = ? OR agent_id = '')``) and that the migration-legs suite
#: pins. ``org_id`` is not analogous: it is the security boundary and always
#: exact. ``team_id``/``user_id`` are exact identity axes: an empty value there
#: means "not recorded" (pre-#1156 rows), which must not silently widen a
#: read, because that would republish unknown-provenance rows to every
#: team or user in the org.
AGENT_EMPTY_WIDENS = "agent_id"


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
        if not requested:
            continue
        value = getattr(learning, field, None)
        if field == AGENT_EMPTY_WIDENS:
            # `or ""` keeps memory equivalent to the SQL twins, which store
            # the dataclass's `None` as `''` ("no agent", the shared pool).
            if (value or "") not in (requested, ""):
                return False
        elif value != requested:
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
        if not requested:
            continue
        placeholder = next(placeholders)
        if field == AGENT_EMPTY_WIDENS:
            clauses.append(f"({field} = {placeholder} OR {field} = '')")
        else:
            clauses.append(f"{field} = {placeholder}")
        params.append(requested)
    return " AND ".join(clauses), params


__all__ = ["AGENT_EMPTY_WIDENS", "learning_scope_predicate", "matches_learning_scope"]
