"""Canonical identity/Workspace/Invocation test fixtures (#974).

Deterministic, synthetic stand-ins for the canonical data an extension's
context may expose. Two boundaries, stated plainly:

- **These are fixtures, not records.** Nothing here is written to any store,
  and the canonical execution model (`Goal -> Graph -> Run -> NodeRun ->
  Attempt`) is never instantiated: the harness does not create Runs, claim
  Attempts, or record events. An `InvocationFixture` is an opaque
  correlation handle for local simulation only — it is not canonical Run
  evidence and must never be presented as one.
- **Values are deterministic** so a conformance report from two machines is
  comparable line for line; every id carries the `fx-` prefix, which
  namespaces the synthetic values away from anything a real deployment
  mints.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "FIXTURE_PREFIX",
    "FixtureSet",
    "IdentityFixture",
    "InvocationFixture",
    "WorkspaceFixture",
    "reference_fixtures",
]

FIXTURE_PREFIX = "fx-"


def _fx(name: str) -> str:
    return f"{FIXTURE_PREFIX}{name}"


@dataclass(frozen=True)
class IdentityFixture:
    """Agent identity metadata — the `agent.read` projection."""

    principal_id: str = _fx("principal")
    agent_id: str = _fx("agent")
    display_name: str = "Conformance Fixture Agent"


@dataclass(frozen=True)
class WorkspaceFixture:
    """Workspace metadata — the `workspace.read` projection."""

    workspace_id: str = _fx("workspace")
    name: str = "Conformance Fixture Workspace"


@dataclass(frozen=True)
class InvocationFixture:
    """Invocation correlation — the `run.read` projection, as a fixture.

    `invocation_id` correlates the simulated call; `node_ref` names the
    NodeRun shape the host *would* project. Both are synthetic values: the
    harness never touches a canonical Run store.
    """

    invocation_id: str = _fx("invocation")
    node_ref: str = _fx("noderun")
    cancel_requested: bool = False


@dataclass(frozen=True)
class FixtureSet:
    """The three fixtures together, so cases construct one context each."""

    identity: IdentityFixture = field(default_factory=IdentityFixture)
    workspace: WorkspaceFixture = field(default_factory=WorkspaceFixture)
    invocation: InvocationFixture = field(default_factory=InvocationFixture)


def reference_fixtures() -> FixtureSet:
    """The canonical fixture triple every conformance case runs against."""
    return FixtureSet()
