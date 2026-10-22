"""Skill mutation store: in-memory implementation.

Tracks when skills are rewritten from promoted learnings.

Ported from Stronghold.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from maistro.memory.exposure import Actor, MemoryExposureMode, require_write_authority

if TYPE_CHECKING:
    from maistro.types.memory import SkillMutation


class InMemorySkillMutationStore:
    """In-memory skill mutation store for testing.

    A skill mutation is written by the promotion pipeline (an agent-loop
    product), so the default actor is `AGENT` and the ADR-057 gate applies:
    under `SYSTEM_MANAGED` an agent-actor record is denied, and an undeclared
    mode refuses every record.
    """

    def __init__(self, exposure_mode: MemoryExposureMode | None = None) -> None:
        self._mutations: list[SkillMutation] = []
        self._next_id = 1
        self._exposure_mode = exposure_mode

    async def record(self, mutation: SkillMutation, *, actor: Actor = Actor.AGENT) -> int:
        """Record a skill mutation. Returns mutation ID.

        The gate is the first statement (ADR-057): a denial raises before the
        list is touched, so denied writes leave no partial state.
        """
        require_write_authority(self._exposure_mode, "write", actor, subject=type(self).__name__)
        mutation.id = self._next_id
        self._next_id += 1
        self._mutations.append(mutation)
        return mutation.id

    async def list_mutations(self, limit: int = 50) -> list[SkillMutation]:
        """List recent mutations."""
        return self._mutations[-limit:]
