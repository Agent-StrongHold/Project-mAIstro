"""Policy-conformance engine core types (SPEC-206 / ADR-074)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class Authority(StrEnum):
    """The precedence order a candidate policy decision is checked against."""

    ADR = "adr"
    SPEC = "spec"
    PRIOR_POLICY = "prior_policy"


@dataclass(frozen=True)
class PolicyDecision:
    """A candidate policy decision to be checked for conformance."""

    action: str
    scope: str
    reversibility: str
    allowed: bool
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Invariant:
    """A machine-checkable assertion an ADR or Spec exposes for conformance checking."""

    id: str
    authority_ref: str
    action: str
    scope: str
    safety_critical: bool = False
    checker: Callable[[PolicyDecision], bool] | None = None


@dataclass(frozen=True)
class ConformanceVerdict:
    """The result of checking a candidate decision against the authority precedence walk."""

    ok: bool
    conflict_layer: Authority | None = None
    conflict_ref: str | None = None
    safety_critical: bool = False
    artifacts: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)


class PriorPolicyStore(Protocol):
    """Queries prior policy decisions for precedent conflicts with a candidate."""

    def find_conflict(self, candidate: PolicyDecision) -> str | None:
        """Return a reference to the conflicting prior decision, or None if none conflicts."""
        ...


class ArtifactResolver(Protocol):
    """Resolves the deployed artifacts that depend on a conflicting authority."""

    def artifacts_for(self, conflict_ref: str) -> tuple[str, ...]:
        """Return the artifact identifiers that depend on the given authority reference."""
        ...


class NoopArtifactResolver:
    """An ArtifactResolver that always reports no dependent artifacts."""

    def artifacts_for(self, conflict_ref: str) -> tuple[str, ...]:
        """Return an empty tuple; no artifact resolution is wired in."""
        return ()
