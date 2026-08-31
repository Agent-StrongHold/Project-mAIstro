"""Memory scope filtering for retrieval queries (ADR-013).

The rule lives here once and is compiled into two languages: `matches_scope`
decides in Python, `scope_predicate` returns the same decision as SQL. A
durable store that re-typed the clauses would be a second spelling of a
visibility rule -- and two of these clauses exist specifically to stop
cross-org leakage, so a drift between the spellings is a leak (ADR-083026-a322).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from maistro.memory.types import EpisodicMemory, MemoryScope

if TYPE_CHECKING:
    from collections.abc import Iterator


def build_scope_filter(
    agent_id: str | None = None,
    user_id: str | None = None,
    team_id: str | None = None,
    org_id: str | None = None,
) -> list[tuple[str, str | None]]:
    """Build scope filter list for memory retrieval (OR semantics)."""
    filters: list[tuple[str, str | None]] = [(MemoryScope.GLOBAL, None)]
    if org_id:
        filters.append((MemoryScope.ORGANIZATION, org_id))
    if team_id:
        filters.append((MemoryScope.TEAM, team_id))
    if user_id:
        filters.append((MemoryScope.USER, user_id))
    if agent_id:
        filters.append((MemoryScope.AGENT, agent_id))
    return filters


def matches_scope(
    mem: EpisodicMemory,
    filters: list[tuple[str, str | None]],
) -> bool:
    """Check if a memory matches any scope filter.

    TEAM scope requires BOTH team_id AND org_id to prevent cross-org leakage.
    GLOBAL memories with an org_id are only visible to the same org.
    """
    caller_org = next(
        (value for scope, value in filters if scope == MemoryScope.ORGANIZATION and value),
        "",
    )

    for scope, value in filters:
        if scope == MemoryScope.GLOBAL and mem.scope == MemoryScope.GLOBAL:
            if mem.org_id and caller_org and mem.org_id != caller_org:
                continue
            return True
        if mem.scope != scope:
            continue
        if scope == MemoryScope.ORGANIZATION and mem.org_id == value:
            return True
        if scope == MemoryScope.TEAM and mem.team_id == value and mem.org_id == caller_org:
            return True
        if scope == MemoryScope.USER and mem.user_id == value:
            return True
        if scope == MemoryScope.AGENT and mem.agent_id == value:
            return True

    return False


#: The column each narrow scope compares against, for the scopes whose SQL
#: clause is a single equality. `global` and `team` are not here: both carry an
#: extra org condition, which is the whole point of them.
_SCOPE_COLUMN: dict[str, str] = {
    MemoryScope.ORGANIZATION: "org_id",
    MemoryScope.USER: "user_id",
    MemoryScope.AGENT: "agent_id",
}

#: Scopes `scope_predicate` can express. `matches_scope` has no branch for any
#: other -- a `session`-scoped memory matches nothing there -- so a scope
#: missing here must contribute no clause rather than raise, or the two
#: spellings would disagree on the corpus that contains one.
_EXPRESSIBLE: frozenset[str] = frozenset({MemoryScope.TEAM, *_SCOPE_COLUMN})


def _clause(
    scope: str,
    value: str | None,
    *,
    caller_org: str,
    placeholders: Iterator[str],
    params: list[str],
) -> str:
    """One scope filter as SQL, appending its parameters to `params`.

    Every value reaches the statement as a bound parameter; the only text this
    builds is column names and the literal scope names, both from this module.
    """
    if scope == MemoryScope.GLOBAL:
        # `matches_scope`: a global memory carrying an org_id is visible only to
        # that org. With no caller org there is nothing to compare against, so
        # every global memory is visible -- which is what the Python rule does
        # when `caller_org` is empty.
        if not caller_org:
            return "(scope = 'global')"
        params.append(caller_org)
        return f"(scope = 'global' AND (org_id = '' OR org_id = {next(placeholders)}))"
    if scope == MemoryScope.TEAM:
        params.append(value or "")
        team = next(placeholders)
        params.append(caller_org)
        return f"(scope = 'team' AND team_id = {team} AND org_id = {next(placeholders)})"
    params.append(value or "")
    return f"(scope = '{scope}' AND {_SCOPE_COLUMN[scope]} = {next(placeholders)})"


def scope_predicate(
    filters: list[tuple[str, str | None]],
    placeholders: Iterator[str],
) -> tuple[str, list[str]]:
    """`matches_scope` as a SQL boolean expression, plus its bound parameters.

    `placeholders` yields the parameter markers of the caller's driver -- `$2`,
    `$3`, ... for asyncpg, an endless `?` for SQLite -- so the one rule serves
    both without a dialect flag.

    Returns the predicate and the parameters in the order the placeholders were
    drawn. The predicate is never empty: `build_scope_filter` always includes
    the global scope.
    """
    caller_org = next(
        (value for scope, value in filters if scope == MemoryScope.ORGANIZATION and value),
        "",
    )
    params: list[str] = []
    clauses = [
        _clause(scope, value, caller_org=caller_org, placeholders=placeholders, params=params)
        for scope, value in filters
        if scope == MemoryScope.GLOBAL or (value and scope in _EXPRESSIBLE)
    ]
    return " OR ".join(clauses), params
