"""GoldenRecord — versioned research ground truth per persona (SPEC-192 Stage 2).

Research outputs (exemplar sources + vocabulary-mapped criteria) are stored as
versioned records. Re-research never overwrites: a new version supersedes the
previous one, and :func:`diff_records` surfaces added/removed/changed criteria
for human sign-off before the Tier 1 floor is replaced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "EvidencedCriterion",
    "GoldenRecord",
    "GoldenRecordDiff",
    "GoldenRecordStore",
    "InMemoryGoldenRecordStore",
    "SourceEvidence",
    "diff_records",
    "record_research",
    "signoff_report",
]


@dataclass(frozen=True)
class SourceEvidence:
    """One fetched exemplar source."""

    url: str
    title: str
    full_text: str
    fetch_ts: datetime


@dataclass(frozen=True)
class EvidencedCriterion:
    """One vocabulary-mapped criterion plus the sources supporting it."""

    name: str
    weight: int
    check: dict[str, Any]  # vocabulary check-spec
    evidence: list[str] = field(default_factory=list)  # supporting source URLs
    needs_review: bool = False  # True when mapped to a `registered` escape hatch


@dataclass(frozen=True)
class GoldenRecord:
    """Versioned golden-truth record for one persona."""

    persona_id: str
    version: int  # increments on re-research
    sources: list[SourceEvidence]
    criteria: list[EvidencedCriterion]
    created_at: datetime
    supersedes: int | None = None  # previous version (never deleted)


@dataclass(frozen=True)
class GoldenRecordDiff:
    """Criteria changes between two GoldenRecord versions (for human sign-off)."""

    persona_id: str
    old_version: int | None
    new_version: int
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)  # same name, different weight/check

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed)


def diff_records(old: GoldenRecord | None, new: GoldenRecord) -> GoldenRecordDiff:
    """Diff two golden records by criterion name, weight, and check spec."""
    old_by_name = {c.name: c for c in old.criteria} if old else {}
    new_by_name = {c.name: c for c in new.criteria}
    added = sorted(set(new_by_name) - set(old_by_name))
    removed = sorted(set(old_by_name) - set(new_by_name))
    changed = sorted(
        name
        for name in set(old_by_name) & set(new_by_name)
        if (old_by_name[name].weight, old_by_name[name].check)
        != (new_by_name[name].weight, new_by_name[name].check)
    )
    return GoldenRecordDiff(
        persona_id=new.persona_id,
        old_version=old.version if old else None,
        new_version=new.version,
        added=added,
        removed=removed,
        changed=changed,
    )


@runtime_checkable
class GoldenRecordStore(Protocol):
    """Store protocol for versioned golden records (versions are never deleted)."""

    async def save(
        self,
        persona_id: str,
        sources: list[SourceEvidence],
        criteria: list[EvidencedCriterion],
    ) -> GoldenRecord:
        """Persist a new version superseding (not replacing) the latest one."""
        ...

    async def get_latest(self, persona_id: str) -> GoldenRecord | None: ...

    async def get_version(self, persona_id: str, version: int) -> GoldenRecord | None: ...

    async def list_versions(self, persona_id: str) -> list[int]: ...


class InMemoryGoldenRecordStore:
    """In-memory GoldenRecordStore (P1 reference implementation)."""

    def __init__(self) -> None:
        self._records: dict[str, dict[int, GoldenRecord]] = {}

    async def save(
        self,
        persona_id: str,
        sources: list[SourceEvidence],
        criteria: list[EvidencedCriterion],
    ) -> GoldenRecord:
        versions = self._records.setdefault(persona_id, {})
        latest = max(versions) if versions else None
        record = GoldenRecord(
            persona_id=persona_id,
            version=(latest or 0) + 1,
            sources=list(sources),
            criteria=list(criteria),
            created_at=datetime.now(UTC),
            supersedes=latest,
        )
        versions[record.version] = record
        return record

    async def get_latest(self, persona_id: str) -> GoldenRecord | None:
        versions = self._records.get(persona_id)
        if not versions:
            return None
        return versions[max(versions)]

    async def get_version(self, persona_id: str, version: int) -> GoldenRecord | None:
        return self._records.get(persona_id, {}).get(version)

    async def list_versions(self, persona_id: str) -> list[int]:
        return sorted(self._records.get(persona_id, {}))


async def record_research(
    store: GoldenRecordStore,
    persona_id: str,
    sources: list[SourceEvidence],
    criteria: list[EvidencedCriterion],
) -> tuple[GoldenRecord, GoldenRecordDiff]:
    """Persist a new research version and diff it against the previous latest.

    The returned diff is the human sign-off artifact: nothing replaces the
    Tier 1 floor until the added/removed/changed criteria are approved.
    """
    previous = await store.get_latest(persona_id)
    record = await store.save(persona_id, sources, criteria)
    return record, diff_records(previous, record)


async def signoff_report(store: GoldenRecordStore, persona_id: str) -> dict[str, Any]:
    """Admin-readable sign-off summary for a persona's latest golden record.

    Includes the full version history, evidence provenance, criteria mapped
    through the ``registered`` escape hatch (``needs_review``), and the diff
    against the superseded version.
    """
    versions = await store.list_versions(persona_id)
    latest = await store.get_latest(persona_id)
    if latest is None:
        return {"persona_id": persona_id, "versions": versions, "latest": None}
    previous = (
        await store.get_version(persona_id, latest.supersedes)
        if latest.supersedes is not None
        else None
    )
    diff = diff_records(previous, latest)
    return {
        "persona_id": persona_id,
        "versions": versions,
        "latest": latest.version,
        "sources": [
            {
                "url": source.url,
                "title": source.title,
                "fetched_at": source.fetch_ts.isoformat(),
                "chars": len(source.full_text),
            }
            for source in latest.sources
        ],
        "needs_review": [c.name for c in latest.criteria if c.needs_review],
        "has_changes": diff.has_changes,
        "added": diff.added,
        "removed": diff.removed,
        "changed": diff.changed,
    }
