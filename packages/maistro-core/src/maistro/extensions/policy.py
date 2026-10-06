"""Organization/Workspace extension policy, pinning, and audit (#971, M9-G3).

The server-side policy layer over the governed install machine (M9-B2): an
organization states which extensions may run at all — and, once running,
exactly which publisher/version identity is pinned — and each Workspace may
only *narrow* that: opt-in enablement and permission ceilings.

Resolution is a fixed rule order, evaluated top to bottom, with every rule's
outcome recorded on the decision trace:

1. ``org.deny-list`` — an organization denial cannot be overridden by any
   Workspace request (the acceptance rule "org deny overrides Workspace
   enablement");
2. ``org.allow-list`` — when configured, everything not on it is denied;
3. ``org.approved-publishers`` — when configured, other publishers are denied;
4. ``org.version-pin`` / ``org.publisher-pin`` — a pin binds the exact
   publisher (and optionally version) an extension may install under;
5. ``workspace.deny-list``;
6. ``workspace.enablement`` — a Workspace *with* a policy must have enabled
   the extension; a Workspace *without* one inherits the organization layer
   unchanged;
7. ``workspace.permission-ceiling`` — requested permissions outside the
   extension's ceiling fail closed; nothing is silently truncated.

A layer with no configured policy imposes nothing and says so on the trace,
so every decision is explainable from its own record. Every evaluation and
every policy change is appended to a :class:`PolicyAuditLog` — the admin
inspection and policy audit trail the issue requires.

Concurrency: policy mutations and the install machine's enforcement critical
sections serialize on a per-organization :class:`asyncio.Lock` (see
:meth:`ExtensionPolicyEngine.enforcement_window`). A pin change therefore
either lands entirely before an install's decision (the install is refused)
or entirely after it (the install ran while the pin did not exist) —
version/publisher pinning is enforced server-side under concurrent callers,
never checked-then-raced.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from maistro.extensions.authority import normalize_permission
from maistro.extensions.types import ExtensionScope


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PolicyLayer(StrEnum):
    """Which policy layer produced a trace entry."""

    ORG = "org"
    WORKSPACE = "workspace"


class PolicyVerdict(StrEnum):
    """The outcome of a policy evaluation."""

    ALLOW = "allow"
    DENY = "deny"


class PolicyConfigurationError(ValueError):
    """A policy would be recorded in a form that cannot be evaluated."""


@dataclass(frozen=True)
class ExtensionPin:
    """An organization's approved identity for one extension.

    ``publisher_id`` is always pinned: only that publisher may ship the
    extension. ``version``, when set, additionally pins the exact version —
    upgrades require an organization policy change, not a Workspace request.
    """

    publisher_id: str
    version: str | None = None


@dataclass(frozen=True)
class ExtensionCandidate:
    """The manifest-derived facts a policy decision is about."""

    extension_id: str
    version: str
    publisher: str
    permissions: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrgExtensionPolicy:
    """The organization layer: absolute gates no Workspace can widen.

    ``allowed_extensions=None`` means default-allow (the deny-list alone
    governs); a set means default-deny outside it. The same ``None``-vs-set
    duality applies to ``approved_publishers``.
    """

    org_id: str
    allowed_extensions: frozenset[str] | None = None
    denied_extensions: frozenset[str] = frozenset()
    approved_publishers: frozenset[str] | None = None
    pins: Mapping[str, ExtensionPin] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkspaceExtensionPolicy:
    """The Workspace layer: enablement and ceilings that only narrow.

    The presence of a Workspace policy switches that Workspace to opt-in
    enablement: extensions it has not enabled are denied there even when the
    organization allows them. A Workspace without a policy inherits the
    organization layer unchanged.
    """

    org_id: str
    workspace_id: str
    enabled_extensions: frozenset[str] = frozenset()
    denied_extensions: frozenset[str] = frozenset()
    #: extension_id -> the maximum permission set the Workspace will hold.
    #: A requested permission outside the ceiling fails closed.
    permission_ceilings: Mapping[str, frozenset[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyRuleOutcome:
    """One rule's result on one decision — the decision's explanation unit."""

    layer: PolicyLayer
    rule: str
    denied: bool
    detail: str


@dataclass(frozen=True)
class PolicyDecision:
    """The deterministic, explainable answer for one candidate in one scope."""

    org_id: str
    workspace_id: str
    extension_id: str
    version: str
    publisher: str
    requested_permissions: tuple[str, ...]
    verdict: PolicyVerdict
    trace: tuple[PolicyRuleOutcome, ...]

    @property
    def allowed(self) -> bool:
        """Whether the request may proceed."""
        return self.verdict is PolicyVerdict.ALLOW

    @property
    def explanation(self) -> str:
        """A one-line, self-contained reason for the verdict."""
        if self.verdict is PolicyVerdict.DENY:
            return "; ".join(outcome.detail for outcome in self.trace if outcome.denied)
        evaluated = ", ".join(outcome.rule for outcome in self.trace)
        return f"no policy rule denied the request (evaluated: {evaluated})"


@dataclass(frozen=True)
class PolicyAuditEvent:
    """One appended row of the policy audit trail."""

    seq: int
    at: datetime
    actor: str
    #: ``org-policy-set``, ``workspace-policy-set``, or ``decision``.
    kind: str
    org_id: str
    workspace_id: str
    extension_id: str
    detail: str


class PolicyAuditLog:
    """Append-only in-memory policy audit trail (#971).

    Decisions and policy changes are evidence: rows are never rewritten or
    removed, only appended and read back filtered.
    """

    def __init__(self) -> None:
        self._events: list[PolicyAuditEvent] = []
        self._seq = 0

    def append(
        self,
        *,
        at: datetime,
        actor: str,
        kind: str,
        org_id: str,
        workspace_id: str = "",
        extension_id: str = "",
        detail: str,
    ) -> PolicyAuditEvent:
        """Append one event and return it (the durable form of what happened)."""
        self._seq += 1
        event = PolicyAuditEvent(
            seq=self._seq,
            at=at,
            actor=actor,
            kind=kind,
            org_id=org_id,
            workspace_id=workspace_id,
            extension_id=extension_id,
            detail=detail,
        )
        self._events.append(event)
        return event

    def events(
        self,
        org_id: str,
        *,
        workspace_id: str | None = None,
        kind: str | None = None,
    ) -> tuple[PolicyAuditEvent, ...]:
        """The trail for one organization, newest last, optionally filtered.

        ``workspace_id=None`` spans every Workspace in the organization —
        the org-admin inspection view.
        """
        selected = [
            event
            for event in self._events
            if event.org_id == org_id
            and (workspace_id is None or event.workspace_id == workspace_id)
            and (kind is None or event.kind == kind)
        ]
        return tuple(selected)


#: The deterministic layer model, in evaluation order — the static half of
#: "policy inheritance/override result is deterministic and explainable".
#: Served verbatim by the admin policy-inspection surface.
INHERITANCE_SEMANTICS: tuple[str, ...] = (
    "1. the organization deny-list denies an extension everywhere; no "
    "Workspace request can override it",
    "2. a configured organization allow-list admits only the listed "
    "extensions; Workspaces may enable a subset of them",
    "3. configured organization approved-publishers gate every install "
    "regardless of Workspace enablement",
    "4. an organization pin binds one publisher (and optionally one exact "
    "version) per extension for every Workspace",
    "5. a Workspace policy may only narrow: opt-in enablement and "
    "permission ceilings; it cannot re-enable a denied extension, admit an "
    "unapproved publisher, or escape a pin",
    "6. a Workspace without a policy inherits the organization layer unchanged",
    "7. every rule outcome is recorded on the decision trace, in this order",
)


def _require_non_blank(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyConfigurationError(f"{label} is required")
    return value


def _validate_org_policy(policy: OrgExtensionPolicy) -> None:
    """Fail closed on an organization policy that could never evaluate."""
    _require_non_blank(policy.org_id, "org_id")
    for extension_id in policy.denied_extensions:
        _require_non_blank(extension_id, "denied extension id")
    for extension_id in policy.allowed_extensions or ():
        _require_non_blank(extension_id, "allowed extension id")
    for publisher in policy.approved_publishers or ():
        _require_non_blank(publisher, "approved publisher id")
    for extension_id, pin in policy.pins.items():
        _require_non_blank(extension_id, "pinned extension id")
        _require_non_blank(pin.publisher_id, "pin publisher id")
        if pin.version is not None:
            _require_non_blank(pin.version, f"pin version for {extension_id}")


def _validate_workspace_policy(policy: WorkspaceExtensionPolicy) -> None:
    """Fail closed on a Workspace policy that could never evaluate."""
    _require_non_blank(policy.org_id, "org_id")
    _require_non_blank(policy.workspace_id, "workspace_id")
    for extension_id in policy.enabled_extensions:
        _require_non_blank(extension_id, "enabled extension id")
    for extension_id in policy.denied_extensions:
        _require_non_blank(extension_id, "denied extension id")
    for extension_id, ceiling in policy.permission_ceilings.items():
        _require_non_blank(extension_id, "ceiling extension id")
        for token in ceiling:
            try:
                normalize_permission(token)
            except ValueError as exc:
                raise PolicyConfigurationError(str(exc)) from exc


class ExtensionPolicyEngine:
    """Holds organization/Workspace policies and evaluates candidates.

    Reads (``evaluate``, ``explain``, the policy getters) are pure and
    synchronous over immutable snapshots. Mutations are async and serialize
    with enforcement critical sections through
    :meth:`enforcement_window`, so a policy change can never split a
    check-then-act sequence in the install machine.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        audit: PolicyAuditLog | None = None,
    ) -> None:
        self._clock = clock if clock is not None else _utc_now
        self._audit = audit if audit is not None else PolicyAuditLog()
        self._org_policies: dict[str, OrgExtensionPolicy] = {}
        self._workspace_policies: dict[tuple[str, str], WorkspaceExtensionPolicy] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # -- mutation ----------------------------------------------------------

    async def set_org_policy(self, policy: OrgExtensionPolicy, *, actor: str) -> None:
        """Install the organization layer wholesale and audit the change."""
        _require_non_blank(actor, "actor")
        _validate_org_policy(policy)
        async with self._org_lock(policy.org_id):
            self._org_policies[policy.org_id] = policy
            self._audit.append(
                at=self._clock(),
                actor=actor,
                kind="org-policy-set",
                org_id=policy.org_id,
                detail=_summarize_org_policy(policy),
            )

    async def set_workspace_policy(self, policy: WorkspaceExtensionPolicy, *, actor: str) -> None:
        """Install one Workspace's narrowing layer wholesale and audit it."""
        _require_non_blank(actor, "actor")
        _validate_workspace_policy(policy)
        async with self._org_lock(policy.org_id):
            self._workspace_policies[(policy.org_id, policy.workspace_id)] = policy
            self._audit.append(
                at=self._clock(),
                actor=actor,
                kind="workspace-policy-set",
                org_id=policy.org_id,
                workspace_id=policy.workspace_id,
                detail=_summarize_workspace_policy(policy),
            )

    # -- reads -------------------------------------------------------------

    def org_policy(self, org_id: str) -> OrgExtensionPolicy | None:
        """The organization layer for ``org_id``, or ``None``."""
        return self._org_policies.get(org_id)

    def workspace_policy(self, org_id: str, workspace_id: str) -> WorkspaceExtensionPolicy | None:
        """The Workspace layer for the scope, or ``None``."""
        return self._workspace_policies.get((org_id, workspace_id))

    def audit_events(
        self,
        org_id: str,
        *,
        workspace_id: str | None = None,
        kind: str | None = None,
    ) -> tuple[PolicyAuditEvent, ...]:
        """The policy audit trail for admin inspection."""
        return self._audit.events(org_id, workspace_id=workspace_id, kind=kind)

    # -- evaluation ----------------------------------------------------------

    def evaluate(
        self,
        candidate: ExtensionCandidate,
        scope: ExtensionScope,
        *,
        actor: str = "system:policy-enforcement",
    ) -> PolicyDecision:
        """Evaluate the candidate and append the decision to the audit trail.

        This is the enforcement entry point the install machine calls at
        inspection, authorization, and activation; every call is evidence.
        """
        decision = self.explain(candidate, scope)
        self._audit.append(
            at=self._clock(),
            actor=actor,
            kind="decision",
            org_id=scope.org_id,
            workspace_id=scope.workspace_id,
            extension_id=candidate.extension_id,
            detail=f"{candidate.extension_id}@{candidate.version}: "
            f"{decision.verdict.value} — {decision.explanation}",
        )
        return decision

    def explain(self, candidate: ExtensionCandidate, scope: ExtensionScope) -> PolicyDecision:
        """Evaluate the candidate without writing an audit row (dry-run).

        The rule order is fixed, so the same policy state always yields the
        same verdict and trace for the same candidate and scope.
        """
        org = self._org_policies.get(scope.org_id)
        workspace = self._workspace_policies.get((scope.org_id, scope.workspace_id))

        trace: list[PolicyRuleOutcome] = []
        denials: list[str] = []
        _org_layer(org, candidate, trace, denials)
        if denials:
            trace.append(
                PolicyRuleOutcome(
                    layer=PolicyLayer.WORKSPACE,
                    rule="workspace.skipped",
                    denied=False,
                    detail="the organization layer denied; Workspace rules are not consulted",
                )
            )
        else:
            _workspace_layer(workspace, candidate, trace, denials)

        verdict = PolicyVerdict.DENY if denials else PolicyVerdict.ALLOW
        return PolicyDecision(
            org_id=scope.org_id,
            workspace_id=scope.workspace_id,
            extension_id=candidate.extension_id,
            version=candidate.version,
            publisher=candidate.publisher,
            requested_permissions=tuple(candidate.permissions),
            verdict=verdict,
            trace=tuple(trace),
        )

    # -- concurrency ---------------------------------------------------------

    @asynccontextmanager
    async def enforcement_window(self, org_id: str) -> AsyncIterator[None]:
        """Hold the organization's enforcement window.

        The install machine wraps its authorization/activation critical
        sections in this window; policy mutations take the same per-org lock.
        Within a window the policy state cannot change, so a decision and the
        action it authorizes are linearized against every policy change.
        """
        async with self._org_lock(org_id):
            yield

    def _org_lock(self, org_id: str) -> asyncio.Lock:
        # No await between the check and the set, so lazy creation is safe
        # under a single event loop (same discipline as the install service).
        lock = self._locks.get(org_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[org_id] = lock
        return lock


# -- layer evaluators (module-level so the engine stays a thin shell) -------


def _org_layer(
    policy: OrgExtensionPolicy | None,
    candidate: ExtensionCandidate,
    trace: list[PolicyRuleOutcome],
    denials: list[str],
) -> None:
    """Evaluate the organization layer, in fixed rule order, into ``trace``."""
    if policy is None:
        trace.append(
            PolicyRuleOutcome(
                layer=PolicyLayer.ORG,
                rule="org.default",
                denied=False,
                detail="no organization policy is configured; "
                "the organization layer imposes nothing",
            )
        )
        return

    if candidate.extension_id in policy.denied_extensions:
        detail = f"extension {candidate.extension_id} is denied by the organization deny-list"
        trace.append(PolicyRuleOutcome(PolicyLayer.ORG, "org.deny-list", True, detail))
        denials.append(detail)
    else:
        trace.append(
            PolicyRuleOutcome(
                layer=PolicyLayer.ORG,
                rule="org.deny-list",
                denied=False,
                detail="not on the organization deny-list",
            )
        )

    if policy.allowed_extensions is not None and candidate.extension_id not in (
        policy.allowed_extensions
    ):
        detail = f"extension {candidate.extension_id} is not on the organization allow-list"
        trace.append(PolicyRuleOutcome(PolicyLayer.ORG, "org.allow-list", True, detail))
        denials.append(detail)
    else:
        detail = (
            "the organization allow-list admits it"
            if policy.allowed_extensions is not None
            else "no organization allow-list is configured"
        )
        trace.append(PolicyRuleOutcome(PolicyLayer.ORG, "org.allow-list", False, detail))

    if policy.approved_publishers is not None and candidate.publisher not in (
        policy.approved_publishers
    ):
        detail = f"publisher {candidate.publisher!r} is not approved by the organization"
        trace.append(PolicyRuleOutcome(PolicyLayer.ORG, "org.approved-publishers", True, detail))
        denials.append(detail)
    else:
        detail = (
            f"publisher {candidate.publisher!r} is organization-approved"
            if policy.approved_publishers is not None
            else "no organization publisher restriction is configured"
        )
        trace.append(PolicyRuleOutcome(PolicyLayer.ORG, "org.approved-publishers", False, detail))

    pin = policy.pins.get(candidate.extension_id)
    if pin is None:
        trace.append(
            PolicyRuleOutcome(
                layer=PolicyLayer.ORG,
                rule="org.pin",
                denied=False,
                detail="no organization pin for this extension",
            )
        )
        return

    if candidate.publisher != pin.publisher_id:
        detail = (
            f"organization pin requires publisher {pin.publisher_id!r}; "
            f"candidate declares {candidate.publisher!r}"
        )
        trace.append(PolicyRuleOutcome(PolicyLayer.ORG, "org.publisher-pin", True, detail))
        denials.append(detail)
    else:
        trace.append(
            PolicyRuleOutcome(
                layer=PolicyLayer.ORG,
                rule="org.publisher-pin",
                denied=False,
                detail=f"publisher {candidate.publisher!r} matches the organization pin",
            )
        )

    if pin.version is not None and candidate.version != pin.version:
        detail = (
            f"organization pin requires version {pin.version}; "
            f"candidate declares {candidate.version}"
        )
        trace.append(PolicyRuleOutcome(PolicyLayer.ORG, "org.version-pin", True, detail))
        denials.append(detail)
    else:
        detail = (
            f"version {candidate.version} matches the organization pin"
            if pin.version is not None
            else "the organization pin constrains the publisher only"
        )
        trace.append(PolicyRuleOutcome(PolicyLayer.ORG, "org.version-pin", False, detail))


def _workspace_layer(
    policy: WorkspaceExtensionPolicy | None,
    candidate: ExtensionCandidate,
    trace: list[PolicyRuleOutcome],
    denials: list[str],
) -> None:
    """Evaluate the Workspace layer; it may only ever add denials."""
    if policy is None:
        trace.append(
            PolicyRuleOutcome(
                layer=PolicyLayer.WORKSPACE,
                rule="workspace.default",
                denied=False,
                detail="no Workspace policy is configured; "
                "the Workspace inherits the organization layer unchanged",
            )
        )
        return

    if candidate.extension_id in policy.denied_extensions:
        detail = (
            f"extension {candidate.extension_id} is denied by the "
            f"{policy.workspace_id} Workspace deny-list"
        )
        trace.append(PolicyRuleOutcome(PolicyLayer.WORKSPACE, "workspace.deny-list", True, detail))
        denials.append(detail)
    else:
        trace.append(
            PolicyRuleOutcome(
                layer=PolicyLayer.WORKSPACE,
                rule="workspace.deny-list",
                denied=False,
                detail="not on the Workspace deny-list",
            )
        )

    if candidate.extension_id not in policy.enabled_extensions:
        detail = (
            f"extension {candidate.extension_id} is not enabled for Workspace {policy.workspace_id}"
        )
        trace.append(PolicyRuleOutcome(PolicyLayer.WORKSPACE, "workspace.enablement", True, detail))
        denials.append(detail)
    else:
        trace.append(
            PolicyRuleOutcome(
                layer=PolicyLayer.WORKSPACE,
                rule="workspace.enablement",
                denied=False,
                detail=f"enabled for Workspace {policy.workspace_id}",
            )
        )

    ceiling = policy.permission_ceilings.get(candidate.extension_id)
    if ceiling is None:
        trace.append(
            PolicyRuleOutcome(
                layer=PolicyLayer.WORKSPACE,
                rule="workspace.permission-ceiling",
                denied=False,
                detail="no permission ceiling for this extension in this Workspace",
            )
        )
        return

    requested = set(candidate.permissions)
    beyond = requested - set(ceiling)
    if beyond:
        detail = "requested permissions exceed the Workspace permission ceiling: " + ", ".join(
            sorted(beyond)
        )
        trace.append(
            PolicyRuleOutcome(PolicyLayer.WORKSPACE, "workspace.permission-ceiling", True, detail)
        )
        denials.append(detail)
    else:
        trace.append(
            PolicyRuleOutcome(
                layer=PolicyLayer.WORKSPACE,
                rule="workspace.permission-ceiling",
                denied=False,
                detail="requested permissions are within the Workspace ceiling",
            )
        )


def _summarize_org_policy(policy: OrgExtensionPolicy) -> str:
    """A stable one-line summary for the audit trail."""

    def names(values: frozenset[str] | None) -> str:
        if values is None:
            return "unrestricted"
        if not values:
            return "none"
        return ", ".join(sorted(values))

    pins = (
        "; ".join(
            f"{extension_id}->{pin.publisher_id}"
            + (f"@{pin.version}" if pin.version is not None else "")
            for extension_id, pin in sorted(policy.pins.items())
        )
        or "none"
    )
    return (
        f"allow={names(policy.allowed_extensions)}; "
        f"deny={names(policy.denied_extensions)}; "
        f"publishers={names(policy.approved_publishers)}; pins: {pins}"
    )


def _summarize_workspace_policy(policy: WorkspaceExtensionPolicy) -> str:
    """A stable one-line summary for the audit trail."""
    ceilings = (
        "; ".join(
            f"{extension_id}<={', '.join(sorted(ceiling))}"
            for extension_id, ceiling in sorted(policy.permission_ceilings.items())
        )
        or "none"
    )
    return (
        f"enabled={', '.join(sorted(policy.enabled_extensions)) or 'none'}; "
        f"deny={', '.join(sorted(policy.denied_extensions)) or 'none'}; "
        f"ceilings: {ceilings}"
    )
