"""`Ontology` Protocol per `engine#ADR-036`.

Implementations:

- ``InMemoryOntology`` (this package) — for tests and engine boot.
- ``PostgresOntology`` (deferred) — SQLAlchemy + pgvector for production.

The Protocol is `runtime_checkable` for adapter-style integration with
the DI container.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel

from maistro.ontology.types import OntologyEntity


@runtime_checkable
class Ontology(Protocol):
    """Canonical ontology API.

    All implementations validate the SEMANTIC facet against the kind's
    registered Pydantic model at upsert time. Read-after-write returns
    the validated form (so callers can rely on coerced types).
    """

    def register(self, kind: str, semantic: type[BaseModel]) -> None:
        """Register a kind with its SEMANTIC-facet Pydantic model.

        Idempotent: re-registering the same kind with the *same* model
        is a no-op. Re-registering with a different model raises
        ``KindAlreadyRegisteredError``.
        """
        ...

    def get(self, entity_id: UUID) -> OntologyEntity | None:
        """Return the entity by id, or ``None`` if absent.

        Returns a deep-copy so caller mutations don't leak back into
        storage.
        """
        ...

    def query(self, kind: str, **filters: object) -> list[OntologyEntity]:
        """Return all entities of ``kind`` matching ``filters``.

        Filters apply to fields of the SEMANTIC facet payload. Read-
        consistent within a single call.

        Raises ``KindNotRegisteredError`` if ``kind`` is unknown.
        """
        ...

    def upsert(self, entity: OntologyEntity) -> OntologyEntity:
        """Insert or update an entity.

        Validates that ``entity.kind`` is registered and that
        ``entity.facets[Facet.SEMANTIC]`` validates against the
        registered Pydantic model. Returns the persisted (validated)
        form.

        Raises ``KindNotRegisteredError`` if ``entity.kind`` is unknown.
        Raises Pydantic ``ValidationError`` for invalid SEMANTIC payload.
        """
        ...
