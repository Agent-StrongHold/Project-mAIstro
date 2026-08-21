"""Skill registry: in-memory CRUD with trust tier tracking.

Manages active skills with registration, lookup, group filtering,
and trust tier enforcement. Mutation history tracked per skill.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maistro.types.skill import SkillDefinition

logger = logging.getLogger("maistro.skills.registry")


class InMemorySkillRegistry:
    """In-memory skill registry.

    Thread-safe via reentrant lock for concurrent requests.
    """

    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}
        self._versions: dict[str, list[SkillDefinition]] = {}
        self._lock = threading.RLock()

    def register(self, skill: SkillDefinition) -> None:
        """Register a skill. Overwrites if name already exists at SAME OR LOWER tier.

        T0 built-in skills cannot be overwritten by marketplace/forge installs.
        """
        key = skill.name
        with self._lock:
            existing = self._skills.get(key)
            if (
                existing
                and existing.trust_tier in ("t0", "t1")
                and skill.trust_tier not in ("t0", "t1")
            ):
                logger.warning(
                    "Blocked: cannot overwrite %s skill '%s' with %s tier",
                    existing.trust_tier,
                    skill.name,
                    skill.trust_tier,
                )
                return
            self._skills[key] = skill
            self._versions.setdefault(key, []).append(skill)
        logger.debug("Registered skill: %s (tier=%s)", skill.name, skill.trust_tier)

    def get(self, name: str) -> SkillDefinition | None:
        """Get a skill by name."""
        return self._skills.get(name)

    def list_all(self) -> list[SkillDefinition]:
        """List all skills."""
        return list(self._skills.values())

    def list_by_group(self, group: str) -> list[SkillDefinition]:
        """List skills matching a group."""
        return [s for s in self.list_all() if group in s.groups]

    def list_by_trust_tier(self, tier: str) -> list[SkillDefinition]:
        """List skills at a specific trust tier."""
        return [s for s in self.list_all() if s.trust_tier == tier]

    def update(self, skill: SkillDefinition) -> bool:
        """Update an existing skill. Returns False if not found."""
        with self._lock:
            if skill.name not in self._skills:
                return False
            self._skills[skill.name] = skill
            return True

    def delete(self, name: str) -> bool:
        """Delete a skill by name. Returns False if not found."""
        with self._lock:
            if name not in self._skills:
                return False
            del self._skills[name]
        logger.debug("Deleted skill: %s", name)
        return True

    def get_versions(self, name: str) -> list[SkillDefinition]:
        """Get all historical versions of a skill (oldest first)."""
        versions = self._versions.get(name)
        if versions:
            return list(versions)
        return []

    def get_version(self, name: str, version_idx: int) -> SkillDefinition | None:
        """Get a specific version by index (0-based)."""
        versions = self.get_versions(name)
        if 0 <= version_idx < len(versions):
            return versions[version_idx]
        return None

    def rollback(self, name: str, version_idx: int) -> bool:
        """Rollback a skill to a previous version. Returns False if version not found."""
        versions = self._versions.get(name)
        if not versions:
            return False

        if version_idx < 0 or version_idx >= len(versions):
            return False

        target = versions[version_idx]
        with self._lock:
            self._skills[name] = target
            versions.append(target)
        logger.info(
            "Rolled back skill '%s' to version %d",
            name,
            version_idx,
        )
        return True

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        return name in self._skills
