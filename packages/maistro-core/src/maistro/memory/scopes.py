"""Memory scope filtering for retrieval queries (ADR-013)."""

from __future__ import annotations

from maistro.memory.types import EpisodicMemory, MemoryScope


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
