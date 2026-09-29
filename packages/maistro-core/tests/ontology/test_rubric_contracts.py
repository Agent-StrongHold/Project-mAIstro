"""M7-A2 (#791): type/kind contract tests separating neighboring "rubric"-ish
and "acceptance"-ish surfaces from the Goal `Rubric` ontology kind.

- `maistro.personas.rubric.RubricEval` scores persona/department template
  evals. It stays exactly as it is and is never the Goal Rubric.
- A CreativeBrief (#774) holds creative success/acceptance *interpretation*.
  That is guidance prose, not a scored object, and is not accepted as a
  Rubric.
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import BaseModel, ValidationError

from maistro.ontology import (
    RUBRIC_KIND,
    InMemoryOntology,
    NumericScale,
    OntologyEntity,
    RubricDimension,
    RubricGate,
    RubricProvenance,
    RubricScale,
    RubricSemantic,
)
from maistro.ontology.rubric import register_rubric_kind
from maistro.personas.rubric import EvalResult, RubricEval


def goal_dimension() -> RubricDimension:
    return RubricDimension(
        id="accuracy",
        name="Accuracy",
        weight=1.0,
        scale=RubricScale(numeric=NumericScale(min_value=0.0, max_value=100.0)),
        method="deterministic",
    )


def goal_rubric_payload() -> dict[str, object]:
    return {
        "rubric_id": "rubric-1",
        "revision": 1,
        "goal_id": "goal-1",
        "goal_revision": 1,
        "workspace_id": "ws-1",
        "project_id": "proj-1",
        "dimensions": [goal_dimension().model_dump()],
        "gate": {"pass_threshold": 80.0},
        "provenance": {"authored_by": "user-1"},
    }


# -- Persona RubricEval vs Goal Rubric ---------------------------------------


def test_persona_scorer_cannot_take_over_the_goal_rubric_kind() -> None:
    """Acceptance: Persona RubricEval and Goal Rubric are different types/kinds.
    The kind is bound to RubricSemantic; registering the persona scorer for the
    same kind is a conflict, and RubricEval is not a Pydantic semantic model."""
    ontology = InMemoryOntology()
    register_rubric_kind(ontology)
    with pytest.raises(Exception, match="already registered"):
        ontology.register(RUBRIC_KIND, RubricEval)  # type: ignore[arg-type]
    assert not issubclass(RubricEval, BaseModel)


def test_persona_rubric_eval_payload_is_not_a_rubric_semantic() -> None:
    """A RubricEval's shape (department/eval_name/tier/criteria vocabulary) is
    not a Goal-bound SEMANTIC payload: no goal binding, scale, gate, provenance."""
    with pytest.raises(ValidationError):
        RubricSemantic.model_validate(
            {
                "department": "pm",
                "eval_name": "structure",
                "tier": 1,
                "criteria": [
                    {"name": "c", "weight": 2, "check": {"type": "contains", "value": "x"}}
                ],
            }
        )


def test_goal_rubric_is_not_a_persona_scorer() -> None:
    """The Goal Rubric records an acceptance contract: no score(), no department
    or criteria vocabulary, so it cannot stand in for RubricEval."""
    semantic = RubricSemantic.model_validate(goal_rubric_payload())
    assert not hasattr(semantic, "score")
    assert not hasattr(semantic, "department")
    assert not hasattr(semantic, "criteria")
    # And the persona scorer has no Goal binding surface.
    assert not hasattr(RubricEval, "goal_id")
    assert not hasattr(RubricEval, "rubric_id")


def test_persona_eval_entity_cannot_be_upserted_as_kind_rubric() -> None:
    """Even a RubricEval-shaped dict fails the kind's SEMANTIC validation at
    the ontology boundary."""
    ontology = InMemoryOntology()
    register_rubric_kind(ontology)
    entity = OntologyEntity(kind=RUBRIC_KIND).with_semantic(
        {
            "department": "design",
            "eval_name": "layout",
            "criteria": [{"name": "grid", "weight": 1, "check": {"type": "regex", "pattern": "g"}}],
        }
    )
    with pytest.raises(ValidationError):
        ontology.upsert(entity)
    assert ontology.query(RUBRIC_KIND) == []


def test_eval_result_is_not_a_rubric_revision() -> None:
    """An EvalResult is a score outcome; a Rubric revision is the pre-declared
    contract. Scores live outside the Rubric kind (this milestone scores nothing)."""
    result = EvalResult(score=90, department="pm", eval_name="structure", details={})
    assert not isinstance(result, RubricSemantic)
    with pytest.raises(ValidationError):
        RubricSemantic.model_validate(result.__dict__)


# -- CreativeBrief is not accepted as a Rubric --------------------------------


def test_creative_brief_prose_is_rejected_as_rubric_payload() -> None:
    """Acceptance: CreativeBrief (audience/channel/source truth/allowed claims/
    deliverables/creative guidance) lacks everything a scored object requires —
    dimensions with scales, aggregation, gate, provenance — and is guidance
    projected from a Goal, not a Goal-bound acceptance contract."""
    brief_shaped: dict[str, object] = {
        "brief_id": "brief-1",
        "version": 1,
        "goal_id": "goal-1",
        "goal_revision": 1,
        "workspace_id": "ws-1",
        "project_id": "proj-1",
        "audience": "iOS power users",
        "channel": "youtube",
        "source_truth": "the Q3 spec",
        "allowed_claims": ["battery lasts 2 days"],
        "requested_deliverables": ["storyboard", "teaser script"],
        "acceptance_interpretation": (
            "the ad lands if the reviewer feels the battery claim is credible"
        ),
        "creative_guidance": "warm palette, handheld feel",
    }
    with pytest.raises(ValidationError):
        RubricSemantic.model_validate(brief_shaped)


def test_brief_guidance_cannot_satisfy_the_kind_model() -> None:
    """Even smuggling brief prose into the kind's field names fails: dimensions
    must be typed dimension records; guidance prose is not a weight or scale."""
    payload = goal_rubric_payload()
    payload["dimensions"] = [
        {
            "id": "audience",
            "name": "the ad lands if the reviewer feels the battery claim is credible",
            "weight": "warm palette, handheld feel",
            "scale": {},
            "method": "creative",
        }
    ]
    with pytest.raises(ValidationError):
        RubricSemantic.model_validate(payload)


def test_brief_cannot_swap_the_registered_kind_model() -> None:
    """The kind stays bound to RubricSemantic: whatever a brief model offers, it
    cannot be registered for the `rubric` kind while RubricSemantic holds it."""

    class BriefShaped(BaseModel):  # stand-in for any Design-Studio DTO
        audience: str

    ontology = InMemoryOntology()
    register_rubric_kind(ontology)
    with pytest.raises(Exception, match="already registered"):
        ontology.register(RUBRIC_KIND, BriefShaped)
    assert not issubclass(BriefShaped, RubricSemantic)


def test_store_rejects_rubric_missing_contract_fields() -> None:
    """What a brief supplies (guidance, no gate/provenance) cannot construct a
    Rubric: the store requires the contract fields, and the kind model does too."""
    from maistro.projects.rubric_store import (
        GoalRevisionSnapshot,
        InMemoryGoalRevisionCatalog,
        RubricStore,
    )

    catalog = InMemoryGoalRevisionCatalog()
    catalog.register_goal(
        GoalRevisionSnapshot(
            goal_id="goal-1", goal_revision=1, workspace_id="ws-1", project_id="proj-1"
        )
    )
    store = RubricStore(InMemoryOntology(), catalog)

    # Contract-level: the store's creation surface requires gate + provenance.
    params = inspect.signature(store.create).parameters
    assert "gate" in params and "provenance" in params
    # Kind-level: a gateless, provenance-less payload does not validate.
    payload = goal_rubric_payload()
    del payload["gate"], payload["provenance"]
    with pytest.raises(ValidationError):
        RubricSemantic.model_validate(payload)
    # Sanity: gate + provenance are the Rubric's, not a brief's, vocabulary.
    assert RubricGate(pass_threshold=80.0).pass_threshold == 80.0
    assert RubricProvenance(authored_by="user-1").authored_by == "user-1"
