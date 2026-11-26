"""Goal `Rubric` — a first-class ontology kind (M7-A2, issue #791).

A Rubric is a **versioned scored-acceptance object bound to one Goal
revision**. Runs name the exact revision they scored against, evals score
against its dimensions, and fences consult its pass/fail gate — without
prompt text, CreativeBrief prose, or persona department YAML becoming that
object.

Deliberately **not** this class:

- :class:`maistro.personas.rubric.RubricEval` scores persona/department
  template evals (0-100, vocabulary checks, no network). That is a scorer
  over template outputs, not a Goal's scored-acceptance object. The two
  share nothing but the English word "rubric".
- A CreativeBrief (#774) may hold "creative success/acceptance
  interpretation". That is guidance prose projected from a Goal revision,
  not a scored object; it carries no dimensions, scales, or aggregation
  rule and is structurally rejected here.

A Rubric never grants authorization. It records what "done, acceptably"
means for one Goal revision; who may act on that verdict is authorization's
job, not the Rubric's.

The kind slug is ``"rubric"``. Packs may supply default dimension catalogs
(:class:`PackRubricCatalog`); a catalog is a supply-side artifact — it is
never registered as an ontology kind and never owns Rubric identity. See
:mod:`maistro.projects.rubric_store` for the ontology-backed store that
mints and binds Rubric revisions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from maistro.ontology.protocols import Ontology

#: Ontology kind slug for the Goal scored-acceptance object.
RUBRIC_KIND = "rubric"


class ScoringMethod(StrEnum):
    """How a dimension is scored (recorded, not executed — this PR scores nothing)."""

    DETERMINISTIC = "deterministic"
    MODEL_JUDGE = "model_judge"
    HUMAN = "human"


class ProvenanceOrigin(StrEnum):
    """Who authored a Rubric revision.

    ``AUTHORED`` — written directly by a principal.
    ``PACK`` — instantiated from a pack-supplied default dimension catalog.
    The pack supplied defaults; it does not own the Rubric (identity is
    minted fresh by the store, and the catalog itself is never persisted).
    """

    AUTHORED = "authored"
    PACK = "pack"


class NumericScale(BaseModel):
    """A bounded numeric scale for one dimension (e.g. 0-100)."""

    model_config = ConfigDict(extra="forbid")

    min_value: float = 0.0
    max_value: float = 100.0

    @model_validator(mode="after")
    def _ordered(self) -> NumericScale:
        if self.min_value >= self.max_value:
            raise ValueError("numeric scale requires min_value < max_value")
        return self


class PassFailScale(BaseModel):
    """A binary pass/fail scale for one dimension."""

    model_config = ConfigDict(extra="forbid")

    pass_value: float = 1.0
    fail_value: float = 0.0


class RubricScale(BaseModel):
    """The scale a dimension is scored on: numeric and/or pass-fail."""

    model_config = ConfigDict(extra="forbid")

    numeric: NumericScale | None = None
    pass_fail: PassFailScale | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> RubricScale:
        if self.numeric is None and self.pass_fail is None:
            raise ValueError("rubric scale requires a numeric scale, a pass/fail scale, or both")
        return self


class RubricDimension(BaseModel):
    """One ordered scoring dimension of a Rubric revision."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    weight: float = Field(gt=0.0)
    scale: RubricScale
    method: ScoringMethod
    evidence_required: bool = False


class RubricAggregation(BaseModel):
    """How dimension results combine into one score.

    ``method`` is fixed to ``weighted_sum`` in v1; veto dimensions fail the
    whole Rubric regardless of the weighted total, and are named by id.
    """

    model_config = ConfigDict(extra="forbid")

    method: Literal["weighted_sum"] = "weighted_sum"
    veto_dimension_ids: list[str] = Field(default_factory=list)


class RubricGate(BaseModel):
    """The pass/fail gate a fence consults.

    The gate is consulted by fences; possessing or satisfying a Rubric
    grants no authorization.
    """

    model_config = ConfigDict(extra="forbid")

    pass_threshold: float = Field(ge=0.0, le=100.0)
    description: str = ""


class RubricProvenance(BaseModel):
    """Who authored a revision and which pack snapshot supplied its defaults.

    ``pack_id`` names the supplier; the optional ``publisher`` /
    ``pack_version`` / ``manifest_sha256`` / ``asset_id`` / ``asset_version``
    fields pin the exact registry snapshot and asset the revision was minted
    from, so rubrics instantiated from different versions of one pack stay
    provenance-distinguishable (the version-addressable contract). Catalog
    adoption — which carries no manifest snapshot — records ``pack_id`` only.

    The five detail fields are all-or-nothing — either the full snapshot
    identity rides along or none of it does — because every one of them
    comes from the same immutable manifest snapshot, and a half-stamped
    provenance would be a third state that names no real install.
    """

    model_config = ConfigDict(extra="forbid")

    authored_by: str = Field(min_length=1)
    origin: ProvenanceOrigin = ProvenanceOrigin.AUTHORED
    pack_id: str | None = None
    #: The exact pack snapshot the revision was instantiated from (all set
    #: together by ``instantiate_rubric_asset``; absent for catalog adoption).
    #: Blank strings name nothing, so the fields are non-empty when present.
    publisher: str | None = Field(default=None, min_length=1)
    pack_version: str | None = Field(default=None, min_length=1)
    manifest_sha256: str | None = Field(default=None, min_length=1)
    asset_id: str | None = Field(default=None, min_length=1)
    asset_version: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _pack_shape(self) -> RubricProvenance:
        if self.origin is ProvenanceOrigin.PACK and not self.pack_id:
            raise ValueError("pack-origin provenance requires pack_id")
        details = (
            self.publisher,
            self.pack_version,
            self.asset_id,
            self.asset_version,
            self.manifest_sha256,
        )
        supplied = [detail is not None for detail in details]
        if any(supplied) and not all(supplied):
            raise ValueError(
                "pack provenance details are all-or-nothing: publisher, pack_version, "
                "asset_id, asset_version, and manifest_sha256 name one manifest "
                "snapshot together"
            )
        if any(supplied) and self.origin is not ProvenanceOrigin.PACK:
            raise ValueError("pack provenance details require origin='pack'")
        return self


class RubricSemantic(BaseModel):
    """SEMANTIC-facet payload for the ``rubric`` ontology kind.

    One revision records exactly one Goal revision binding plus its scope;
    identity is ``(rubric_id, revision)``. Revision payloads are immutable
    snapshots — changing scoring without changing the desired outcome mints
    a new revision against the same Goal revision (the store enforces this).

    ``workspace_id``/``project_id`` must match the bound Goal's Project.
    Cross-Workspace Goal/Rubric references are structurally rejected (the
    store compares both fields against the live Goal revision snapshot).
    """

    model_config = ConfigDict(extra="forbid")

    rubric_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    goal_id: str = Field(min_length=1)
    goal_revision: int = Field(ge=1)
    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    dimensions: list[RubricDimension] = Field(min_length=1)
    aggregation: RubricAggregation = Field(default_factory=RubricAggregation)
    gate: RubricGate
    provenance: RubricProvenance
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _dimension_consistency(self) -> RubricSemantic:
        dim_ids = [d.id for d in self.dimensions]
        if len(set(dim_ids)) != len(dim_ids):
            raise ValueError("rubric dimension ids must be unique")
        known = set(dim_ids)
        for veto_id in self.aggregation.veto_dimension_ids:
            if veto_id not in known:
                raise ValueError(f"veto dimension {veto_id!r} is not a dimension of this rubric")
        return self


def rubric_entity_id(rubric_id: str, revision: int) -> UUID:
    """Deterministic entity id for one Rubric revision.

    Revision payloads are immutable snapshots, so (rubric_id, revision)
    mapping to a stable UUID makes store writes idempotent and historical
    revisions addressable without a second index.
    """
    return uuid5(NAMESPACE_URL, f"maistro:rubric:{rubric_id}:{revision}")


def register_rubric_kind(ontology: Ontology) -> None:
    """Register the ``rubric`` kind + SEMANTIC model with an ``Ontology``.

    Also registers the ``rubric_run_binding`` kind: the durable record of
    which exact Rubric revision (and, via it, Goal revision) a historical
    Run consumed. Bindings are ontology entities, so they survive store
    restarts exactly like the revisions they name.

    Idempotent per the ontology's own registration contract.
    """
    ontology.register(RUBRIC_KIND, RubricSemantic)
    ontology.register(RUBRIC_RUN_BINDING_KIND, RubricRunBindingSemantic)


#: Ontology kind slug for a historical Run's (Goal, Rubric) revision binding.
RUBRIC_RUN_BINDING_KIND = "rubric_run_binding"


class RubricRunBindingSemantic(BaseModel):
    """SEMANTIC-facet payload for the ``rubric_run_binding`` ontology kind.

    One immutable record per ``run_id``: the exact Rubric revision a Run
    scored against and the Goal revision that revision binds. Persisted as
    an ontology entity so it is durable across restarts and reconstructable
    from the same store the revisions live in.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    rubric_id: str = Field(min_length=1)
    rubric_revision: int = Field(ge=1)
    goal_id: str = Field(min_length=1)
    goal_revision: int = Field(ge=1)


def rubric_run_binding_entity_id(run_id: str) -> UUID:
    """Deterministic entity id for one Run's binding.

    One binding per Run, so ``run_id`` alone maps to a stable UUID: record
    is idempotent, and the durable read is a direct ``get`` — no index.
    """
    return uuid5(NAMESPACE_URL, f"maistro:rubric-run-binding:{run_id}")


class PackRubricCatalog(BaseModel):
    """A pack-supplied default dimension catalog.

    Supply-side artifact only: it carries no rubric_id, is never registered
    as an ontology kind, and never owns Rubric identity. Instantiating a
    Rubric from a catalog deep-copies the dimensions into a fresh Rubric
    whose provenance names the pack as supplier (:mod:`maistro.projects.
    rubric_store`).
    """

    model_config = ConfigDict(extra="forbid")

    pack_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    dimensions: list[RubricDimension] = Field(min_length=1)
    aggregation: RubricAggregation | None = None
    gate: RubricGate | None = None
