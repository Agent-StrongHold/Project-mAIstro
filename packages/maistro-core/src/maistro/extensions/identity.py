"""Canonical extension identity, declarations, and invocation scope (#950).

These are the metadata half of the extension contract: who an extension is,
the maximum authority it declares, and the canonical execution identifiers of
the one invocation it is serving. Nothing here carries an object handle —
scope members are identifiers only, so a context can never become a store or
container lookup key into live machinery.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from maistro.extensions.errors import ScopeMismatch


def _require(label: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"extension {label} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class ExtensionIdentity:
    """Who an extension is, for provenance and refusal messages."""

    extension_id: str
    version: str

    def __post_init__(self) -> None:
        _require("id", self.extension_id)
        _require("version", self.version)

    @property
    def provenance(self) -> dict[str, str]:
        """The canonical event-envelope provenance payload for this extension."""
        return {
            "extension_id": self.extension_id,
            "extension_version": self.version,
        }


@dataclass(frozen=True, slots=True)
class ExtensionDescriptor:
    """The maximum authority an extension declares, and therefore can receive.

    Declaration is a ceiling, not a grant: the host must still grant every
    service and route every effect for the extension to reach it. A context
    refuses anything outside this descriptor regardless of what the host
    happens to hold, so extension code cannot obtain undeclared authority by
    importing SDK objects (epic #938 acceptance).
    """

    identity: ExtensionIdentity
    config_keys: frozenset[str] = field(default_factory=frozenset)
    services: frozenset[str] = field(default_factory=frozenset)
    effects: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        for group, keys in (
            ("config key", self.config_keys),
            ("service", self.services),
            ("effect", self.effects),
        ):
            for key in keys:
                _require(group, key)


@dataclass(frozen=True, slots=True)
class InvocationScope:
    """Canonical identifiers for one extension invocation.

    ``workspace_id``/``agent_id`` are the scope root and the accountable
    agent. ``run_id``/``node_run_id``/``attempt_id`` locate the physical
    execution on the canonical ``Graph → Run → NodeRun → Attempt`` chain and
    are exactly the correlation the governed Invocation seam requires. During
    activation — which happens outside any Attempt — the three execution
    members are empty; inside an invocation all three must be present, so a
    half-correlated scope can never exist.
    """

    workspace_id: str
    agent_id: str
    run_id: str = ""
    node_run_id: str = ""
    attempt_id: str = ""

    def __post_init__(self) -> None:
        _require("workspace_id", self.workspace_id)
        _require("agent_id", self.agent_id)
        execution = (self.run_id, self.node_run_id, self.attempt_id)
        if any(execution) and not all(execution):
            raise ScopeMismatch(
                "run_id, node_run_id, and attempt_id must be correlated: "
                "all empty (activation) or all present (invocation)"
            )

    @property
    def in_attempt(self) -> bool:
        """Whether this scope is bound to a physical Attempt execution."""
        return bool(self.run_id)

    @property
    def correlation(self) -> dict[str, str]:
        """The canonical event-envelope correlation fields for this scope."""
        return {
            "workspace_id": self.workspace_id,
            "run_id": self.run_id,
            "node_run_id": self.node_run_id,
            "attempt_id": self.attempt_id,
        }


__all__ = [
    "ExtensionDescriptor",
    "ExtensionIdentity",
    "InvocationScope",
]
