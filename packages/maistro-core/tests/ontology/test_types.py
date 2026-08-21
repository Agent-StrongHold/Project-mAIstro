"""Tests for ontology types per engine#ADR-036."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from maistro.ontology.types import Facet, OntologyEntity


def test_entity_default_id_is_uuid() -> None:
    e = OntologyEntity(kind="Person")
    assert isinstance(e.id, UUID)


def test_entity_two_default_ids_differ() -> None:
    a = OntologyEntity(kind="Person")
    b = OntologyEntity(kind="Person")
    assert a.id != b.id


def test_entity_default_revision_is_1() -> None:
    e = OntologyEntity(kind="Person")
    assert e.revision == 1


def test_entity_default_facets_is_empty() -> None:
    e = OntologyEntity(kind="Person")
    assert e.facets == {}
    assert e.get_semantic() == {}


def test_entity_with_semantic_returns_copy() -> None:
    e = OntologyEntity(kind="Person")
    e2 = e.with_semantic({"name": "Alice", "age": 30})
    assert e.id == e2.id  # same logical entity
    assert e2.facets[Facet.SEMANTIC] == {"name": "Alice", "age": 30}
    assert e.facets == {}  # original untouched


def test_with_semantic_does_not_mutate_input() -> None:
    """Passing a dict to with_semantic should not let later mutations leak."""
    payload = {"name": "Alice", "age": 30}
    e = OntologyEntity(kind="Person").with_semantic(payload)
    payload["name"] = "Mallory"
    assert e.facets[Facet.SEMANTIC]["name"] == "Alice"


def test_with_semantic_replaces_existing_semantic() -> None:
    e1 = OntologyEntity(kind="Person").with_semantic({"name": "Alice", "age": 30})
    e2 = e1.with_semantic({"name": "Bob", "age": 25})
    assert e2.get_semantic() == {"name": "Bob", "age": 25}


def test_entity_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        OntologyEntity(kind="Person", unknown_field="value")  # type: ignore[call-arg]


def test_facet_enum_has_three_values() -> None:
    assert Facet.SEMANTIC.value == "semantic"
    assert Facet.KINETIC.value == "kinetic"
    assert Facet.DYNAMIC.value == "dynamic"


def test_facet_enum_is_string() -> None:
    """Facet inherits from str so dict serialization works cleanly."""
    assert isinstance(Facet.SEMANTIC, str)
    assert Facet.SEMANTIC == "semantic"
