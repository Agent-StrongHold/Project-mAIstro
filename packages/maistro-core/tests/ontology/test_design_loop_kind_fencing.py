"""M7-A1 contract: design-loop kinds are fenced to the ontology registry (#790).

Contract under test: ADR-092926-7a01 / SPEC-092926-7a01.

The closed design loop (`Goal -> Rubric -> Explore -> Execute -> Evaluate ->
Refine`) runs as one Graph/Run over the canonical object graph. The nouns it
introduces are ontology kinds, not product-local identity: a product module
that registers a competing `Goal`, `Rubric`, or `EvalRun` kind outside the
ontology registry must fail loudly, Goal semantics stay singly owned with exact
revision lineage (#458), Persona `RubricEval` (ADR-060) is not the Goal Rubric,
and no sidecar eval identity (`EvalRun`) may exist.

The canonical semantic models used here are contract stand-ins: the M7-A2 lane
registers the real Rubric semantics on this registry and replaces them.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from maistro.interop import (
    INTEROP_ONTOLOGY_V1,
    InteropContractError,
    validate_projection,
)
from maistro.ontology.registry import InMemoryOntology
from maistro.ontology.types import KindAlreadyRegisteredError
from maistro.personas.rubric import RubricEval


class _CanonicalGoalSemantic(BaseModel):
    """Stand-in for the ontology-registered Goal semantics (#458)."""

    goal_id: str
    goal_revision: int
    title: str


class _CompetingGoalProductDTO(BaseModel):
    """A product-local shape that mints its own Goal identity (forbidden)."""

    design_goal_key: str
    summary: str


class _CanonicalRubricSemantic(BaseModel):
    """Stand-in for the ontology-registered Goal-acceptance Rubric semantics."""

    rubric_id: str
    rubric_version: int
    goal_id: str
    goal_revision: int


class _CompetingRubricProductDTO(BaseModel):
    """A product-local shape claiming its own rubric identity (forbidden)."""

    studio_rubric_key: str
    dimensions: list[str]


class _CompetingEvalRunProductDTO(BaseModel):
    """A sidecar eval-run identity — the exact shape ADR-092926-7a01 forbids."""

    eval_run_key: str
    scores: dict[str, float]


#: Fenced kind names -> the semantics the ontology registry would hold (the
#: canonical claim) and the competing shape a product module must not claim.
_FENCED_KINDS: dict[str, tuple[type[BaseModel], type[BaseModel]]] = {
    "Goal": (_CanonicalGoalSemantic, _CompetingGoalProductDTO),
    "Rubric": (_CanonicalRubricSemantic, _CompetingRubricProductDTO),
    "EvalRun": (_CanonicalGoalSemantic, _CompetingEvalRunProductDTO),
}


@pytest.mark.contract("boundary")
@pytest.mark.ac("SPEC-092926-7a01/AC-1")
@pytest.mark.parametrize("kind", sorted(_FENCED_KINDS))
def test_fenced_kind_rejects_product_module_registration(kind: str) -> None:
    """A product module cannot register a competing Goal/Rubric/EvalRun kind.

    The ontology registry holds the canonical semantics first (as the canonical
    owner would); a second, different model claiming the same kind is the
    competing-kind defect the M7 contract forbids and must raise.
    """
    canonical, competing = _FENCED_KINDS[kind]
    ontology = InMemoryOntology()
    ontology.register(kind, canonical)

    with pytest.raises(KindAlreadyRegisteredError):
        ontology.register(kind, competing)


@pytest.mark.contract("boundary")
@pytest.mark.parametrize("kind", sorted(_FENCED_KINDS))
def test_canonical_owner_re_registration_is_idempotent(kind: str) -> None:
    """The fence blocks competing claims, not the canonical owner itself."""
    canonical, _competing = _FENCED_KINDS[kind]
    ontology = InMemoryOntology()
    ontology.register(kind, canonical)

    ontology.register(kind, canonical)  # same-model re-registration is a no-op


@pytest.mark.contract("boundary")
@pytest.mark.ac("SPEC-092926-7a01/AC-2")
def test_goal_has_exactly_one_canonical_identity() -> None:
    """No alias concept may mint a second Goal identity (#458)."""
    spec = INTEROP_ONTOLOGY_V1.concepts["Goal"]
    assert spec.owner == "maistro.goals"
    assert spec.identity == "goal_id"
    assert spec.revision == "goal_revision"
    assert spec.parent == "Project"

    goal_identity_owners = {
        name: concept.owner
        for name, concept in INTEROP_ONTOLOGY_V1.concepts.items()
        if concept.identity == "goal_id"
    }
    assert goal_identity_owners == {"Goal": "maistro.goals"}


@pytest.mark.contract("boundary")
@pytest.mark.ac("SPEC-092926-7a01/AC-3")
def test_goal_projection_requires_canonical_identity_and_revision() -> None:
    """A Goal projection carries goal_id + goal_revision — nothing else counts.

    A foreign identity (a product-local DTO key) and a revision-less projection
    are both rejected: the consumed Goal revision must stay recoverable, so
    history cannot be silently rewritten (ADR-092926-7a01 §8).
    """
    with pytest.raises(InteropContractError):
        validate_projection(INTEROP_ONTOLOGY_V1, "Goal", {"design_goal_key": "g-1"})

    with pytest.raises(InteropContractError):
        validate_projection(INTEROP_ONTOLOGY_V1, "Goal", {"goal_id": "g-1"})

    carried = validate_projection(
        INTEROP_ONTOLOGY_V1, "Goal", {"goal_id": "g-1", "goal_revision": 3}
    )
    assert carried == "g-1"


@pytest.mark.contract("boundary")
@pytest.mark.ac("SPEC-092926-7a01/AC-4")
def test_persona_module_owns_no_scoring_kind() -> None:
    """`maistro.personas` owns Persona flavor — never a Goal-scoring kind.

    Persona `RubricEval` (ADR-060) is department/template scoring; the
    Goal-acceptance Rubric is a different object owned by the Goal-acceptance
    facet, and the persona module can never claim it in the shared ontology.
    """
    persona_owned = {
        name
        for name, concept in INTEROP_ONTOLOGY_V1.concepts.items()
        if concept.owner == "maistro.personas"
    }
    assert persona_owned == {"Persona"}
    assert "RubricEval" not in INTEROP_ONTOLOGY_V1.concepts


@pytest.mark.contract("boundary")
@pytest.mark.ac("SPEC-092926-7a01/AC-4")
def test_persona_rubric_eval_class_cannot_claim_goal_rubric_kind() -> None:
    """The persona scorer is not a Rubric semantic, even accidentally."""
    ontology = InMemoryOntology()
    ontology.register("Rubric", _CanonicalRubricSemantic)

    with pytest.raises(KindAlreadyRegisteredError):
        ontology.register("Rubric", RubricEval)


@pytest.mark.contract("boundary")
@pytest.mark.ac("SPEC-092926-7a01/AC-5")
def test_no_sidecar_eval_kind_in_shared_ontology() -> None:
    """Eval evidence keys to the producing Run/NodeRun/Attempt — never a new kind.

    Eval-on-Run (ADR-092926-7a01 §7): scores and dimension results attach to
    the producing execution; the shared ontology must not declare `EvalRun`
    (or any sidecar eval-session identity).
    """
    for forbidden in ("EvalRun", "EvalSession"):
        assert forbidden not in INTEROP_ONTOLOGY_V1.concepts
        # Note: `EvalRecord` is likewise never an ontology *entity* — the ADR
        # gives it no minted identity, so it can only ever appear as evidence
        # keyed by the producing attempt. It is deliberately not asserted here
        # so A4 may declare it as a projection of producing identity if useful.


@pytest.mark.contract("boundary")
def test_ontology_registry_rejects_unknown_kind_upsert() -> None:
    """Kinds only enter the registry through registration — not through upsert."""
    from maistro.ontology.types import KindNotRegisteredError, OntologyEntity

    ontology = InMemoryOntology()
    entity = OntologyEntity(kind="EvalRun").with_semantic({"eval_run_key": "e-1"})
    with pytest.raises(KindNotRegisteredError):
        ontology.upsert(entity)
