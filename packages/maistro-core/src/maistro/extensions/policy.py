"""Organization/Workspace extension policy, pinning, and tenancy (#971, M9-G3).

One server-side authority answers "may this org/Workspace run this extension
at all, and under which ceilings" — before #969's intersection narrows what
an enabled extension may do. The layers, resolved in a fixed order:

1. **organization registration** — an org unknown to extension policy is
   deny-by-default: canonical policy is server-side state, not UI truth,
   so a scope nobody configured enables nothing.
2. **org allowlist** — when the org states one, only listed extensions are
   eligible, regardless of Workspace enablement.
3. **org deny list** — an org deny overrides any Workspace enable request.
4. **publisher approval** — when the org names approved publishers, packages
   from any other publisher are refused.
5. **version pinning** — a pin is an exact-version requirement enforced
   server-side under concurrent callers: every resolution reads one
   immutable policy snapshot, so a caller can never observe a torn policy
   (half the pin swap, half the old table).
6. **Workspace enablement** — the Workspace-level allowlist; a Workspace
   that never enabled an extension runs nothing, and the org ceiling and
   the Workspace ceiling compose by intersection.

The result (:class:`ResolvedExtensionPolicy`) is a pure function of the
policy table and the requested identity: deterministic, explainable (every
refusal carries the layer reason, in the fixed order), and stable. Its
:meth:`ResolvedExtensionPolicy.workspace_layer` projects the resolution onto
the #969 :class:`~maistro.extensions.effective_authority.
WorkspaceExtensionPolicy` input, so an org deny becomes the intersection's
package blocker and an org ceiling can only narrow effective authority.

Two guarantees make cross-tenant noninterference structural rather than
hoped-for:

- the ledger swaps whole immutable snapshots (:class:`ExtensionPolicyTable`)
  and never mutates one in place — concurrent readers hold a consistent
  table, and tenants only ever read rows keyed by their own scope;
- per-tenant extension state (caches, checkpoints, configuration) lives in
  :class:`TenantScopedExtensionState`, keyed by ``(org_id, workspace_id)``
  with views that cannot reach another view's values.

Every ledger mutation appends an :class:`ExtensionPolicyAuditEvent` with
actor, scope, reason, and the digest of the table state it produced — the
admin inspection and policy audit trail the issue requires.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from types import MappingProxyType

from maistro.extensions.effective_authority import WorkspaceExtensionPolicy
from maistro.extensions.types import ExtensionRegistryError, ExtensionScope


class ExtensionPolicyError(ExtensionRegistryError):
    """A policy mutation or resolution was malformed or unauthorized."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_id(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExtensionPolicyError(f"{label} is required")
    return value


def _as_frozen(tokens: Iterable[str] | None) -> frozenset[str] | None:
    return frozenset(tokens) if tokens is not None else None


def _table_digest(table: ExtensionPolicyTable) -> str:
    """Stable digest over a policy snapshot — the audit row's table identity."""
    payload = {
        "orgs": {
            org_id: {
                "allowed": sorted(policy.allowed_extensions)
                if policy.allowed_extensions is not None
                else None,
                "ceiling": sorted(policy.permission_ceiling)
                if policy.permission_ceiling is not None
                else None,
                "denied": sorted(policy.denied_extensions),
                "pins": dict(sorted(policy.version_pins.items())),
                "publishers": sorted(policy.approved_publishers)
                if policy.approved_publishers is not None
                else None,
            }
            for org_id, policy in sorted(table.orgs.items())
        },
        "workspaces": {
            # JSON-encoded [org_id, workspace_id] pair: delimiter-free, so
            # IDs containing "/" cannot collide across distinct scopes.
            json.dumps([org_id, workspace_id]): {
                "ceiling": sorted(ov.permission_ceiling)
                if ov.permission_ceiling is not None
                else None,
                "enabled": sorted(ov.enabled_extensions),
            }
            for (org_id, workspace_id), ov in sorted(table.workspaces.items())
        },
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class OrgExtensionPolicy:
    """The organization's extension policy stance.

    ``allowed_extensions``/``approved_publishers`` use ``None`` to mean "no
    org-wide list" — ``None`` is *not* an empty allow-all, it is the absence
    of that layer. An org that states neither constrains enablement only
    through ``denied_extensions`` and ``version_pins``.
    """

    org_id: str
    #: Extensions denied outright; overrides any Workspace enable request.
    denied_extensions: frozenset[str] = frozenset()
    #: Org-wide allowlist; ``None`` defers eligibility to Workspace enablement.
    allowed_extensions: frozenset[str] | None = None
    #: Approved publishers; ``None`` admits any publisher trust admits.
    approved_publishers: frozenset[str] | None = None
    #: extension id -> exact semantic version the org pins the extension to.
    version_pins: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    #: Org-wide permission ceiling composed under every Workspace ceiling.
    permission_ceiling: frozenset[str] | None = None

    def __post_init__(self) -> None:
        _require_id(self.org_id, label="org_id")
        object.__setattr__(self, "denied_extensions", frozenset(self.denied_extensions))
        object.__setattr__(self, "allowed_extensions", _as_frozen(self.allowed_extensions))
        object.__setattr__(self, "approved_publishers", _as_frozen(self.approved_publishers))
        object.__setattr__(self, "permission_ceiling", _as_frozen(self.permission_ceiling))
        object.__setattr__(self, "version_pins", MappingProxyType(dict(self.version_pins)))


@dataclass(frozen=True)
class WorkspacePolicyOverride:
    """One Workspace's enablement and ceiling, under its org's policy."""

    org_id: str
    workspace_id: str
    #: Extensions this Workspace enabled — empty enables nothing.
    enabled_extensions: frozenset[str] = frozenset()
    #: Workspace permission ceiling; ``None`` inherits the org ceiling (and
    #: no ceiling at all when the org states none either).
    permission_ceiling: frozenset[str] | None = None

    def __post_init__(self) -> None:
        _require_id(self.org_id, label="org_id")
        _require_id(self.workspace_id, label="workspace_id")
        object.__setattr__(self, "enabled_extensions", frozenset(self.enabled_extensions))
        object.__setattr__(self, "permission_ceiling", _as_frozen(self.permission_ceiling))


@dataclass(frozen=True)
class ExtensionPolicyTable:
    """One immutable policy snapshot; resolution is a pure function of it.

    The ledger never mutates a table: every mutation swaps this whole
    snapshot, so a concurrent reader holds either the old or the new policy —
    never a torn one.
    """

    orgs: Mapping[str, OrgExtensionPolicy] = field(default_factory=lambda: MappingProxyType({}))
    workspaces: Mapping[tuple[str, str], WorkspacePolicyOverride] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "orgs", MappingProxyType(dict(self.orgs)))
        object.__setattr__(self, "workspaces", MappingProxyType(dict(self.workspaces)))


@dataclass(frozen=True)
class ExtensionPolicyAuditEvent:
    """One appended policy change, with the table state it produced."""

    seq: int
    action: str
    org_id: str
    workspace_id: str
    actor: str
    reason: str
    at: datetime
    #: Digest of the policy table this event produced — joins audit rows to
    #: the exact policy every concurrent resolution around them read.
    table_digest: str


@dataclass(frozen=True)
class ResolvedExtensionPolicy:
    """The explainable answer for one extension identity in one scope.

    ``enabled`` is true exactly when no layer refused; ``reasons`` is empty
    exactly then, and otherwise lists every refusing layer in the fixed
    resolution order. ``permission_ceiling`` is the org ∩ Workspace ceiling,
    or ``None`` when neither level states one.
    """

    extension_id: str
    version: str
    publisher: str
    scope: ExtensionScope
    enabled: bool
    reasons: tuple[str, ...] = ()
    #: The org pin this resolution was checked against, when one exists.
    pin: str | None = None
    #: The composed org ∩ Workspace permission ceiling; ``None`` = unstated.
    permission_ceiling: frozenset[str] | None = None

    def workspace_layer(self, requested: Iterable[str]) -> WorkspaceExtensionPolicy:
        """Project this resolution onto the #969 Workspace-policy layer.

        ``requested`` is the manifest's requested permission universe (what
        the caller has from the manifest snapshot). A resolution without a
        configured ceiling yields exactly the request — matching a
        deployment that states no Workspace ceiling — and a configured
        ceiling intersects it. A denied resolution yields an empty
        enablement, which #969 turns into a package blocker.
        """
        requested_set = frozenset(requested)
        if not self.enabled:
            return WorkspaceExtensionPolicy(
                scope=self.scope,
                enabled_extensions=frozenset(),
                permission_ceiling=requested_set,
            )
        ceiling = (
            requested_set & self.permission_ceiling
            if self.permission_ceiling is not None
            else requested_set
        )
        return WorkspaceExtensionPolicy(
            scope=self.scope,
            enabled_extensions=frozenset({self.extension_id}),
            permission_ceiling=ceiling,
        )


_FIXED_RESOLUTION_LAYERS = (
    "org registration",
    "org allowlist",
    "org deny",
    "publisher approval",
    "version pin",
    "workspace enablement",
)


def _org_layer_reasons(
    org: OrgExtensionPolicy, *, extension_id: str, publisher: str, version: str
) -> tuple[list[str], str | None]:
    """The org layers' refusals, in the fixed order, plus the pin if any."""
    reasons: list[str] = []
    pin: str | None = None
    if org.allowed_extensions is not None and extension_id not in org.allowed_extensions:
        reasons.append(f"org {org.org_id!r} allowlist excludes {extension_id!r}")
    if extension_id in org.denied_extensions:
        reasons.append(
            f"org {org.org_id!r} denies {extension_id!r} (overrides workspace enablement)"
        )
    if org.approved_publishers is not None and publisher not in org.approved_publishers:
        reasons.append(f"publisher {publisher!r} is not approved by org {org.org_id!r}")
    pinned = org.version_pins.get(extension_id)
    if pinned is not None:
        pin = pinned
        if version != pinned:
            reasons.append(
                f"org {org.org_id!r} pins {extension_id!r} to {pinned!r}, not {version!r}"
            )
    return reasons, pin


def resolve_extension_policy(
    table: ExtensionPolicyTable,
    *,
    extension_id: str,
    version: str,
    publisher: str,
    org_id: str,
    workspace_id: str,
) -> ResolvedExtensionPolicy:
    """Resolve one extension identity against one immutable policy table.

    Pure function: the same table and identity always produce an equal
    result, which is what makes policy inheritance deterministic and the
    resolution safely re-derivable from audit evidence. The org pin, when
    present, is enforced here — server-side, before any caller-specific
    logic can run.
    """
    _require_id(extension_id, label="extension_id")
    _require_id(version, label="version")
    _require_id(publisher, label="publisher")
    _require_id(org_id, label="org_id")
    _require_id(workspace_id, label="workspace_id")

    scope = ExtensionScope(org_id=org_id, workspace_id=workspace_id)
    reasons: list[str] = []
    pin: str | None = None

    org = table.orgs.get(org_id)
    if org is None:
        reasons.append(f"org {org_id!r} is not registered with extension policy")
    else:
        org_reasons, pin = _org_layer_reasons(
            org, extension_id=extension_id, publisher=publisher, version=version
        )
        reasons.extend(org_reasons)

    override = table.workspaces.get((org_id, workspace_id))
    if override is None:
        reasons.append(f"workspace {scope.describe} is not registered with extension policy")
    elif extension_id not in override.enabled_extensions:
        reasons.append(f"{extension_id!r} is not enabled in {scope.describe}")

    ceiling: frozenset[str] | None = None
    if org is not None and org.permission_ceiling is not None:
        ceiling = frozenset(org.permission_ceiling)
    if override is not None and override.permission_ceiling is not None:
        ceiling = (
            frozenset(override.permission_ceiling)
            if ceiling is None
            else ceiling & override.permission_ceiling
        )

    return ResolvedExtensionPolicy(
        extension_id=extension_id,
        version=version,
        publisher=publisher,
        scope=scope,
        enabled=not reasons,
        reasons=tuple(reasons),
        pin=pin,
        permission_ceiling=ceiling,
    )


class ExtensionPolicyLedger:
    """Server-side authority for org/Workspace extension policy (#971).

    Holds the current immutable :class:`ExtensionPolicyTable` and an
    append-only audit trail. Mutations are synchronous table swaps — no
    await between reading and replacing — so under concurrent asyncio
    callers every :meth:`resolve` observes exactly one whole table, and
    pinning is enforced against a consistent snapshot however the callers
    interleave. Readers cannot mutate: resolution takes only the table, and
    the ledger exposes no in-place edit of a published snapshot.
    """

    def __init__(self, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock
        self._table = ExtensionPolicyTable()
        self._audit: list[ExtensionPolicyAuditEvent] = []
        self._seq = 0

    @property
    def table(self) -> ExtensionPolicyTable:
        """The current policy snapshot."""
        return self._table

    @property
    def table_digest(self) -> str:
        """Digest of the current policy snapshot."""
        return _table_digest(self._table)

    def set_org_policy(self, policy: OrgExtensionPolicy, *, actor: str, reason: str) -> int:
        """Record the org's policy, replacing any previous one, and audit it."""
        _require_id(actor, label="actor")
        _require_id(reason, label="reason")
        table = ExtensionPolicyTable(
            orgs={**self._table.orgs, policy.org_id: policy},
            workspaces=self._table.workspaces,
        )
        return self._swap(
            table,
            action="org_policy_set",
            org_id=policy.org_id,
            workspace_id="",
            actor=actor,
            reason=reason,
        )

    def set_workspace_override(
        self, override: WorkspacePolicyOverride, *, actor: str, reason: str
    ) -> int:
        """Record one Workspace's enablement/ceiling, replacing any previous."""
        _require_id(actor, label="actor")
        _require_id(reason, label="reason")
        if override.org_id not in self._table.orgs:
            raise ExtensionPolicyError(
                f"org {override.org_id!r} is not registered; set its policy first"
            )
        table = ExtensionPolicyTable(
            orgs=self._table.orgs,
            workspaces={
                **self._table.workspaces,
                (override.org_id, override.workspace_id): override,
            },
        )
        return self._swap(
            table,
            action="workspace_override_set",
            org_id=override.org_id,
            workspace_id=override.workspace_id,
            actor=actor,
            reason=reason,
        )

    def pin_version(
        self, *, org_id: str, extension_id: str, version: str, actor: str, reason: str
    ) -> int:
        """Pin one extension to an exact version under an org's policy."""
        _require_id(actor, label="actor")
        _require_id(reason, label="reason")
        _require_id(version, label="version")
        org = self._table.orgs.get(org_id)
        if org is None:
            raise ExtensionPolicyError(f"org {org_id!r} is not registered")
        updated = replace(org, version_pins={**org.version_pins, extension_id: version})
        table = ExtensionPolicyTable(
            orgs={**self._table.orgs, org_id: updated}, workspaces=self._table.workspaces
        )
        return self._swap(
            table,
            action="version_pinned",
            org_id=org_id,
            workspace_id="",
            actor=actor,
            reason=reason,
        )

    def resolve(
        self,
        *,
        extension_id: str,
        version: str,
        publisher: str,
        org_id: str,
        workspace_id: str,
    ) -> ResolvedExtensionPolicy:
        """Resolve against the current snapshot (see the module function)."""
        return resolve_extension_policy(
            self._table,
            extension_id=extension_id,
            version=version,
            publisher=publisher,
            org_id=org_id,
            workspace_id=workspace_id,
        )

    def audit(self, *, org_id: str | None = None) -> tuple[ExtensionPolicyAuditEvent, ...]:
        """The retained audit trail, optionally narrowed to one org."""
        if org_id is None:
            return tuple(self._audit)
        return tuple(event for event in self._audit if event.org_id == org_id)

    def _swap(
        self,
        table: ExtensionPolicyTable,
        *,
        action: str,
        org_id: str,
        workspace_id: str,
        actor: str,
        reason: str,
    ) -> int:
        self._seq += 1
        event = ExtensionPolicyAuditEvent(
            seq=self._seq,
            action=action,
            org_id=org_id,
            workspace_id=workspace_id,
            actor=actor,
            reason=reason,
            at=self._clock(),
            table_digest=_table_digest(table),
        )
        self._table = table
        self._audit.append(event)
        return self._seq


def tenant_scope_key(org_id: str, workspace_id: str) -> tuple[str, str]:
    """The tenant key every tenant-scoped extension seam must be namespaced by.

    The org is mandatory (an install nobody is the authority for cannot be
    recorded — :class:`~maistro.extensions.types.ExtensionScope`); the
    Workspace may be blank for org-wide scope, but the key still separates
    org-wide from per-Workspace state.
    """
    _require_id(org_id, label="org_id")
    if not isinstance(workspace_id, str):
        raise ExtensionPolicyError("workspace_id must be a string")
    return (org_id, workspace_id)


class TenantScopedExtensionState:
    """Tenant-keyed extension state: caches, checkpoints, configuration (#971).

    All state is namespaced by ``(org_id, workspace_id)``. A view handed to
    one tenant can only touch that tenant's slice — there is no API by which
    a view names another scope, and no shared default bucket two Workspaces
    could collide in. Two Workspaces enabling the same extension therefore
    cannot observe each other's state, whatever key they use inside their
    own slice.
    """

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], dict[str, object]] = {}

    def view(self, org_id: str, workspace_id: str) -> TenantStateView:
        """The isolated state view for exactly this tenant scope."""
        key = tenant_scope_key(org_id, workspace_id)
        bucket = self._buckets.setdefault(key, {})
        return TenantStateView(key, bucket)


@dataclass(frozen=True)
class _ViewKey:
    org_id: str
    workspace_id: str


class TenantStateView:
    """One tenant's isolated slice of :class:`TenantScopedExtensionState`."""

    def __init__(self, key: tuple[str, str], bucket: dict[str, object]) -> None:
        self._key = _ViewKey(org_id=key[0], workspace_id=key[1])
        self._bucket = bucket

    @property
    def scope(self) -> ExtensionScope:
        return ExtensionScope(org_id=self._key.org_id, workspace_id=self._key.workspace_id)

    def get(self, key: str, default: object = None) -> object:
        return self._bucket.get(key, default)

    def put(self, key: str, value: object) -> None:
        _require_id(key, label="state key")
        self._bucket[key] = value

    def pop(self, key: str, default: object = None) -> object:
        return self._bucket.pop(key, default)

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._bucket))
