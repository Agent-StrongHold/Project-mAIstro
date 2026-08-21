"""Ontology layer per [`engine#ADR-036`](../../../../docs/adr/ADR-036-ontology-semantic-object-layer.md).

v1.0 ships the **Semantic** facet only — typed entities backed by Pydantic
for validation, queryable by kind + filters. Kinetic and Dynamic facets
are deferred to v2.0 (see `[engine-070]`, `[engine-071]` in BACKLOG).

Public surface:

- ``OntologyEntity`` — the typed entity (id + kind + revision + facets).
- ``Ontology`` — Protocol every implementation must satisfy.
- ``InMemoryOntology`` — in-process implementation; suitable for tests
  and engine boot. SQLAlchemy-backed implementation lands in a follow-up
  on this branch.

Usage:

.. code-block:: python

    from maistro.ontology import InMemoryOntology, OntologyEntity
    from pydantic import BaseModel

    class Person(BaseModel):
        name: str
        age: int

    ontology = InMemoryOntology()
    ontology.register("Person", Person)
    alice = OntologyEntity(kind="Person").with_semantic(
        {"name": "Alice", "age": 30}
    )
    ontology.upsert(alice)
    found = ontology.query("Person", age=30)
"""

from maistro.ontology.protocols import Ontology
from maistro.ontology.registry import InMemoryOntology
from maistro.ontology.types import (
    Facet,
    KindAlreadyRegisteredError,
    KindNotRegisteredError,
    OntologyEntity,
    OntologyError,
)

__all__ = [
    "Facet",
    "InMemoryOntology",
    "KindAlreadyRegisteredError",
    "KindNotRegisteredError",
    "Ontology",
    "OntologyEntity",
    "OntologyError",
]
