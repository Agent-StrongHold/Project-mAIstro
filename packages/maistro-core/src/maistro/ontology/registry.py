"""In-memory ``Ontology`` implementation.

Intended for tests and engine boot. Production uses
``PostgresOntology`` (deferred to a follow-up commit on this branch).

Thread-safety: not thread-safe. Wrap with a lock or use the Postgres
implementation for concurrent access.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from maistro.ontology.types import (
    Facet,
    KindAlreadyRegisteredError,
    KindNotRegisteredError,
    OntologyEntity,
)


class InMemoryOntology:
    """Ontology implementation backed by Python dicts."""

    def __init__(self) -> None:
        self._kinds: dict[str, type[BaseModel]] = {}
        self._entities: dict[UUID, OntologyEntity] = {}

    def register(self, kind: str, semantic: type[BaseModel]) -> None:
        existing = self._kinds.get(kind)
        if existing is not None and existing is not semantic:
            raise KindAlreadyRegisteredError(
                f"kind {kind!r} already registered with a different model "
                f"({existing.__name__!r}); refusing to overwrite with "
                f"{semantic.__name__!r}"
            )
        self._kinds[kind] = semantic

    def get(self, entity_id: UUID) -> OntologyEntity | None:
        ent = self._entities.get(entity_id)
        return deepcopy(ent) if ent is not None else None

    def query(self, kind: str, **filters: Any) -> list[OntologyEntity]:
        if kind not in self._kinds:
            raise KindNotRegisteredError(f"kind {kind!r} not registered")

        results: list[OntologyEntity] = []
        for ent in self._entities.values():
            if ent.kind != kind:
                continue
            semantic = ent.facets.get(Facet.SEMANTIC, {})
            if all(semantic.get(k) == v for k, v in filters.items()):
                results.append(deepcopy(ent))
        return results

    def upsert(self, entity: OntologyEntity) -> OntologyEntity:
        if entity.kind not in self._kinds:
            raise KindNotRegisteredError(f"kind {entity.kind!r} not registered")

        # Validate SEMANTIC facet against registered model. This raises
        # Pydantic ValidationError on bad data, which propagates to the
        # caller per ADR-032 boundary contracts.
        model_cls = self._kinds[entity.kind]
        validated = model_cls.model_validate(entity.get_semantic())
        stored = entity.with_semantic(validated.model_dump())

        self._entities[stored.id] = stored
        return deepcopy(stored)
