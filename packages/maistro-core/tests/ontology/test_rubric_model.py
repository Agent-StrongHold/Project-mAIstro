"""M7-A2 (#791): the `rubric` ontology kind — model-level contract.

Covers the registered SEMANTIC model for a Goal's scored-acceptance object:
ordered dimensions (id/name/weight/scale/method/evidence), aggregation rule,
pass/fail gate, Goal-revision binding fields, scope fields, and provenance.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from maistro.ontology import (
    RUBRIC_KIND,
    InMemoryOntology,
    NumericScale,
    OntologyEntity,
    PackRubricCatalog,
    RubricAggregation,
    RubricDimension,
    RubricGate,
    RubricProvenance,
    RubricScale,
    RubricSemantic,
    register_rubric_kind,
    rubric_entity_id,
)


def dimension(dim_id: str = "accuracy", weight: float = 1.0) -> RubricDimension:
    return RubricDimension(
        id=dim_id,
        name="Accuracy",
        weight=weight,
        scale=RubricScale(numeric=NumericScale(min_value=0.0, max_value=100.0)),
        method="deterministic",
        evidence_required=False,
    )


def semantic(**overrides: object) -> RubricSemantic:
    base: dict[str, object] = {
        "rubric_id": "rubric-1",
        "revision": 1,
        "goal_id": "goal-1",
        "goal_revision": 3,
        "workspace_id": "w1",
        "project_id": "p1",
        "dimensions": [dimension()],
        "gate": RubricGate(pass_threshold=80.0),
        "provenance": RubricProvenance(authored_by="user-1"),
    }
    base.update(overrides)
    return RubricSemantic.model_validate(base)


def test_rubric_kind_registers_and_upserts() -> None:
    """Acceptance: Rubric is a registered ontology kind with a Pydantic model."""
    ontology = InMemoryOntology()
    register_rubric_kind(ontology)

    entity = OntologyEntity(id=rubric_entity_id("rubric-1", 1), kind=RUBRIC_KIND).with_semantic(
        semantic().model_dump(mode="json")
    )
    stored = ontology.upsert(entity)

    assert stored.kind == RUBRIC_KIND
    found = ontology.query(RUBRIC_KIND, rubric_id="rubric-1")
    assert len(found) == 1
    assert RubricSemantic.model_validate(found[0].get_semantic()).goal_revision == 3


def test_rubric_registration_is_idempotent_same_model() -> None:
    ontology = InMemoryOntology()
    register_rubric_kind(ontology)
    register_rubric_kind(ontology)  # no KindAlreadyRegisteredError


def test_entity_id_is_deterministic_per_revision() -> None:
    """(rubric_id, revision) pins one entity: revisions are immutable snapshots."""
    assert rubric_entity_id("rubric-1", 1) == rubric_entity_id("rubric-1", 1)
    assert rubric_entity_id("rubric-1", 1) != rubric_entity_id("rubric-1", 2)
    assert rubric_entity_id("rubric-2", 1) != rubric_entity_id("rubric-1", 1)


def test_scale_requires_numeric_or_pass_fail() -> None:
    with pytest.raises(ValidationError, match="numeric scale, a pass/fail scale, or both"):
        RubricScale()
    with pytest.raises(ValidationError, match="numeric scale, a pass/fail scale, or both"):
        RubricScale(numeric=None, pass_fail=None)
    # numeric and/or pass-fail: each alone is fine, both together too.
    RubricScale(numeric=NumericScale(min_value=0.0, max_value=100.0))
    RubricScale(pass_fail={"pass_value": 1.0, "fail_value": 0.0})
    RubricScale(numeric=NumericScale(min_value=0.0, max_value=5.0), pass_fail={"pass_value": 1.0})


def test_numeric_scale_must_be_ordered() -> None:
    with pytest.raises(ValidationError, match="min_value < max_value"):
        NumericScale(min_value=100.0, max_value=0.0)


def test_dimension_weight_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        RubricDimension(
            id="d",
            name="D",
            weight=0.0,
            scale=RubricScale(numeric=NumericScale()),
            method="deterministic",
        )


def test_dimension_scale_is_required() -> None:
    with pytest.raises(ValidationError):
        RubricDimension(id="d", name="D", weight=1.0, scale=None, method="human")  # type: ignore[arg-type]


def test_dimension_methods_are_enumerated() -> None:
    for method in ("deterministic", "model_judge", "human"):
        RubricDimension(
            id="d",
            name="D",
            weight=1.0,
            scale=RubricScale(numeric=NumericScale()),
            method=method,
        )
    with pytest.raises(ValidationError):
        RubricDimension(
            id="d",
            name="D",
            weight=1.0,
            scale=RubricScale(numeric=NumericScale()),
            method="vibes",  # type: ignore[arg-type]
        )


def test_dimensions_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        semantic(dimensions=[])


def test_dimension_ids_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="dimension ids must be unique"):
        semantic(dimensions=[dimension("a"), dimension("a")])


def test_veto_ids_must_reference_dimensions() -> None:
    with pytest.raises(ValidationError, match="veto dimension 'nope'"):
        semantic(
            dimensions=[dimension("a")],
            aggregation=RubricAggregation(veto_dimension_ids=["nope"]),
        )
    ok = semantic(
        dimensions=[dimension("a"), dimension("b", weight=2.0)],
        aggregation=RubricAggregation(veto_dimension_ids=["b"]),
    )
    assert ok.aggregation.veto_dimension_ids == ["b"]


def test_gate_threshold_is_bounded() -> None:
    RubricGate(pass_threshold=0.0)
    RubricGate(pass_threshold=100.0)
    with pytest.raises(ValidationError):
        RubricGate(pass_threshold=100.5)
    with pytest.raises(ValidationError):
        RubricGate(pass_threshold=-1.0)


def test_binding_and_scope_fields_are_required() -> None:
    """A Rubric revision records goal binding + Project scope, or it is not a Rubric."""
    for missing in ("goal_id", "goal_revision", "workspace_id", "project_id", "rubric_id"):
        payload = semantic().model_dump()
        del payload[missing]
        with pytest.raises(ValidationError):
            RubricSemantic.model_validate(payload)


def test_pack_provenance_requires_pack_id() -> None:
    with pytest.raises(ValidationError, match="pack-origin provenance requires pack_id"):
        RubricProvenance(authored_by="user-1", origin="pack", pack_id=None)
    proven = RubricProvenance(authored_by="user-1", origin="pack", pack_id="pack-9")
    assert proven.pack_id == "pack-9"


def test_extra_fields_are_forbidden() -> None:
    payload = semantic().model_dump()
    payload["score"] = 42  # a Rubric records the acceptance contract; it is never a score
    with pytest.raises(ValidationError):
        RubricSemantic.model_validate(payload)


def test_pack_catalog_is_supply_side_only() -> None:
    """Packs may supply default dimension catalogs; they never own Rubric identity."""
    catalog = PackRubricCatalog(
        pack_id="pack-9",
        name="Defaults",
        dimensions=[dimension("a"), dimension("b", weight=2.0)],
        gate=RubricGate(pass_threshold=70.0),
    )
    assert not hasattr(catalog, "rubric_id")  # no identity field to own
    assert catalog.pack_id == "pack-9"
