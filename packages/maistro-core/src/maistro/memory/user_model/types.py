"""UserModelFact: a durable, user-owned, revisioned fact about one user (#1047).

Separate from EpisodicMemory on purpose: episodic memory decays, whereas a
user-model fact is only ever revised, put under review, or tombstoned, and each
change is a new revision in its lineage.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4


def _now() -> datetime:
    return datetime.now(UTC)


def new_fact_id() -> str:
    """Mint the id of one revision."""
    return uuid4().hex


class FactState(StrEnum):
    """Lifecycle of one user-model revision."""

    ACTIVE = "active"
    UNDER_REVIEW = "under_review"
    SUPERSEDED = "superseded"
    TOMBSTONED = "tombstoned"


class FactSensitivity(StrEnum):
    """How carefully a fact must be handled when it is recalled."""

    NORMAL = "normal"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"


class UserModelError(Exception):
    """Base class for user-model refusals."""


class PromotionRefusedError(UserModelError):
    """The evidence cannot become a user-model fact."""


class CrossUserPromotionError(PromotionRefusedError, PermissionError):
    """Evidence owned by another user needs SPEC-242 consent, not self-consent."""


class TombstonedLineageError(PromotionRefusedError):
    """The lineage was deleted by its owner and must not be recreated."""


class StaleEvidenceError(PromotionRefusedError):
    """The owner corrected this lineage; old evidence must not revive the old statement."""


class RevisionConflictError(UserModelError):
    """An appended revision does not directly follow the lineage's current one."""


@dataclass(frozen=True)
class EvidenceRef:
    """Where a fact was observed. Identifiers only, never content."""

    workspace_id: str = ""
    project_id: str = ""
    memory_id: str = ""
    run_id: str = ""
    artifact_id: str = ""


@dataclass(frozen=True)
class Correction:
    """Who explicitly revised or deleted a fact, and why."""

    corrected_by: str
    reason: str
    corrected_at: datetime = field(default_factory=_now)


def normalize_statement(statement: str) -> str:
    """Case- and whitespace-insensitive form used for lineage identity."""
    return " ".join(statement.split()).casefold()


def fact_key(owner_user_id: str, statement: str) -> str:
    """Owner-bound statement identity, so re-promoted evidence finds its lineage.

    ``kind`` is deliberately not part of it: a producer relabelling a fact must
    not be able to step around the owner's tombstone.
    """
    raw = "\x1f".join((owner_user_id, normalize_statement(statement)))
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class UserModelFact:
    """One revision of a fact about ``owner_user_id`` (the canonical user id)."""

    lineage_id: str
    revision: int
    supersedes: str | None
    owner_user_id: str
    kind: str
    statement: str
    fact_id: str = field(default_factory=new_fact_id)
    evidence: tuple[EvidenceRef, ...] = ()
    first_observed: datetime = field(default_factory=_now)
    last_observed: datetime = field(default_factory=_now)
    last_reinforced: datetime = field(default_factory=_now)
    confidence: float = 0.5
    state: FactState = FactState.ACTIVE
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    sensitivity: FactSensitivity = FactSensitivity.PERSONAL
    reusable: bool = True
    correction: Correction | None = None
    persona_hints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Reject revisions that could not have come from a valid lineage."""
        if not self.owner_user_id.strip():
            raise ValueError("owner_user_id must be the canonical user id")
        if not self.lineage_id:
            raise ValueError("lineage_id is required")
        if self.revision < 1:
            raise ValueError("revision starts at 1")
        if (self.revision == 1) != (self.supersedes is None):
            raise ValueError("supersedes is set exactly when revision > 1")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0, 1]")
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until <= self.valid_from
        ):
            raise ValueError("valid_until must be after valid_from")
