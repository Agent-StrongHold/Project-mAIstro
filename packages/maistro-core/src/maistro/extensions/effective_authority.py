"""Effective-authority computation for extensions (#969, M9-G1).

One canonical calculation answers "what may this extension actually do":
effective authority is the **intersection** of every applicable ceiling, so a
requested permission never becomes a granted permission by declaration alone.
The layers, each able only to narrow:

1. **manifest request** — the universe of what can be granted at all. A
   permission the manifest does not declare is structurally unreachable: no
   ambient or default access exists anywhere in this module to recover an
   omission with.
2. **publisher/package trust** — an untrusted publisher holds nothing, and a
   trusted publisher's trust tier gates which ceiling applies
   (:class:`TrustTier`, :func:`resolve_publisher_trust`).
3. **deployment/host policy** — the platform ceiling, a per-trust-tier
   ceiling, and per-extension-family ceilings (an unmapped family simply has
   no family-specific ceiling; the host ceiling still applies).
4. **canonical caller/Agent delegated authority** — an extension never holds
   more than its caller could delegate to it, and the caller cannot delegate
   past what the manifest, package trust, host, or Workspace disallow.
5. **Workspace/org extension policy** — the extension must be enabled in the
   requesting scope, and the Workspace's permission ceiling applies.

Deny-by-default throughout: an absent ceiling is an empty ceiling, an empty
ceiling grants nothing, and every layer must admit a permission for it to be
effective. The result is a pure function of its inputs — no clock, no
randomness — so the same inputs always produce an equal, independently
re-computable answer with a stable ``decision_digest``. Policy changes
therefore affect only operations evaluated after the change; previously
recorded results (immutable, digest-anchored) are historical evidence and are
never rewritten. :meth:`EffectiveAuthority.with_execution_context` pins a
result to the canonical Run evidence (run/node-run/attempt ids) for audit.

This module is the extension-side authority calculation. It does not replace
the canonical authorization decision points (Sentinel, the policy engine);
it defines what an extension's declared authority *is* so those decision
points and sandbox profiles (M9-G2) enforce an already-intersected set.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from maistro.extensions.authority import normalize_permission
from maistro.extensions.manifest import assert_snapshot_intact
from maistro.extensions.trust import TrustPolicy, TrustReport, evaluate_trust
from maistro.extensions.types import ExtensionManifest, ExtensionScope, TrustClaim


class TrustTier(StrEnum):
    """Publisher/package trust ladder (#969).

    A tier is not a privilege: it selects which host ceiling applies. The
    members are deliberately few; deployments map publishers to tiers and
    define per-tier ceilings in :class:`HostExtensionPolicy`. An unmapped
    tier ceiling is an empty ceiling — a tier without a configured ceiling
    grants nothing. The default tier for a publisher absent from the
    deployment's mapping is :attr:`UNVERIFIED`: signature-verified, but in
    no deployment-configured tier program.
    """

    UNTRUSTED = "untrusted"
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


@dataclass(frozen=True)
class PublisherTrust:
    """The trust layer's answer for one extension package.

    ``trusted`` is the fail-closed verdict (a mirror of
    :class:`maistro.extensions.trust.TrustReport`); an untrusted result
    forces the effective tier to :attr:`TrustTier.UNTRUSTED` regardless of
    any configured mapping, and ``failures`` carries the reasons.
    """

    tier: TrustTier
    trusted: bool
    failures: tuple[str, ...] = ()


def resolve_publisher_trust(
    manifest: ExtensionManifest,
    evidence: TrustClaim,
    policy: TrustPolicy,
    *,
    tier_of: Mapping[str, TrustTier],
    default_tier: TrustTier,
) -> PublisherTrust:
    """Combine trust evidence, trust policy, and publisher tiers into one answer.

    ``tier_of`` maps publisher ids to their configured tier; publishers
    absent from the mapping take ``default_tier``. Mapping a publisher to
    :attr:`TrustTier.UNTRUSTED` is an explicit downgrade and is honored even
    when the evidence itself verified. Everything routes through
    :func:`maistro.extensions.trust.evaluate_trust`, so an evaluation that
    fails — publisher not allowlisted, signature absent where required — is
    untrusted at tier :attr:`TrustTier.UNTRUSTED` with its failures intact.
    """
    report: TrustReport = evaluate_trust(manifest, evidence, policy)
    if not report.trusted:
        return PublisherTrust(tier=TrustTier.UNTRUSTED, trusted=False, failures=report.failures)
    tier = tier_of.get(manifest.publisher, default_tier)
    if tier is TrustTier.UNTRUSTED:
        return PublisherTrust(
            tier=TrustTier.UNTRUSTED,
            trusted=False,
            failures=(f"publisher {manifest.publisher!r} is pinned to an untrusted tier",),
        )
    return PublisherTrust(tier=tier, trusted=True)


def extension_family(extension_id: str) -> str:
    """The family of an extension id: the leading dotted segment.

    ``acme.chart_tools`` belongs to family ``acme``; an id without a dot is
    its own family. Family ceilings key on this, so a deployment can restrict
    a whole family of extensions without enumerating ids.
    """
    return extension_id.split(".", 1)[0]


@dataclass(frozen=True)
class HostExtensionPolicy:
    """Deployment/host ceilings. Every field is an allow-set; empty denies all."""

    #: The absolute deployment ceiling. No permission outside it is ever
    #: effective, whatever every other layer says.
    ceiling: frozenset[str] = frozenset()
    #: Ceiling per trust tier. A tier absent here has an empty ceiling.
    tier_ceilings: Mapping[TrustTier, frozenset[str]] = field(default_factory=dict)
    #: Extra ceiling per extension family (:func:`extension_family`). A family
    #: absent here has no family-specific restriction beyond the ceilings
    #: above; a family mapped to an empty set is barred entirely.
    family_ceilings: Mapping[str, frozenset[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class CallerAuthority:
    """What the canonical caller (Agent or human) can delegate to the extension.

    ``delegated_permissions`` is the caller's delegable set — deny-by-default,
    so a caller configured with nothing delegates nothing. The intersection
    makes both failure directions impossible: the caller cannot delegate
    authority the manifest/trust/host/Workspace disallow, and those layers
    cannot grant authority the caller does not delegate.
    """

    principal_id: str
    delegated_permissions: frozenset[str] = frozenset()


@dataclass(frozen=True)
class WorkspaceExtensionPolicy:
    """The Workspace/org extension policy layer.

    ``enabled_extensions`` is the allowlist of extension ids enabled in the
    scope — empty enables nothing. ``permission_ceiling`` caps what the
    Workspace extends to its enabled extensions.
    """

    scope: ExtensionScope
    enabled_extensions: frozenset[str] = frozenset()
    permission_ceiling: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PermissionDenial:
    """One requested permission the intersection refused, and why."""

    permission: str
    #: Every layer that excludes it, in the fixed layer order; plus the
    #: global blockers when one applies. Non-empty by construction.
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class EffectiveAuthority:
    """The explainable result of the intersection (#969).

    Pure function of its inputs: no timestamps, no randomness. Two
    evaluations of the same inputs are equal and carry the same
    ``decision_digest`` (a SHA-256 over the canonical decision payload), so a
    recorded result can always be re-derived and compared. Changing any
    input — a manifest byte, a ceiling, a tier mapping — changes the digest;
    previously recorded results keep theirs, which is what makes policy
    changes forward-looking only.
    """

    extension_id: str
    version: str
    publisher: str
    #: The manifest snapshot digest the decision was computed from.
    manifest_sha256: str
    #: What the manifest requested — the only universe considered.
    requested: tuple[str, ...]
    #: What every layer admits: sorted, and never broader than any ceiling.
    effective: tuple[str, ...]
    #: Requested permissions the intersection refused, with layer reasons.
    denials: tuple[PermissionDenial, ...] = ()
    #: Package-level blockers (untrusted publisher, extension not enabled)
    #: that deny everything regardless of per-permission ceilings.
    blockers: tuple[str, ...] = ()
    #: SHA-256 over the canonical decision payload — the stable identity of
    #: this exact authorization answer.
    decision_digest: str = ""

    @property
    def granted_all(self) -> bool:
        """True when no requested permission was denied."""
        return not self.denials and not self.blockers

    @property
    def granted_none(self) -> bool:
        """True when nothing is effective."""
        return not self.effective

    def with_execution_context(
        self, *, run_id: str, node_run_id: str, attempt_id: str
    ) -> ExtensionAuthorityEvidence:
        """Pin this result to canonical Run evidence without mutating it.

        The evidence shares the authority result (same digest); the linkage
        fields only say *where* the decision was applied.
        """
        return ExtensionAuthorityEvidence(
            authority=self, run_id=run_id, node_run_id=node_run_id, attempt_id=attempt_id
        )


@dataclass(frozen=True)
class ExtensionAuthorityInputs:
    """The policy inputs a deployment supplies for extension authorization.

    Passed to :class:`maistro.extensions.service.ExtensionInstallService` so
    install-time grants are frozen to the intersection rather than to the
    manifest declaration. Every layer must be stated: there are no defaults
    that quietly mean "allow", and an inputs bundle configured with empty
    ceilings authorizes nothing (deny-by-default). ``None`` (the service
    default) keeps the #953 operator-approval contract, where the grant
    freezes to the requested set the operator saw and approved.
    """

    #: Trust evidence for the package under inspection, combined with the
    #: service's :class:`TrustPolicy` by :func:`resolve_publisher_trust`.
    trust_claim: TrustClaim
    #: Publisher -> tier mapping (see :func:`resolve_publisher_trust`).
    tier_of: Mapping[str, TrustTier] = field(default_factory=dict)
    #: Tier for publishers absent from ``tier_of``.
    default_tier: TrustTier = TrustTier.UNVERIFIED
    host: HostExtensionPolicy = field(default_factory=HostExtensionPolicy)
    caller: CallerAuthority = field(default_factory=lambda: CallerAuthority(principal_id=""))
    workspace: WorkspaceExtensionPolicy = field(
        default_factory=lambda: WorkspaceExtensionPolicy(scope=ExtensionScope(org_id="deployment"))
    )


@dataclass(frozen=True)
class ExtensionAuthorityEvidence:
    """An effective-authority result linked to one Invocation/Run site.

    Field names mirror :class:`maistro.capabilities.governed_invocation.
    InvocationPolicyContext` so the evidence attaches to the same canonical
    execution identity (Run -> NodeRun -> Attempt) that Invocation evidence
    uses. The authority's ``decision_digest`` is the join key: audit trails
    store the digest, and the full result can be re-derived from the recorded
    inputs at any time.
    """

    authority: EffectiveAuthority
    run_id: str
    node_run_id: str
    attempt_id: str


def _validated(tokens: frozenset[str], *, layer: str) -> frozenset[str]:
    """Fail loudly on a malformed token in operator-configured policy.

    Manifest permissions are validated at parse time; ceilings and
    delegations are configuration, and a typo there must be a configuration
    error, not a silently narrower ceiling nobody noticed.
    """
    for token in tokens:
        try:
            normalize_permission(token)
        except ValueError as exc:
            raise ValueError(f"{layer} policy contains {exc}") from exc
    return tokens


@dataclass(frozen=True)
class _ResolvedCeilings:
    """The validated allow-sets every layer contributes to the intersection."""

    tier: frozenset[str]
    host: frozenset[str]
    family: frozenset[str] | None  # None: no family-specific ceiling configured
    caller: frozenset[str]
    workspace: frozenset[str]


def _resolve_ceilings(
    *,
    manifest: ExtensionManifest,
    trust: PublisherTrust,
    host: HostExtensionPolicy,
    caller: CallerAuthority,
    workspace: WorkspaceExtensionPolicy,
) -> tuple[_ResolvedCeilings, str]:
    """Validate and gather each layer's ceiling, with the extension family."""
    family = extension_family(manifest.extension_id)
    resolved = _ResolvedCeilings(
        tier=_validated(
            host.tier_ceilings.get(trust.tier, frozenset()), layer=f"trust tier {trust.tier.value}"
        ),
        host=_validated(host.ceiling, layer="host"),
        family=(
            _validated(host.family_ceilings[family], layer=f"extension family {family}")
            if family in host.family_ceilings
            else None
        ),
        caller=_validated(caller.delegated_permissions, layer="caller"),
        workspace=_validated(workspace.permission_ceiling, layer="workspace"),
    )
    return resolved, family


def _package_blockers(
    *, manifest: ExtensionManifest, trust: PublisherTrust, workspace: WorkspaceExtensionPolicy
) -> tuple[str, ...]:
    """Package-level blockers: each denies every requested permission."""
    blockers: list[str] = []
    if not trust.trusted:
        detail = "; ".join(trust.failures) if trust.failures else "trust evaluation failed"
        blockers.append(f"publisher {manifest.publisher!r} is not trusted: {detail}")
    if manifest.extension_id not in workspace.enabled_extensions:
        blockers.append(
            f"extension {manifest.extension_id!r} is not enabled in {workspace.scope.describe}"
        )
    return tuple(blockers)


def _denial_reasons(
    permission: str,
    ceilings: _ResolvedCeilings,
    *,
    trust: PublisherTrust,
    family: str,
    caller: CallerAuthority,
    workspace: WorkspaceExtensionPolicy,
) -> tuple[str, ...]:
    """Every layer that excludes ``permission``, in the fixed layer order."""
    reasons: list[str] = []
    if permission not in ceilings.tier:
        reasons.append(f"trust tier {trust.tier.value!r} ceiling excludes it")
    if permission not in ceilings.host:
        reasons.append("host policy ceiling excludes it")
    if ceilings.family is not None and permission not in ceilings.family:
        reasons.append(f"extension family {family!r} ceiling excludes it")
    if permission not in ceilings.caller:
        reasons.append(f"caller {caller.principal_id!r} has not delegated it")
    if permission not in ceilings.workspace:
        reasons.append(f"workspace {workspace.scope.describe} ceiling excludes it")
    return tuple(reasons)


def _canonical_decision_payload(
    *,
    extension_id: str,
    version: str,
    publisher: str,
    manifest_sha256: str,
    requested: tuple[str, ...],
    effective: tuple[str, ...],
    denials: tuple[PermissionDenial, ...],
    blockers: tuple[str, ...],
) -> bytes:
    """The exact bytes a decision digest is taken over."""
    payload = {
        "blockers": list(blockers),
        "denials": [
            {"permission": denial.permission, "reasons": list(denial.reasons)} for denial in denials
        ],
        "effective": list(effective),
        "extension_id": extension_id,
        "manifest_sha256": manifest_sha256,
        "publisher": publisher,
        "requested": list(requested),
        "version": version,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def compute_effective_authority(
    manifest: ExtensionManifest,
    *,
    trust: PublisherTrust,
    host: HostExtensionPolicy,
    caller: CallerAuthority,
    workspace: WorkspaceExtensionPolicy,
) -> EffectiveAuthority:
    """Intersect manifest, trust, host, caller, and Workspace policy (#969).

    The requested universe is exactly ``manifest.permissions`` — computed
    only after the manifest snapshot re-verifies against its anchored
    digest, so a decision can never be computed from bytes that drifted.
    Every other layer contributes an allow-set (empty denies all) and global
    blockers (untrusted publisher; extension not enabled in the Workspace)
    deny everything. The result explains every refusal per permission and is
    digest-anchored for stable, replayable authorization evidence.
    """
    assert_snapshot_intact(manifest)
    requested = manifest.permissions
    ceilings, family = _resolve_ceilings(
        manifest=manifest, trust=trust, host=host, caller=caller, workspace=workspace
    )
    blockers = _package_blockers(manifest=manifest, trust=trust, workspace=workspace)

    effective: list[str] = []
    denials: list[PermissionDenial] = []
    for permission in sorted(requested):
        if blockers:
            denials.append(PermissionDenial(permission=permission, reasons=blockers))
            continue
        reasons = _denial_reasons(
            permission, ceilings, trust=trust, family=family, caller=caller, workspace=workspace
        )
        if reasons:
            denials.append(PermissionDenial(permission=permission, reasons=reasons))
        else:
            effective.append(permission)

    frozen_effective = tuple(effective)
    digest = hashlib.sha256(
        _canonical_decision_payload(
            extension_id=manifest.extension_id,
            version=manifest.version,
            publisher=manifest.publisher,
            manifest_sha256=manifest.source_sha256,
            requested=tuple(sorted(requested)),
            effective=frozen_effective,
            denials=tuple(denials),
            blockers=tuple(blockers),
        )
    ).hexdigest()

    return EffectiveAuthority(
        extension_id=manifest.extension_id,
        version=manifest.version,
        publisher=manifest.publisher,
        manifest_sha256=manifest.source_sha256,
        requested=tuple(sorted(requested)),
        effective=frozen_effective,
        denials=tuple(denials),
        blockers=tuple(blockers),
        decision_digest=digest,
    )
