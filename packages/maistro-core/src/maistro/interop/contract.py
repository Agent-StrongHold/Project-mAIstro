"""Executable cross-product interoperability ontology (#458).

The registry is metadata over canonical semantic owners. It deliberately does
not define replacement Workspace, Project, Agent, Goal, Graph, Run, Capability,
or product DTOs, and it is not a scheduler, execution authority, Goal store, or
authorization path. The public validators are module-level functions exported
through :mod:`maistro.interop` so the importable contract surface is exactly
the reviewed public API.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_MILESTONE_RE = re.compile(r"^M(?:0|[1-9]\d*)$")
_CARDINALITIES = frozenset({"exactly-one", "zero-or-one", "one-or-many", "zero-or-many"})


class InteropContractError(ValueError):
    """Raised when an ontology or product projection violates the contract."""


@dataclass(frozen=True, slots=True)
class ConceptSpec:
    """Canonical owner/identity metadata for one shared concept."""

    owner: str
    identity: str
    parent: str | None = None
    scope: str | None = None
    revision: str | None = None

    def as_dict(self) -> dict[str, str]:
        """The published concept fields, omitting absent optional relations."""
        result = {"owner": self.owner, "identity": self.identity}
        if self.scope is not None:
            result["scope"] = self.scope
        if self.parent is not None:
            result["parent"] = self.parent
        if self.revision is not None:
            result["revision"] = self.revision
        return result


@dataclass(frozen=True, slots=True)
class RelationshipSpec:
    """A typed semantic relationship between canonical concepts."""

    source: str
    target: str
    kind: str
    sources_per_target: str
    targets_per_source: str

    def as_dict(self) -> dict[str, str]:
        """The published relationship fields."""
        return {
            "source": self.source,
            "target": self.target,
            "kind": self.kind,
            "sources_per_target": self.sources_per_target,
            "targets_per_source": self.targets_per_source,
        }


@dataclass(frozen=True, slots=True)
class InteropOntology:
    """Versioned registry of canonical identities, relationships, and lineage."""

    version: str
    status: str
    issue: int
    principles: tuple[str, ...]
    concepts: Mapping[str, ConceptSpec]
    relationships: Mapping[str, RelationshipSpec]
    required_lineage: tuple[tuple[str, str], ...]
    consumers: Mapping[str, str]

    def __post_init__(self) -> None:
        """Freeze the registry mappings and validate the whole definition."""
        object.__setattr__(self, "concepts", MappingProxyType(dict(self.concepts)))
        object.__setattr__(self, "relationships", MappingProxyType(dict(self.relationships)))
        object.__setattr__(self, "consumers", MappingProxyType(dict(self.consumers)))
        self._validate_definition()

    def _validate_definition(self) -> None:
        """Run every structural validation in fail-loud order."""
        _parse_version(self.version)
        self._validate_header()
        self._validate_concepts()
        self._validate_relationships()
        self._validate_lineage()
        self._validate_consumers()

    def _validate_header(self) -> None:
        """Require a positive issue, non-blank status, and principles."""
        if self.issue <= 0:
            raise InteropContractError("ontology issue must be a positive integer")
        if not self.status.strip():
            raise InteropContractError("ontology status must be non-blank")
        if not self.principles or any(not item.strip() for item in self.principles):
            raise InteropContractError("ontology principles must be non-empty strings")
        if not self.concepts:
            raise InteropContractError("ontology must define at least one concept")

    def _validate_concepts(self) -> None:
        """Validate every concept spec."""
        for name, spec in self.concepts.items():
            self._validate_concept(name, spec)

    def _validate_concept(self, name: str, spec: ConceptSpec) -> None:
        """Require canonical owner, explicit identity, and known relations."""
        if not name.strip():
            raise InteropContractError("concept names must be non-blank")
        if not spec.owner.startswith("maistro."):
            raise InteropContractError(
                f"{name} owner must name a canonical maistro module, got {spec.owner!r}"
            )
        if not spec.identity.endswith("_id"):
            raise InteropContractError(
                f"{name} identity must be an explicit *_id field, got {spec.identity!r}"
            )
        if spec.revision is not None and not spec.revision.strip():
            raise InteropContractError(f"{name} revision field must be non-blank")
        for relation, target in (("parent", spec.parent), ("scope", spec.scope)):
            if target is not None and target not in self.concepts:
                raise InteropContractError(
                    f"{name} {relation} references unknown concept {target!r}"
                )

    def _validate_relationships(self) -> None:
        """Require known endpoints and reviewed cardinalities."""
        for name, spec in self.relationships.items():
            if not name.strip() or not spec.kind.strip():
                raise InteropContractError("relationship names and kinds must be non-blank")
            for endpoint_name, endpoint in (
                ("source", spec.source),
                ("target", spec.target),
            ):
                if endpoint not in self.concepts:
                    raise InteropContractError(
                        f"relationship {name!r} {endpoint_name} references "
                        f"unknown concept {endpoint!r}"
                    )
            for field_name, cardinality in (
                ("sources_per_target", spec.sources_per_target),
                ("targets_per_source", spec.targets_per_source),
            ):
                if cardinality not in _CARDINALITIES:
                    raise InteropContractError(
                        f"relationship {name!r} has invalid {field_name} {cardinality!r}"
                    )

    def _validate_lineage(self) -> None:
        """Require single-parent required lineage and declared parents."""
        lineage_parent: dict[str, str] = {}
        for parent, child in self.required_lineage:
            self._validate_lineage_edge(parent, child, lineage_parent)
        for name, spec in self.concepts.items():
            self._validate_declared_parent(name, spec)

    def _validate_lineage_edge(
        self,
        parent: str,
        child: str,
        lineage_parent: dict[str, str],
    ) -> None:
        """Reject lineage edges naming unknown concepts or second parents."""
        if parent not in self.concepts or child not in self.concepts:
            raise InteropContractError(
                f"required lineage {parent!r} -> {child!r} references an unknown concept"
            )
        previous = lineage_parent.setdefault(child, parent)
        if previous != parent:
            raise InteropContractError(
                f"{child} has multiple required lineage parents: {previous!r}, {parent!r}"
            )

    def _validate_declared_parent(self, name: str, spec: ConceptSpec) -> None:
        """Reject a declared parent absent from required lineage."""
        if spec.parent is None or (spec.parent, name) in self.required_lineage:
            return
        parent = self.concepts[spec.parent]
        if spec.identity != parent.identity:
            raise InteropContractError(
                f"{name} declares parent {spec.parent!r} without required lineage"
            )

    def _validate_consumers(self) -> None:
        """Require milestone declarations to be spelled like M1/M3/M5."""
        for consumer, milestone in self.consumers.items():
            if not consumer.strip() or not _MILESTONE_RE.fullmatch(milestone):
                raise InteropContractError(
                    f"invalid consumer milestone declaration {consumer!r}: {milestone!r}"
                )

    def concept(self, name: str) -> ConceptSpec:
        """Return canonical metadata for ``name`` or fail loudly."""
        try:
            return self.concepts[name]
        except KeyError as exc:
            raise InteropContractError(f"unknown interoperability concept {name!r}") from exc

    def validate_projection(self, concept: str, projection: Mapping[str, object]) -> str:
        """Validate and return the canonical identity carried by a projection."""
        spec = self.concept(concept)
        if spec.identity not in projection:
            raise InteropContractError(
                f"{concept} projection must carry canonical identity field {spec.identity!r}"
            )
        value = projection[spec.identity]
        if not isinstance(value, str) or not value.strip():
            raise InteropContractError(f"{concept}.{spec.identity} must be a non-blank string")
        if spec.revision is not None:
            revision = projection.get(spec.revision)
            valid_string = isinstance(revision, str) and bool(revision.strip())
            valid_integer = (
                isinstance(revision, int) and not isinstance(revision, bool) and revision > 0
            )
            if not valid_string and not valid_integer:
                raise InteropContractError(
                    f"{concept} projection must carry canonical revision field {spec.revision!r}"
                )
        return value

    def validate_reference_set(self, references: Mapping[str, str]) -> None:
        """Require canonical parent/scope identities for supplied references."""
        required_parent = {child: parent for parent, child in self.required_lineage}
        for concept, value in references.items():
            spec = self.concept(concept)
            if not isinstance(value, str) or not value.strip():
                raise InteropContractError(f"{concept} reference must be a non-blank string")
            parent = required_parent.get(concept)
            if parent is not None and parent not in references:
                raise InteropContractError(
                    f"{concept} reference requires canonical parent {parent}"
                )
            if spec.scope is not None and spec.scope not in references:
                raise InteropContractError(
                    f"{concept} reference requires canonical scope {spec.scope}"
                )

    def require_compatible(self, version: str) -> None:
        """Require semantic-major compatibility with this ontology."""
        requested = _parse_version(version)
        current = _parse_version(self.version)
        if requested[0] != current[0]:
            raise InteropContractError(
                f"ontology version {version!r} is incompatible with {self.version!r}"
            )

    def as_dict(self) -> dict[str, object]:
        """Return the published JSON serialization of this contract."""
        return {
            "version": self.version,
            "status": self.status,
            "issue": self.issue,
            "principles": list(self.principles),
            "concepts": {name: spec.as_dict() for name, spec in self.concepts.items()},
            "relationships": {name: spec.as_dict() for name, spec in self.relationships.items()},
            "required_lineage": [list(edge) for edge in self.required_lineage],
            "consumers": dict(self.consumers),
        }


def validate_projection(
    ontology: InteropOntology, concept: str, projection: Mapping[str, object]
) -> str:
    """Module-level form of :meth:`InteropOntology.validate_projection`."""
    return ontology.validate_projection(concept, projection)


def validate_reference_set(ontology: InteropOntology, references: Mapping[str, str]) -> None:
    """Module-level form of :meth:`InteropOntology.validate_reference_set`."""
    return ontology.validate_reference_set(references)


def require_compatible(ontology: InteropOntology, version: str) -> None:
    """Module-level form of :meth:`InteropOntology.require_compatible`."""
    ontology.require_compatible(version)


def _parse_version(version: str) -> tuple[int, int, int]:
    """Return the semantic-major/minor/patch triple or fail loudly."""
    match = _VERSION_RE.fullmatch(version)
    if match is None:
        raise InteropContractError(f"ontology version must be semantic x.y.z, got {version!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


INTEROP_ONTOLOGY_V1 = InteropOntology(
    version="1.1.0",
    status="m1-freeze-candidate",
    issue=458,
    principles=(
        "one canonical identity per shared concept",
        "product-local DTOs may project but may not redefine shared semantics",
        "cross-product references use canonical IDs",
        "ownership and execution lineage survive product boundaries",
        "contract evolution is explicit and versioned",
    ),
    concepts={
        "Workspace": ConceptSpec("maistro.workspaces", "workspace_id"),
        "Project": ConceptSpec("maistro.projects", "project_id", parent="Workspace"),
        "Agent": ConceptSpec("maistro.agents", "agent_id", scope="Workspace"),
        "Persona": ConceptSpec("maistro.personas", "persona_id"),
        "Template": ConceptSpec("maistro.prompts", "template_id"),
        "Goal": ConceptSpec(
            "maistro.goals",
            "goal_id",
            parent="Project",
            revision="goal_revision",
        ),
        "Graph": ConceptSpec("maistro.graph", "graph_id", scope="Project"),
        "Run": ConceptSpec(
            "maistro.runs",
            "run_id",
            parent="Graph",
            scope="Project",
        ),
        "GraphExecutionState": ConceptSpec("maistro.graph", "run_id", parent="Run"),
        "NodeRun": ConceptSpec("maistro.runs", "node_run_id", parent="Run"),
        "Attempt": ConceptSpec("maistro.runs", "attempt_id", parent="NodeRun"),
        "ExecutionRuntime": ConceptSpec(
            "maistro.runtime",
            "execution_id",
            parent="Attempt",
        ),
        "Capability": ConceptSpec("maistro.capabilities", "capability_id"),
        "Provider": ConceptSpec("maistro.capabilities", "provider_id"),
        "Binding": ConceptSpec(
            "maistro.capabilities",
            "binding_id",
            parent="Provider",
        ),
        "Invocation": ConceptSpec(
            "maistro.capabilities",
            "invocation_id",
            parent="Binding",
        ),
    },
    relationships={
        "project_goal": RelationshipSpec(
            "Project",
            "Goal",
            "scope",
            "exactly-one",
            "zero-or-many",
        ),
        "agent_goal_ownership": RelationshipSpec(
            "Agent",
            "Goal",
            "accountability",
            "exactly-one",
            "zero-or-many",
        ),
        "goal_subgoal": RelationshipSpec(
            "Goal",
            "Goal",
            "subgoal",
            "zero-or-one",
            "zero-or-many",
        ),
        "goal_graph_selection": RelationshipSpec(
            "Goal",
            "Graph",
            "execution-strategy",
            "zero-or-many",
            "zero-or-many",
        ),
        "goal_run_evidence": RelationshipSpec(
            "Goal",
            "Run",
            "execution-evidence",
            "zero-or-one",
            "zero-or-many",
        ),
        "persona_agent_flavor": RelationshipSpec(
            "Persona",
            "Agent",
            "behavioral-flavor",
            "zero-or-one",
            "zero-or-many",
        ),
    },
    required_lineage=(
        ("Workspace", "Project"),
        ("Project", "Goal"),
        ("Project", "Graph"),
        ("Graph", "Run"),
        ("Run", "NodeRun"),
        ("NodeRun", "Attempt"),
        ("Attempt", "ExecutionRuntime"),
        ("Capability", "Provider"),
        ("Provider", "Binding"),
        ("Binding", "Invocation"),
    ),
    consumers={
        "builders": "M1",
        "conductor": "M1",
        "evolve": "M1",
        "canvas_design": "M1",
        "workspace_agent": "M3",
        "design_studio": "M3",
        "rsi": "M5",
    },
)
