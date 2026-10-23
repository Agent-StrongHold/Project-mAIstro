"""Domain pack contract (M7-A4, #793) — domain is a pack, not a product.

A domain pack is a *bundle of defaults* the one canonical loop can run with:
a default Rubric dimension catalog, a Graph shape for
explore → execute → evaluate → refine, the execute backends it may bind, the
artifact kinds it may emit, and its fence points. `product`, `game` and
`book` are three such bundles — not three products. The invariants the
contract encodes:

- **No second identity scheme.** A pack never mints a Goal, Run, NodeRun,
  Attempt, Workspace, Project or Design Studio identity. Runs executed from a
  pack's Graph template are canonical `maistro.runs` records exactly like any
  other Graph; Goal identity stays the `INTEROP_ONTOLOGY_V1` `Goal`
  (`goal_id` + `goal_revision`, owner `maistro.goals`).
- **Closed pack id, open catalog.** `PackId` is a closed enum of the shipped
  packs. The extension rule is: add one enum member plus one in-repo YAML
  manifest under `maistro_design/packs/manifests/` — never a new package
  (`maistro-game` / `maistro-book` products are explicitly out of scope).
- **Backends are bindings, never packs.** `ExecuteBackend` values (canvas,
  builders, artifact writers) may only appear in `execute_backends` and on
  execute-phase node `binding_ids`. A pack id can never name a backend, and
  `product` binds canvas while `book` does not — neither pack becomes "the
  Canvas pack".
- **Fence points are declared, not implied.** `fence_points` names the loop
  phases where park/redirect/accept is required; `PackPhase.fenced` marks the
  gated node inside the Graph shape, and `_PHASE_GATES` is the single
  phase→gate mapping. (The fence *execution* semantics — the durable HITL
  park itself — stay with the canonical loop runtime; the pack only declares
  where the gates sit.)
- **A pack id can never name a backend.** `PackId` and `ExecuteBackend` are
  two closed enums with disjoint member values — a manifest declaring
  `pack_id: canvas` fails enum validation, and the disjointness itself is
  pinned by test (AC-5), so no validator-side collision check is needed.

Placement (the A1 documentation hook): this contract lives in ONE place,
`maistro_design.packs`, because Design Studio hosts all three packs and
`maistro-design` is its substrate package (ADR-061) which already depends on
`maistro-core` for canonical Graph/Goal semantics (ADR-081226-034b direction).
M7-A1 has since landed as ADR-092926-7a01 / SPEC-093026-7a90 and does not
move it: packs there are data under registry/repertoire supply chains that
cannot register ontology kinds, own workstate, mint identity, or bypass the
effect chain (ADR-092926-7a01 §5) — exactly the invariants this module
enforces. The manifest format itself remains A1 open question Q4; this
in-repo YAML registry is this lane's answer to it.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PackPhaseName = Literal["explore", "execute", "evaluate", "refine"]

if TYPE_CHECKING:
    # Import at type-check time only: `rubric` imports this module's contract
    # types, so a runtime import would make the pair unimportable from either
    # door. The method body does the deferred runtime import itself.
    from maistro_design.packs.rubric import GoalRubricCatalog

_LOOP_PHASES = frozenset({"explore", "execute", "evaluate", "refine"})


def _reachable_from_entry(entry: str, edges: tuple[tuple[str, str], ...]) -> set[str]:
    reachable = {entry}
    changed = True
    while changed:
        changed = False
        for source, target in edges:
            if source in reachable and target not in reachable:
                reachable.add(target)
                changed = True
    return reachable


def _validate_shape_edges(
    node_ids: list[str], entry_node: str, edges: tuple[tuple[str, str], ...]
) -> None:
    by_id = set(node_ids)
    if entry_node not in by_id:
        raise ValueError(f"entry_node {entry_node!r} is not a shape node")
    for source, target in edges:
        if source not in by_id or target not in by_id:
            raise ValueError(f"edge {source!r} -> {target!r} references a node outside the shape")
    unreachable = by_id - _reachable_from_entry(entry_node, edges)
    if unreachable:
        raise ValueError(f"nodes unreachable from entry: {sorted(unreachable)}")


class RubricDimension(BaseModel):
    """One default rubric dimension a pack ships in its manifest.

    A *default*, not an instance: the dimension becomes evaluation criteria
    only when the pack's catalog is instantiated onto a Goal (see
    `rubric.GoalRubricCatalog`), and the pack never carries the resulting
    identity.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""


class PackId(StrEnum):
    """Closed enum of shipped domain packs.

    Extension rule (#793): adding a pack means adding one member here and one
    YAML manifest under `maistro_design/packs/manifests/`. It must never mean
    a new package identity — the pack registry is the single place a pack is
    declared, loaded, and listed.
    """

    PRODUCT = "product"
    GAME = "game"
    BOOK = "book"


class ExecuteBackend(StrEnum):
    """Execute backends a pack may bind.

    These are *bindings* onto canonical executors (canvas composition,
    Builders, artifact writers, later media), never pack identities: no pack
    may be named after a backend, and "canvas" in a manifest is a backend
    reference under `execute_backends` / node `binding_ids` — nothing else.
    """

    CANVAS = "canvas"
    BUILDERS = "builders"
    FILE_ARTIFACT_WRITER = "file_artifact_writer"
    TEXT_ARTIFACT_TREE = "text_artifact_tree"
    MEDIA = "media"


class FencePoint(StrEnum):
    """A loop phase where park/redirect/accept is required (#793 pack contract).

    The value is `<phase>.<gate>`; the gate sits after the *fenced* node of
    that phase completes. Fence execution (the durable HITL park) belongs to
    the canonical loop runtime — the pack declares where the gates are.
    """

    EXPLORE_ACCEPT = "explore.accept"
    EXECUTE_PARK = "execute.park"
    EVALUATE_ACCEPT = "evaluate.accept"
    REFINE_ACCEPT = "refine.accept"


#: The fence gate each loop phase closes with, declared as data over the
#: closed `FencePoint` enum — four phases, four gates, one source of truth.
#: String surgery (`f"{phase}.accept"`) is how a gate spelling drifts from the
#: enum the manifests declare; this mapping cannot.
_PHASE_GATES: Mapping[PackPhaseName, FencePoint] = {
    "explore": FencePoint.EXPLORE_ACCEPT,
    "execute": FencePoint.EXECUTE_PARK,
    "evaluate": FencePoint.EVALUATE_ACCEPT,
    "refine": FencePoint.REFINE_ACCEPT,
}


def _fence_gate_for(phase_name: PackPhaseName) -> str:
    """The fence point a gated node of `phase_name` must have declared."""
    return _PHASE_GATES[phase_name].value


class PackPhase(BaseModel):
    """One node of a pack's explore → execute → evaluate → refine shape.

    `kind` is the node type the canonical Graph executor resolves through its
    `NodeResolver` — phase kinds are loop-runtime bindings, not registered
    LLM nodes. `fenced: True` marks a node whose completion requires a
    park/redirect/accept gate before downstream nodes run.
    """

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    phase: PackPhaseName
    fenced: bool = False


class PackGraphShape(BaseModel):
    """The topology a pack binds for the one canonical loop.

    Shapes must genuinely differ between packs (that is what makes a pack
    thick rather than a label), so edges are explicit and validated for
    endpoint membership, reachability from the entry, and at least one node
    in each of the four loop phases.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    entry_node: str = Field(min_length=1)
    nodes: tuple[PackPhase, ...] = Field(min_length=4)
    edges: tuple[tuple[str, str], ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_shape(self) -> PackGraphShape:
        node_ids = [phase.node_id for phase in self.nodes]
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("pack graph shape node_ids must be unique")
        _validate_shape_edges(node_ids, self.entry_node, self.edges)
        phases = {phase.phase for phase in self.nodes}
        missing = _LOOP_PHASES - phases
        if missing:
            raise ValueError(f"pack graph shape is missing loop phases: {sorted(missing)}")
        fence_gates = {gate.value for gate in _PHASE_GATES.values()}
        for phase in self.nodes:
            if not phase.fenced:
                continue
            gate = _fence_gate_for(phase.phase)
            if gate not in fence_gates:
                raise ValueError(f"fenced node {phase.node_id!r} has no fence point")
        return self


class PackSummary(BaseModel):
    """The Design Studio selector payload for one pack.

    Deliberately uniform across packs — one listing shape, no per-pack
    fields — so no pack can grow product identity through its listing.
    """

    model_config = ConfigDict(extra="forbid")

    pack_id: PackId
    name: str
    summary: str
    execute_backends: tuple[ExecuteBackend, ...]
    artifact_kinds: tuple[str, ...]


_SEMVER_RE = "^\\d+\\.\\d+\\.\\d+$"


class DomainPack(BaseModel):
    """One domain pack manifest (#793 pack contract, minimum).

    A pack owns *defaults only*. It never owns: a Goal (Goals are canonical
    `maistro.goals` identity a pack instantiates *onto*), a Rubric catalog
    instance (identity is minted per Goal instantiation — see
    `rubric.GoalRubricCatalog`), a Run/NodeRun/Attempt (minted by the
    canonical executor from the pack's Graph template), or a Design Studio.

    `version` is the pack's own release version (M9-F3, #968): the identity a
    Workspace activation is recorded against. It is a *pack* version, not a
    Goal/Graph/Rubric revision — instantiations carry it as provenance and are
    never rewritten by a later upgrade.
    """

    model_config = ConfigDict(extra="forbid")

    pack_id: PackId
    version: str = Field(min_length=1, pattern=_SEMVER_RE)
    name: str = Field(min_length=1)
    summary: str = ""
    explore_focus: tuple[str, ...] = Field(min_length=1)
    execute_backends: tuple[ExecuteBackend, ...] = Field(min_length=1)
    artifact_kinds: tuple[str, ...] = Field(min_length=1)
    rubric_dimensions: tuple[RubricDimension, ...] = Field(min_length=1)
    fence_points: tuple[FencePoint, ...] = ()
    graph: PackGraphShape

    @model_validator(mode="after")
    def _validate_pack(self) -> DomainPack:
        if len(set(self.artifact_kinds)) != len(self.artifact_kinds):
            raise ValueError("artifact_kinds must be unique within a pack")
        dimension_ids = [dimension.dimension_id for dimension in self.rubric_dimensions]
        if len(set(dimension_ids)) != len(dimension_ids):
            raise ValueError("rubric dimension_ids must be unique within a pack")
        # (A backend name is a binding name, never a pack identity — AC-5. That
        # invariant needs no validator branch here: `PackId` and
        # `ExecuteBackend` are two closed enums with disjoint members, so a
        # colliding manifest fails enum validation before this validator runs.
        # The disjointness itself is pinned at the enum level by test.)
        # Declared fence points must cover every gated node in the shape.
        declared = {point.value for point in self.fence_points}
        for phase in self.graph.nodes:
            if not phase.fenced:
                continue
            gate = _fence_gate_for(phase.phase)
            if gate not in declared:
                raise ValueError(
                    f"fenced node {phase.node_id!r} requires fence point {gate!r} in fence_points"
                )
        return self

    def instantiate_rubric_catalog(
        self,
        *,
        goal_id: str,
        goal_revision: int,
        catalog_id: str | None = None,
    ) -> GoalRubricCatalog:
        """Instantiate the pack's default Rubric dimension catalog onto a Goal.

        The Goal identity is validated against the canonical ontology
        (`goal_id` + `goal_revision`); the catalog id is minted fresh per
        instantiation unless the caller supplies one, so the pack never owns
        Rubric identity — it only supplies the dimension defaults.

        The catalog model is imported here rather than at module scope:
        `rubric` imports this module's contract types, and a module-level
        import would make the pair unimportable from either door (the same
        shape as `GraphSnapshot.materialize` in maistro.runs.model).
        """
        from maistro_design.packs.rubric import GoalRubricCatalog

        return GoalRubricCatalog.instantiate(
            pack_id=self.pack_id,
            pack_version=self.version,
            dimensions=self.rubric_dimensions,
            goal_id=goal_id,
            goal_revision=goal_revision,
            catalog_id=catalog_id,
        )

    def to_summary(self) -> PackSummary:
        """The uniform selector entry for this pack (AC-6 substrate side)."""
        return PackSummary(
            pack_id=self.pack_id,
            name=self.name,
            summary=self.summary,
            execute_backends=self.execute_backends,
            artifact_kinds=self.artifact_kinds,
        )
