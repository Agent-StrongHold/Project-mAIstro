"""The extension context: what a loaded handler can see (#974).

The context is the seam — per the lifecycle guide, "there is no second way
to reach product state". A conformance host proves that structurally: the
context exposes **only** what the grant carries, built from the canonical
fixtures in `maistro_ext_harness.fixtures`.

What is deliberately absent: memory stores, tool dispatch, network egress,
secret values. Those capabilities exist in the vocabulary, but the harness
does not simulate honest versions of them locally — a property that needs a
real backend is a real-backend case (`maistro_ext_harness.backends`), and
the report distinguishes what actually executed. An absent seam is the
honest local version of "not granted a second way in".
"""

from __future__ import annotations

from dataclasses import dataclass

from maistro_ext_harness.fixtures import (
    IdentityFixture,
    InvocationFixture,
    WorkspaceFixture,
)
from maistro_ext_harness.grants import Grant

__all__ = [
    "ExtensionContext",
    "IdentityView",
    "InvocationView",
    "WorkspaceView",
    "build_context",
]


@dataclass(frozen=True)
class IdentityView:
    """Identity metadata, visible only under `agent.read`."""

    principal_id: str
    agent_id: str
    display_name: str


@dataclass(frozen=True)
class WorkspaceView:
    """Workspace metadata, visible only under `workspace.read`."""

    workspace_id: str
    name: str


@dataclass(frozen=True)
class InvocationView:
    """Invocation correlation, visible only under `run.read`.

    `cancel_requested` is the host's cancellation signal: once the host has
    cancelled the invocation, a well-behaved handler stops instead of
    continuing (the runner's cancellation case refuses to call a handler at
    all once cancellation is requested — the host side of that contract).
    """

    invocation_id: str
    node_ref: str
    cancel_requested: bool


@dataclass(frozen=True)
class ExtensionContext:
    """Everything one handler invocation may reach.

    Constructed only by `build_context` from a grant plus fixtures. The
    views are `None` unless their capability was granted — an undeclared
    capability is not merely denied, it is invisible: `has_capability`
    answers for granted names and nothing else, and no accessor exists
    through which a handler could ask for more.
    """

    capabilities: frozenset[str]
    identity: IdentityView | None
    workspace: WorkspaceView | None
    invocation: InvocationView | None

    def has_capability(self, name: str) -> bool:
        """Whether `name` is among the granted capabilities."""
        return name in self.capabilities


def build_context(
    grant: Grant,
    *,
    identity: IdentityFixture,
    workspace: WorkspaceFixture,
    invocation: InvocationFixture,
) -> ExtensionContext:
    """Project the fixtures through the grant: nothing granted, nothing shown.

    This is the least-authority construction the security cases assert:
    `workspace` is None without `workspace.read` even though the fixture
    exists, and so on for the other two views.
    """
    return ExtensionContext(
        capabilities=grant.capabilities,
        identity=(
            IdentityView(
                principal_id=identity.principal_id,
                agent_id=identity.agent_id,
                display_name=identity.display_name,
            )
            if grant.has_capability("agent.read")
            else None
        ),
        workspace=(
            WorkspaceView(workspace_id=workspace.workspace_id, name=workspace.name)
            if grant.has_capability("workspace.read")
            else None
        ),
        invocation=(
            InvocationView(
                invocation_id=invocation.invocation_id,
                node_ref=invocation.node_ref,
                cancel_requested=invocation.cancel_requested,
            )
            if grant.has_capability("run.read")
            else None
        ),
    )
