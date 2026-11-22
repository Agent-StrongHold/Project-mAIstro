"""Workspace scoping and the session object connector code runs against.

Two declarations meet here and neither can silently widen the other:

* the connector's :class:`~maistro.connectors.types.ConnectorDescriptor`
  declares which secret names it needs;
* the host's :class:`ConnectorInstance` binds one installed connector to an
  explicit allowlist of Workspaces and a secret authority.

The host only ever hands connector code a :class:`ConnectorSession` that is
already bound to one Workspace. There is no API on the session to re-scope it,
so an out-of-tree connector has no code path to touch an undeclared Workspace;
asking the engine to sync one raises :class:`ConnectorScopeError` before the
connector is invoked.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from maistro.connectors.secrets import require_declared_secret
from maistro.connectors.types import ConnectorScopeError, SecretRef

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.connectors.secrets import SecretAuthority
    from maistro.connectors.types import ConnectorDescriptor


@dataclass(frozen=True)
class ConnectorInstance:
    """One installed connector bound to its Workspaces and secret authority.

    ``workspace_ids`` is the allowlist the installer declared — the exact set
    of Workspaces this installation may ingest into. The engine checks it
    before every connector invocation; nothing else can widen it because the
    instance is frozen.
    """

    descriptor: ConnectorDescriptor
    workspace_ids: frozenset[str] = field(default_factory=frozenset)
    secrets: SecretAuthority | None = None


@dataclass(frozen=True)
class ConnectorSession:
    """The per-sync handle connector code receives; bound to one Workspace.

    ``resolve_secret`` is the only way connector code reaches secret material,
    and it refuses every name that is not declared on the descriptor — the
    authority behind the session never sees an undeclared request.
    """

    descriptor: ConnectorDescriptor
    workspace_id: str
    config_id: str
    config: Mapping[str, str] = field(default_factory=dict)
    _secrets: SecretAuthority | None = field(default=None, repr=False)

    @classmethod
    def create(
        cls,
        instance: ConnectorInstance,
        *,
        workspace_id: str,
        config_id: str,
        config: Mapping[str, str],
    ) -> ConnectorSession:
        """Bind a session for ``workspace_id``; refuse undeclared Workspaces.

        The engine's single session factory. It re-checks the instance
        allowlist even though ``SyncEngine.run`` already did: one check is
        policy, two make the boundary hold for every future caller of the
        factory.
        """
        if workspace_id not in instance.workspace_ids:
            msg = (
                f"workspace {workspace_id!r} is not declared for connector "
                f"{instance.descriptor.connector_id!r}"
            )
            raise ConnectorScopeError(msg)
        return cls(
            descriptor=instance.descriptor,
            workspace_id=workspace_id,
            config_id=config_id,
            config=dict(config),
            _secrets=instance.secrets,
        )

    async def resolve_secret(self, name: str) -> str:
        """Resolve a declared secret by name for this session's Workspace.

        Raises :class:`ConnectorScopeError` for a name the descriptor does not
        declare and ``LookupError`` when a declared name has no provisioned
        value. With no authority bound (an instance installed without one),
        every declared name is unprovisioned.
        """
        ref: SecretRef = require_declared_secret(self.descriptor.secret_refs, name)
        if self._secrets is None:
            msg = f"secret {name!r} declared but no secret authority is bound"
            raise LookupError(msg)
        return await self._secrets.resolve(ref, workspace_id=self.workspace_id)


@dataclass(frozen=True)
class SyncContext:
    """What a connector sees on one host-driven call.

    ``cursor`` carries the incremental checkpoint to resume from (``None`` on
    a first sync); ``query`` carries the query string on QUERY-capability
    calls. Connectors read scope off ``session`` and never receive the
    instance or the engine.
    """

    session: ConnectorSession
    cursor: str | None = None
    query: str | None = None
