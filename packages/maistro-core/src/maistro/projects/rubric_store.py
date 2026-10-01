"""Ontology-backed `Rubric` persistence with Project scope (M7-A2, #791).

The Rubric ontology kind (:mod:`maistro.ontology.rubric`) is persisted as
ontology entities; this module is the Project-scoped store around it. It
enforces the binding invariants:

- A Rubric revision binds to exactly one **live** Goal revision in the same
  Project. Creating a Rubric without one fails (:class:`RubricGoalNotLiveError`).
- ``workspace_id``/``project_id`` must match the Goal's Project; cross-
  Project/Workspace binds are structurally rejected
  (:class:`RubricScopeMismatchError`).
- Revisions are immutable snapshots. Updating dimensions mints a new
  revision; every prior revision stays readable by number.
- Historical Runs persist a binding that names the exact ``(rubric_id,
  revision)`` — and, via the revision payload, the exact Goal revision.
- A Rubric never grants authorization: nothing here consults or produces
  permissions, grants, or capabilities.

Goal-side seam: canonical Goal identity is ``maistro.goals``
(``goal_id`` + ``goal_revision``, INTEROP-ONTOLOGY-v1). That module does not
exist yet at this head, so the store depends on the minimal
:class:`GoalRevisionCatalog` Protocol instead of a Goal store; when the
canonical Goal persistence lands (#458) it implements the Protocol and is
injected — no Rubric code changes, and no competing Goal store is created
here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from maistro.ontology.protocols import Ontology
from maistro.ontology.rubric import (
    RUBRIC_KIND,
    RUBRIC_RUN_BINDING_KIND,
    PackRubricCatalog,
    RubricAggregation,
    RubricDimension,
    RubricGate,
    RubricProvenance,
    RubricRunBindingSemantic,
    RubricSemantic,
    register_rubric_kind,
    rubric_entity_id,
    rubric_run_binding_entity_id,
)
from maistro.ontology.types import OntologyEntity

#: Prefix for minted Rubric identity. Callers may pass their own rubric_id;
#: minted ids are opaque and never derived from pack content.
_MINTED_ID_PREFIX = "rubric-"


class GoalRevisionSnapshot(BaseModel):
    """The live state of one Goal revision, as the Goal system reports it."""

    model_config = ConfigDict(extra="forbid")

    goal_id: str
    goal_revision: int = Field(ge=1)
    workspace_id: str
    project_id: str


@runtime_checkable
class GoalRevisionCatalog(Protocol):
    """Resolution seam for live Goal revisions.

    Minimal on purpose: it answers exactly one question — is this Goal
    revision live, and in which scope? Accountability, lifecycle, and Goal
    persistence stay with the canonical Goal system (#458).
    """

    def resolve(self, goal_id: str, goal_revision: int) -> GoalRevisionSnapshot | None:
        """Return the snapshot if that exact Goal revision is live, else ``None``."""
        ...


class RubricError(Exception):
    """Base class for Rubric store errors."""


class RubricNotFoundError(RubricError, KeyError):
    """No Rubric (or no such revision) under that rubric_id."""


class RubricGoalNotLiveError(RubricError):
    """The referenced Goal revision is not live (unknown, superseded, or absent)."""


class RubricScopeMismatchError(RubricError):
    """The Rubric's Workspace/Project does not match the bound Goal's Project."""


class RubricRevisionConflictError(RubricError):
    """The revision already exists with different content (immutability guard)."""


class RubricRunBindingConflictError(RubricError):
    """The Run already has a binding naming different revisions (one binding per Run)."""


@dataclass(frozen=True, slots=True)
class RubricRunBinding:
    """What a historical Run names: the exact Rubric revision it scored
    against, and — via that revision's payload — the exact Goal revision."""

    run_id: str
    rubric_id: str
    rubric_revision: int
    goal_id: str
    goal_revision: int


class RubricStore:
    """Project-scoped persistence for Rubric revisions over an ``Ontology``.

    Every Rubric revision is one ontology entity of kind ``"rubric"`` with a
    deterministic id (see :func:`maistro.ontology.rubric.rubric_entity_id`),
    so writes are idempotent and revisions immutable.
    """

    def __init__(self, ontology: Ontology, goals: GoalRevisionCatalog) -> None:
        self._ontology = ontology
        self._goals = goals
        register_rubric_kind(ontology)

    # -- create / revise ---------------------------------------------------

    async def create(
        self,
        *,
        workspace_id: str,
        project_id: str,
        goal_id: str,
        goal_revision: int,
        dimensions: list[RubricDimension],
        gate: RubricGate,
        provenance: RubricProvenance,
        aggregation: RubricAggregation | None = None,
        rubric_id: str | None = None,
    ) -> RubricSemantic:
        """Mint revision 1 of a new Rubric bound to a live Goal revision."""
        rubric_id = rubric_id or f"{_MINTED_ID_PREFIX}{uuid4().hex[:12]}"
        return await self._persist(
            rubric_id=rubric_id,
            revision=1,
            workspace_id=workspace_id,
            project_id=project_id,
            goal_id=goal_id,
            goal_revision=goal_revision,
            dimensions=dimensions,
            aggregation=aggregation or RubricAggregation(),
            gate=gate,
            provenance=provenance,
        )

    async def update_dimensions(
        self,
        rubric_id: str,
        *,
        dimensions: list[RubricDimension],
        gate: RubricGate | None = None,
        aggregation: RubricAggregation | None = None,
        provenance: RubricProvenance | None = None,
        goal_revision: int | None = None,
    ) -> RubricSemantic:
        """Mint the next revision of an existing Rubric.

        Prior revisions are never mutated. Scoring changes without a change
        of desired outcome stay bound to the same Goal revision (the
        default); passing ``goal_revision`` re-binds the new revision to a
        different — still live — Goal revision, which is how a new Goal
        revision mints a new Rubric revision.
        """
        prior = await self.get(rubric_id)
        if prior is None:
            raise RubricNotFoundError(f"no rubric {rubric_id!r}")
        bound_goal_revision = goal_revision if goal_revision is not None else prior.goal_revision
        return await self._persist(
            rubric_id=rubric_id,
            revision=prior.revision + 1,
            workspace_id=prior.workspace_id,
            project_id=prior.project_id,
            goal_id=prior.goal_id,
            goal_revision=bound_goal_revision,
            dimensions=dimensions,
            aggregation=aggregation or prior.aggregation,
            gate=gate or prior.gate,
            provenance=provenance or prior.provenance,
        )

    async def instantiate_from_catalog(
        self,
        catalog: PackRubricCatalog,
        *,
        workspace_id: str,
        project_id: str,
        goal_id: str,
        goal_revision: int,
        adopted_by: str,
        rubric_id: str | None = None,
    ) -> RubricSemantic:
        """Instantiate a Rubric from a pack's default dimension catalog.

        The pack supplies defaults; it does not become the owner. Identity
        is minted fresh (or caller-supplied), provenance records
        ``origin="pack"`` with the adopter as ``authored_by``, and the
        dimensions are deep-copied so later catalog edits cannot leak into
        persisted Rubrics. The catalog itself is never persisted.
        """
        return await self.create(
            workspace_id=workspace_id,
            project_id=project_id,
            goal_id=goal_id,
            goal_revision=goal_revision,
            dimensions=[d.model_copy(deep=True) for d in catalog.dimensions],
            gate=catalog.gate or RubricGate(pass_threshold=80.0),
            aggregation=catalog.aggregation or RubricAggregation(),
            provenance=RubricProvenance(
                authored_by=adopted_by, origin="pack", pack_id=catalog.pack_id
            ),
            rubric_id=rubric_id,
        )

    # -- reads ---------------------------------------------------------------

    async def get(self, rubric_id: str) -> RubricSemantic | None:
        """Latest revision of a Rubric, or ``None``."""
        revisions = await self.revisions(rubric_id)
        return revisions[-1] if revisions else None

    async def get_revision(self, rubric_id: str, revision: int) -> RubricSemantic | None:
        """One exact revision, or ``None``. Historical revisions stay readable."""
        revisions = await self.revisions(rubric_id)
        for sem in revisions:
            if sem.revision == revision:
                return sem
        return None

    async def revisions(self, rubric_id: str) -> list[RubricSemantic]:
        """All revisions of a Rubric, ordered by revision number."""
        found = self._ontology.query(RUBRIC_KIND, rubric_id=rubric_id)
        semantics = [RubricSemantic.model_validate(e.get_semantic()) for e in found]
        return sorted(semantics, key=lambda s: s.revision)

    async def list_for_goal(self, goal_id: str) -> list[RubricSemantic]:
        """All Rubric revisions (latest per rubric_id) bound to a Goal."""
        found = self._ontology.query(RUBRIC_KIND, goal_id=goal_id)
        latest: dict[str, RubricSemantic] = {}
        for entity in found:
            sem = RubricSemantic.model_validate(entity.get_semantic())
            if sem.rubric_id not in latest or sem.revision > latest[sem.rubric_id].revision:
                latest[sem.rubric_id] = sem
        return sorted(latest.values(), key=lambda s: (s.rubric_id, s.revision))

    # -- run bindings --------------------------------------------------------

    async def record_run_binding(
        self, run_id: str, rubric_id: str, rubric_revision: int | None = None
    ) -> RubricRunBinding:
        """Persist the (goal, rubric) revision pair a Run scored against.

        ``rubric_revision=None`` pins the latest revision at record time.
        The binding is derived from the persisted revision payload, so a
        historical Run always names the exact revisions it consumed.
        """
        semantic = (
            await self.get_revision(rubric_id, rubric_revision)
            if rubric_revision is not None
            else await self.get(rubric_id)
        )
        if semantic is None:
            raise RubricNotFoundError(f"no rubric revision {rubric_id!r}@{rubric_revision}")
        binding = RubricRunBinding(
            run_id=run_id,
            rubric_id=semantic.rubric_id,
            rubric_revision=semantic.revision,
            goal_id=semantic.goal_id,
            goal_revision=semantic.goal_revision,
        )
        record = RubricRunBindingSemantic(
            run_id=binding.run_id,
            rubric_id=binding.rubric_id,
            rubric_revision=binding.rubric_revision,
            goal_id=binding.goal_id,
            goal_revision=binding.goal_revision,
        )
        entity = OntologyEntity(
            id=rubric_run_binding_entity_id(run_id), kind=RUBRIC_RUN_BINDING_KIND, revision=1
        ).with_semantic(record.model_dump(mode="json"))
        existing = self._ontology.get(entity.id)
        if existing is not None:
            prior = RubricRunBindingSemantic.model_validate(existing.get_semantic())
            if (
                prior.rubric_id,
                prior.rubric_revision,
                prior.goal_id,
                prior.goal_revision,
            ) != (
                record.rubric_id,
                record.rubric_revision,
                record.goal_id,
                record.goal_revision,
            ):
                raise RubricRunBindingConflictError(
                    f"run {run_id!r} already bound to rubric {prior.rubric_id!r}"
                    f"@{prior.rubric_revision}; one binding per Run"
                )
        self._ontology.upsert(entity)
        return binding

    async def binding_for_run(self, run_id: str) -> RubricRunBinding | None:
        """The binding a Run recorded, or ``None``.

        Read from the durable ontology (deterministic per-Run entity id),
        not from process memory, so a restarted or newly constructed store
        over the same ontology still resolves historical bindings.
        """
        entity = self._ontology.get(rubric_run_binding_entity_id(run_id))
        if entity is None:
            return None
        record = RubricRunBindingSemantic.model_validate(entity.get_semantic())
        return RubricRunBinding(
            run_id=record.run_id,
            rubric_id=record.rubric_id,
            rubric_revision=record.rubric_revision,
            goal_id=record.goal_id,
            goal_revision=record.goal_revision,
        )

    # -- internals -----------------------------------------------------------

    async def _persist(
        self,
        *,
        rubric_id: str,
        revision: int,
        workspace_id: str,
        project_id: str,
        goal_id: str,
        goal_revision: int,
        dimensions: list[RubricDimension],
        aggregation: RubricAggregation,
        gate: RubricGate,
        provenance: RubricProvenance,
    ) -> RubricSemantic:
        snapshot = self._goals.resolve(goal_id, goal_revision)
        if snapshot is None:
            raise RubricGoalNotLiveError(
                f"goal {goal_id!r} revision {goal_revision} is not live; "
                "a Rubric requires a live Goal revision in its Project"
            )
        if snapshot.project_id != project_id or snapshot.workspace_id != workspace_id:
            raise RubricScopeMismatchError(
                f"rubric scope workspace={workspace_id!r} project={project_id!r} does not "
                f"match goal {goal_id!r} scope workspace={snapshot.workspace_id!r} "
                f"project={snapshot.project_id!r}; cross-Project/Workspace binds are rejected"
            )

        semantic = RubricSemantic(
            rubric_id=rubric_id,
            revision=revision,
            goal_id=goal_id,
            goal_revision=goal_revision,
            workspace_id=workspace_id,
            project_id=project_id,
            dimensions=list(dimensions),
            aggregation=aggregation,
            gate=gate,
            provenance=provenance,
        )

        entity = OntologyEntity(
            id=rubric_entity_id(rubric_id, revision), kind=RUBRIC_KIND, revision=revision
        ).with_semantic(semantic.model_dump(mode="json"))
        existing = self._ontology.get(entity.id)
        if existing is not None:
            prior = RubricSemantic.model_validate(existing.get_semantic())
            # ``created_at`` is store-assigned, not caller content: adopt the
            # persisted timestamp before comparing so a retried identical
            # write stays idempotent (deterministic entity id, same payload).
            semantic = semantic.model_copy(update={"created_at": prior.created_at})
            if prior != semantic:
                raise RubricRevisionConflictError(
                    f"rubric {rubric_id!r} revision {revision} already exists with "
                    "different content; revisions are immutable"
                )
            return prior
        self._ontology.upsert(entity)
        return semantic
