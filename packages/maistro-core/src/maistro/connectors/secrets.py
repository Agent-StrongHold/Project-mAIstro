"""Secret authority seam for the connector SDK (M9-E2, issue #963).

Connector code never receives secret material up front. It declares
:class:`~maistro.connectors.types.SecretRef` requirements on its descriptor,
and at sync time resolves them by name through the session — which refuses
names the descriptor does not declare and delegates the lookup to whatever
authority the host bound. The host binds its canonical secret backend
(``maistro.protocols.secrets.SecretBackend``) behind the tiny
:class:`SecretAuthority` port below; the SDK never imports a concrete backend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from maistro.connectors.types import ConnectorScopeError, SecretRef

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Mapping


@runtime_checkable
class SecretAuthority(Protocol):
    """Resolve one declared secret ref for one Workspace.

    Implementations raise ``LookupError`` when the (workspace, ref) pair has
    no provisioned value — a missing secret is an operator problem, not a
    scope violation, so it keeps its own error type.
    """

    async def resolve(self, ref: SecretRef, *, workspace_id: str) -> str:
        """Return the current value of ``ref`` scoped to ``workspace_id``."""
        ...


class StaticSecretAuthority:
    """Mapping-backed reference authority: keys are ``(workspace_id, name)``.

    Used by the shared conformance suite and by tests. Production hosts adapt
    their canonical secret backend instead — this class exists so the port has
    at least one working implementation in-tree.
    """

    def __init__(self, values: Mapping[tuple[str, str], str]) -> None:
        self.values = dict(values)

    async def resolve(self, ref: SecretRef, *, workspace_id: str) -> str:
        """Return the provisioned value, or raise ``LookupError``."""
        try:
            return self.values[(workspace_id, ref.name)]
        except KeyError:
            msg = f"no secret provisioned for {ref.name!r} in workspace {workspace_id!r}"
            raise LookupError(msg) from None


def require_declared_secret(descriptor_refs: tuple[SecretRef, ...], name: str) -> SecretRef:
    """Return the declared ref matching ``name``, or refuse with a scope error.

    This is the whole undeclared-secret boundary: resolution is only reachable
    through names that appear on the connector's own descriptor, so a
    connector that never declared a secret can never read one, regardless of
    what the authority would have answered.
    """
    for ref in descriptor_refs:
        if ref.name == name:
            return ref
    msg = f"secret {name!r} is not declared on this connector's descriptor"
    raise ConnectorScopeError(msg)
