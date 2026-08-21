"""Ontology types per `engine#ADR-036`.

The Semantic facet ships in v1.0; Kinetic and Dynamic are reserved.

Kinds are registered with a Pydantic model that validates the
Semantic facet's payload at `upsert` time. UUIDs are version-7
ordered (time-ordered) so naive sorts are roughly chronological.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class Facet(StrEnum):
    """Ontology facets per `engine#ADR-036`.

    - SEMANTIC: what an object *is*. Required for v1.0.
    - KINETIC: what an object *does* (actions w/ pre/post). v2.0.
    - DYNAMIC: how an object *evolves* (transitions, history). v2.0.
    """

    SEMANTIC = "semantic"
    KINETIC = "kinetic"
    DYNAMIC = "dynamic"


class OntologyEntity(BaseModel):
    """A typed semantic object in the four-repo system's ontology.

    The ``kind`` is a stable string slug registered with a Pydantic
    model. ``facets`` is keyed by `Facet`; v1.0 only populates the
    SEMANTIC entry.

    Equality is by ``id`` (UUID); two entities with the same id but
    different revisions or facet contents represent distinct snapshots
    of the same logical object (Dynamic facet, v2.0).
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    kind: str
    revision: int = 1  # bumps on Dynamic facet edits (v2.0)
    facets: dict[Facet, dict[str, Any]] = Field(default_factory=dict)

    def get_semantic(self) -> dict[str, Any]:
        """Return the SEMANTIC facet payload, or {} if unset."""
        return self.facets.get(Facet.SEMANTIC, {})

    def with_semantic(self, data: dict[str, Any]) -> OntologyEntity:
        """Return a copy with the SEMANTIC facet replaced.

        The original is not mutated. Use this rather than direct dict
        mutation so callers can't accidentally desynchronise stored
        entities.
        """
        new_facets = {**self.facets, Facet.SEMANTIC: dict(data)}
        return self.model_copy(update={"facets": new_facets})


class OntologyError(Exception):
    """Base class for ontology errors."""


class KindNotRegisteredError(OntologyError):
    """Raised when querying or upserting an entity of an unregistered kind."""


class KindAlreadyRegisteredError(OntologyError):
    """Raised when re-registering a kind with a non-equivalent model."""
