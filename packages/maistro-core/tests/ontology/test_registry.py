"""Tests for InMemoryOntology per engine#ADR-036."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from maistro.ontology.protocols import Ontology
from maistro.ontology.registry import InMemoryOntology
from maistro.ontology.types import (
    Facet,
    KindAlreadyRegisteredError,
    KindNotRegisteredError,
    OntologyEntity,
)


class Person(BaseModel):
    name: str
    age: int


class Document(BaseModel):
    title: str
    body: str


@pytest.fixture
def ontology() -> InMemoryOntology:
    return InMemoryOntology()


def test_in_memory_satisfies_protocol(ontology: InMemoryOntology) -> None:
    """Boundary contract: implementation conforms to the Protocol."""
    assert isinstance(ontology, Ontology)


def test_register_and_query(ontology: InMemoryOntology) -> None:
    ontology.register("Person", Person)
    alice = OntologyEntity(kind="Person").with_semantic({"name": "Alice", "age": 30})
    ontology.upsert(alice)

    results = ontology.query("Person")
    assert len(results) == 1
    assert results[0].get_semantic()["name"] == "Alice"


def test_register_idempotent_same_model(ontology: InMemoryOntology) -> None:
    ontology.register("Person", Person)
    ontology.register("Person", Person)

    alice = OntologyEntity(kind="Person").with_semantic({"name": "Alice", "age": 30})
    ontology.upsert(alice)
    assert ontology.get(alice.id) == alice


def test_register_conflicting_model_raises(ontology: InMemoryOntology) -> None:
    ontology.register("Person", Person)
    with pytest.raises(KindAlreadyRegisteredError):
        ontology.register("Person", Document)


def test_query_unregistered_kind_raises(ontology: InMemoryOntology) -> None:
    with pytest.raises(KindNotRegisteredError):
        ontology.query("Nonexistent")


def test_upsert_unregistered_kind_raises(ontology: InMemoryOntology) -> None:
    e = OntologyEntity(kind="Nonexistent")
    with pytest.raises(KindNotRegisteredError):
        ontology.upsert(e)


def test_upsert_invalid_semantic_raises(ontology: InMemoryOntology) -> None:
    ontology.register("Person", Person)
    bad = OntologyEntity(kind="Person").with_semantic({"name": "Alice"})  # missing age
    with pytest.raises(ValidationError):
        ontology.upsert(bad)


def test_get_returns_entity(ontology: InMemoryOntology) -> None:
    ontology.register("Person", Person)
    alice = OntologyEntity(kind="Person").with_semantic({"name": "Alice", "age": 30})
    ontology.upsert(alice)

    got = ontology.get(alice.id)
    assert got is not None
    assert got.id == alice.id
    assert got.get_semantic()["name"] == "Alice"


def test_get_returns_none_for_unknown_id(ontology: InMemoryOntology) -> None:
    assert ontology.get(uuid4()) is None


def test_query_filters_on_semantic_fields(ontology: InMemoryOntology) -> None:
    ontology.register("Person", Person)
    alice = OntologyEntity(kind="Person").with_semantic({"name": "Alice", "age": 30})
    bob = OntologyEntity(kind="Person").with_semantic({"name": "Bob", "age": 25})
    ontology.upsert(alice)
    ontology.upsert(bob)

    young = ontology.query("Person", age=25)
    assert len(young) == 1
    assert young[0].get_semantic()["name"] == "Bob"


def test_query_isolates_kinds(ontology: InMemoryOntology) -> None:
    ontology.register("Person", Person)
    ontology.register("Document", Document)
    alice = OntologyEntity(kind="Person").with_semantic({"name": "Alice", "age": 30})
    doc = OntologyEntity(kind="Document").with_semantic({"title": "T", "body": "B"})
    ontology.upsert(alice)
    ontology.upsert(doc)

    persons = ontology.query("Person")
    assert len(persons) == 1
    assert persons[0].kind == "Person"

    documents = ontology.query("Document")
    assert len(documents) == 1
    assert documents[0].kind == "Document"


def test_upsert_returns_validated_form(ontology: InMemoryOntology) -> None:
    ontology.register("Person", Person)
    alice = OntologyEntity(kind="Person").with_semantic({"name": "Alice", "age": 30})
    stored = ontology.upsert(alice)
    assert stored.get_semantic() == {"name": "Alice", "age": 30}


def test_upsert_overwrites_same_id(ontology: InMemoryOntology) -> None:
    ontology.register("Person", Person)
    e = OntologyEntity(kind="Person").with_semantic({"name": "Alice", "age": 30})
    ontology.upsert(e)

    updated = e.with_semantic({"name": "Alice Updated", "age": 31})
    ontology.upsert(updated)

    persons = ontology.query("Person")
    assert len(persons) == 1
    assert persons[0].get_semantic() == {"name": "Alice Updated", "age": 31}


def test_get_returns_deep_copy(ontology: InMemoryOntology) -> None:
    """Mutating the returned entity should not affect storage."""
    ontology.register("Person", Person)
    alice = OntologyEntity(kind="Person").with_semantic({"name": "Alice", "age": 30})
    ontology.upsert(alice)

    got = ontology.get(alice.id)
    assert got is not None
    got.facets[Facet.SEMANTIC]["name"] = "MUTATED"

    fresh = ontology.get(alice.id)
    assert fresh is not None
    assert fresh.get_semantic()["name"] == "Alice"


def test_query_returns_deep_copy(ontology: InMemoryOntology) -> None:
    """Mutating a query result should not affect storage."""
    ontology.register("Person", Person)
    alice = OntologyEntity(kind="Person").with_semantic({"name": "Alice", "age": 30})
    ontology.upsert(alice)

    results = ontology.query("Person")
    results[0].facets[Facet.SEMANTIC]["name"] = "MUTATED"

    fresh = ontology.query("Person")
    assert fresh[0].get_semantic()["name"] == "Alice"
