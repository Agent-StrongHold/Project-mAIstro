"""Skill registry: in-memory CRUD with trust tier tracking.

Manages active skills with registration, lookup, group filtering,
and trust tier enforcement. Mutation history tracked per skill.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maistro.types.skill import SkillDefinition

logger = logging.getLogger("maistro.skills.registry")

# Lower numeric tiers are more trusted. An incoming mutation can never retain
# the old approval/tier: its content must earn trust again.
_TIER_RANK = {"t0": 0, "t1": 1, "t2": 2, "t3": 3}
_FLOOR_TIER = "t3"


@dataclass(frozen=True)
class SkillTrustMetadata:
    trust_tier: str
    approved: bool
    provenance: str
    content_hash: str


def _content_hash(skill: SkillDefinition) -> str:
    payload = "\x00".join(
        (skill.name, skill.description, "\n".join(skill.groups), skill.system_prompt)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class InMemorySkillRegistry:
    """In-memory skill registry.

    Thread-safe via reentrant lock for concurrent requests.
    """

    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}
        self._versions: dict[str, list[SkillDefinition]] = {}
        self._trust: dict[str, SkillTrustMetadata] = {}
        self._lock = threading.RLock()

    def register(
        self,
        skill: SkillDefinition,
        *,
        content_hash: str = "",
        provenance: str = "",
        approved: bool | None = None,
    ) -> bool:
        """Register a skill without allowing trust or approval escalation.

        ``trust_tier`` on an incoming definition is only an admission hint. The
        registry owns the effective record and retains approval for identical
        content, while every changed body returns to the untrusted floor.
        """
        key = skill.name
        incoming_hash = content_hash or skill.content_hash or _content_hash(skill)
        incoming_provenance = provenance or skill.provenance or skill.source or "unknown"
        with self._lock:
            existing = self._skills.get(key)
            prior = self._trust.get(key)
            if existing is not None and prior is not None:
                incoming_rank = _TIER_RANK.get(skill.trust_tier, len(_TIER_RANK))
                prior_rank = _TIER_RANK.get(prior.trust_tier, len(_TIER_RANK))
                if incoming_rank < prior_rank or (prior_rank <= 1 and incoming_rank > prior_rank):
                    logger.warning("Blocked non-monotonic trust change for skill '%s'", key)
                    return False
                if incoming_hash == prior.content_hash:
                    effective = prior
                else:
                    effective = SkillTrustMetadata(
                        trust_tier=_FLOOR_TIER,
                        approved=False,
                        provenance=incoming_provenance,
                        content_hash=incoming_hash,
                    )
            else:
                effective = SkillTrustMetadata(
                    trust_tier=skill.trust_tier if skill.trust_tier in _TIER_RANK else _FLOOR_TIER,
                    approved=bool(approved) if approved is not None else False,
                    provenance=incoming_provenance,
                    content_hash=incoming_hash,
                )
            stored = (
                skill
                if not skill.content_hash
                and not skill.provenance
                and effective.trust_tier == skill.trust_tier
                else replace(
                    skill,
                    trust_tier=effective.trust_tier,
                    content_hash=effective.content_hash,
                    provenance=effective.provenance,
                )
            )
            self._skills[key] = stored
            self._trust[key] = effective
            self._versions.setdefault(key, []).append(stored)
        logger.debug("Registered skill: %s (tier=%s)", key, effective.trust_tier)
        return True

    def trust_metadata(self, name: str) -> SkillTrustMetadata | None:
        """Return host-owned trust facts, never the source's claims."""
        with self._lock:
            return self._trust.get(name)

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
        """Update through the same monotonic admission path as registration."""
        with self._lock:
            if skill.name not in self._skills:
                return False
        with self._lock:
            prior_hash = self._trust[skill.name].content_hash
        accepted = self.register(skill)
        # Preserve the legacy object-identity contract for an unchanged body;
        # changed CRUD content must expose the downgraded host record.
        if accepted and _content_hash(skill) == prior_hash and not skill.content_hash:
            with self._lock:
                self._skills[skill.name] = skill
        return accepted

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
            current = self._trust.get(name)
            if current is not None and current.content_hash != self._trust_for(target).content_hash:
                # Rollback is a content change and therefore cannot restore an
                # approval that belonged to a different body.
                target = replace(target, trust_tier=_FLOOR_TIER, content_hash="")
        self.register(target, provenance="rollback")
        logger.info(
            "Rolled back skill '%s' to version %d",
            name,
            version_idx,
        )
        return True

    def _trust_for(self, skill: SkillDefinition) -> SkillTrustMetadata:
        return self._trust.get(
            skill.name,
            SkillTrustMetadata(
                trust_tier=skill.trust_tier,
                approved=False,
                provenance=skill.source or "unknown",
                content_hash=skill.content_hash or _content_hash(skill),
            ),
        )

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        return name in self._skills
