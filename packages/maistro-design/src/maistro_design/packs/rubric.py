"""Goal-scoped Rubric catalog instantiation (M7-A4, #793).

The pack supplies the *default* Rubric dimension catalog; the instantiated
catalog belongs to the Goal, and its identity is minted per instantiation.
Nothing here stores, registers, or resolves a Rubric — M7-A2 owns durable
Rubric identity and persistence. This module is the pack-side projection the
acceptance criterion names ("each pack can instantiate a Rubric catalog onto
a Goal without owning Rubric identity"): a frozen value object keyed by
canonical Goal identity, with an id that exists only because some caller
instantiated it.

Goal identity is the canonical `INTEROP_ONTOLOGY_V1` Goal: `goal_id` with
`goal_revision` (owner `maistro.goals`, parent Project). Validation goes
through the ontology contract itself, so this projection cannot drift from
the canonical Goal shape (#458).
"""

from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from maistro.interop.contract import INTEROP_ONTOLOGY_V1
from maistro_design.packs.types import PackId, RubricDimension


class GoalRubricDimension(BaseModel):
    """One rubric dimension grounded onto a Goal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""


class GoalRubricCatalog(BaseModel):
    """A pack's default Rubric dimensions, instantiated onto one Goal revision.

    `catalog_id` is minted per instantiation — the pack never carries it, so
    two instantiations of the same pack onto the same Goal are two catalogs
    (the Goal owns whichever the caller keeps), and the pack object itself
    stays identity-free for Rubric purposes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    catalog_id: str = Field(min_length=1)
    goal_id: str = Field(min_length=1)
    goal_revision: int = Field(ge=1)
    pack_id: PackId  # provenance of the dimension defaults, not an ownership claim
    #: The pack release these defaults came from (M9-F3, #968). Provenance
    #: only — a later pack upgrade never rewrites an instantiated catalog.
    pack_version: str = Field(min_length=1, pattern=r"^\d+\.\d+\.\d+$")
    dimensions: tuple[GoalRubricDimension, ...] = Field(min_length=1)

    @classmethod
    def instantiate(
        cls,
        *,
        pack_id: PackId,
        pack_version: str,
        dimensions: tuple[RubricDimension, ...],
        goal_id: str,
        goal_revision: int,
        catalog_id: str | None = None,
    ) -> GoalRubricCatalog:
        """Validate the Goal projection and mint a Goal-scoped catalog.

        Raises the ontology contract's own error when `goal_id`/`goal_revision`
        is not a canonical Goal identity, so a pack cannot invent a Goal shape.
        """
        canonical_goal_id = INTEROP_ONTOLOGY_V1.validate_projection(
            "Goal", {"goal_id": goal_id, "goal_revision": goal_revision}
        )
        return cls(
            catalog_id=catalog_id if catalog_id is not None else uuid4().hex,
            goal_id=canonical_goal_id,
            goal_revision=goal_revision,
            pack_id=pack_id,
            pack_version=pack_version,
            dimensions=tuple(
                GoalRubricDimension(
                    dimension_id=dimension.dimension_id,
                    name=dimension.name,
                    description=dimension.description,
                )
                for dimension in dimensions
            ),
        )
