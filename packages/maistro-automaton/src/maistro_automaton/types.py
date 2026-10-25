"""Value types for autonomous-actor machinery.

Host-agnostic by construction: nothing here knows what a Workspace, a merge
queue, or a persona is. A host maps its own state (facet scores, mood, queue
pressure) into these shapes and gets deterministic, testable machinery back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DriveTermKind(StrEnum):
    FACET = "facet"
    MOOD = "mood"


@dataclass(frozen=True)
class DriveTerm:
    """One additive contribution to a drive level.

    ``source`` names a facet key (slow-moving personality state, normalized
    against ``facet_scale``) or a mood attribute (fast-moving affective state)
    depending on ``kind``. Weights are the host's personality — the machinery
    only sums and clamps.
    """

    source: str
    weight: float
    kind: DriveTermKind = DriveTermKind.FACET


@dataclass(frozen=True)
class DriveSpec:
    """Declaration of one drive: name plus additive terms.

    Drives are computed as ``sum(term.weight * normalized(source))`` clamped
    to ``ceiling``. Facets are divided by ``facet_scale`` (HEXACO-style
    ratings live on a 1-5 scale); mood attributes are used as-is and should
    already live in [0, 1] or [-1, 1] per the host's mood contract.
    """

    name: str
    terms: tuple[DriveTerm, ...]
    ceiling: float = 1.0


@dataclass(frozen=True)
class Candidate:
    """One thing an actor might do, submitted by a producer.

    ``key`` identifies the *action class* (e.g. ``"enqueue:pr-1495"``) and is
    what the arbiter's refractory period keys on. ``payload`` is opaque to the
    machinery — the host's dispatch layer interprets it.
    """

    key: str
    producer: str
    drive: str
    drive_score: float
    payload: Any = None
    created_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True)
class Episode:
    """A durable record of something the actor did or observed.

    The write-through memory that makes an actor persistent: every fired
    action, every refused attempt, every observed outcome is an Episode the
    host sinks into its own durability layer. The machinery never stores —
    it hands Episodes to an :class:`~maistro_automaton.memory.EpisodeSink`.
    """

    content: str
    tier: str
    source: str
    weight: float
    intent: str
    created_at: datetime = field(default_factory=_utc_now)
    ref: str | None = None


VerdictCode: type = str
"""Enumerated refusal/admission reason codes live with the host cage; the
machinery only requires that a verdict's ``reason_code`` is a stable string
a ticket system can group on. Raw exception text is not a reason code."""
