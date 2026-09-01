"""Executable cross-product interoperability ontology (#458).

The registry is metadata over existing canonical owners. It deliberately does
not define replacement Workspace, Project, Graph, Run, Capability, or product
DTOs.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_MILESTONE_RE = re.compile(r"^M(?:0|[1-9]\d*)$")


class InteropContractError(ValueError):
    """Raised when an ontology or product projection violates the contract."""


@dataclass(frozen=True, slots=True)
class ConceptSpec:
    """Canonical owner/identity metadata for one shared concept."""

    owner: str
    identity: str
    parent: str | None = None
    scope: str | None = None

    def as_dict(self) -> dict[str, str]:
        result = {"owner": self.owner, "identity": self.identity}
        if self.scope is not None:
            result["scope"] = self.scope
        if self.parent is not None:
            result["parent"] = self.parent
        return result


@dataclass(frozen=True, slots=True)
class InteropOntology:
    """Versioned registry of canonical cross-product identities and lineage."""

    version: str
    status: str
    issue: int
    principles: tuple[str, ...]
    concepts: Mapping[str, ConceptSpec]
    required_lineage: tuple[tuple[str, str], ...]
    consumers: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "concepts", MappingProxyType(dict(self.concepts)))
        object.__setattr__(self, "consumers", MappingProxyType(dict(self.consumers)))
        self._validate_definition()

    def _validate_definition(self) -> None:
        _parse_version(self.version)
        self._validate_header()
        self._validate_concepts()
        self._validate_lineage()
        self._validate_consumers()

    def _validate_header(self) -> None:
        if self.issue <= 0:
            raise InteropContractError("ontology issue must be a positive integer")
        if not self.status.strip():
            raise InteropContractError("ontology status must be non-blank")
        if not self.principles or any(not item.strip() for item in self.principles):
            raise InteropContractError("ontology principles must be non-empty strings")
        if not self.concepts:
            raise InteropContractError("ontology must define at least one concept")

    def _validate_concepts(self) -> None:
        for name, spec in self.concepts.items():
            self._validate_concept(name, spec)

    def _validate_concept(self, name: str, spec: ConceptSpec) -> None:
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
        for relation, target in (("parent", spec.parent), ("scope", spec.scope)):
            if target is not None and target not in self.concepts:
                raise InteropContractError(
                    f"{name} {relation} references unknown concept {target!r}"
                )

    def _validate_lineage(self) -> None:
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
        if spec.parent is None or (spec.parent, name) in self.required_lineage:
            return
        parent = self.concepts[spec.parent]
        if spec.identity != parent.identity:
            raise InteropContractError(
                f"{name} declares parent {spec.parent!r} without required lineage"
            )

    def _validate_consumers(self) -> None:
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
        """Return the canonical identity carried by a product projection."""
        spec = self.concept(concept)
        if spec.identity not in projection:
            raise InteropContractError(
                f"{concept} projection must carry canonical identity field {spec.identity!r}"
            )
        value = projection[spec.identity]
        if not isinstance(value, str) or not value.strip():
            raise InteropContractError(f"{concept}.{spec.identity} must be a non-blank string")
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
            "required_lineage": [list(edge) for edge in self.required_lineage],
            "consumers": dict(self.consumers),
        }


def _parse_version(version: str) -> tuple[int, int, int]:
    match = _VERSION_RE.fullmatch(version)
    if match is None:
        raise InteropContractError(
            f"ontology version must be semantic x.y.z, got {version!r}"
        )
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


INTEROP_ONTOLOGY_V1 = InteropOntology(
    version="1.0.0",
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
        "Persona": ConceptSpec("maistro.personas", "persona_id"),
        "Template": ConceptSpec("maistro.prompts", "template_id"),
        "Graph": ConceptSpec("maistro.graph", "graph_id", scope="Project"),
        "Run": ConceptSpec("maistro.runs", "run_id", parent="Graph", scope="Project"),
        "GraphExecutionState": ConceptSpec("maistro.graph", "run_id", parent="Run"),
        "NodeRun": ConceptSpec("maistro.runs", "node_run_id", parent="Run"),
        "Attempt": ConceptSpec("maistro.runs", "attempt_id", parent="NodeRun"),
        "ExecutionRuntime": ConceptSpec("maistro.runtime", "execution_id", parent="Attempt"),
        "Capability": ConceptSpec("maistro.capabilities", "capability_id"),
        "Provider": ConceptSpec("maistro.capabilities", "provider_id", parent="Capability"),
        "Binding": ConceptSpec("maistro.capabilities", "binding_id", parent="Provider"),
        "Invocation": ConceptSpec("maistro.capabilities", "invocation_id", parent="Binding"),
    },
    required_lineage=(
        ("Workspace", "Project"),
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
        "rsi": "M5",
    },
)
