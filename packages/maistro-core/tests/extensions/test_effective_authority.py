"""Effective-authority intersection (#969, M9-G1).

The canonical calculation behind "what may this extension actually do":
effective authority is the intersection of manifest request, publisher trust,
host policy, caller delegation and Workspace policy. These tests pin each
acceptance criterion of the issue against reachable production behavior:
never broader than any ceiling, manifest omission unrecoverable, delegation
capped from both directions, stable and digest-anchored results linkable to
Run evidence, forward-looking policy changes, deny-by-default under
differential and property-tested combinations, and the install service
freezing grants to the intersection.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from maistro.extensions import (
    CallerAuthority,
    EffectiveAuthority,
    ExtensionInstallService,
    ExtensionPackage,
    ExtensionScope,
    HostExtensionPolicy,
    InMemoryExtensionStore,
    TrustPolicy,
    WorkspaceExtensionPolicy,
    compute_effective_authority,
    extension_family,
    resolve_publisher_trust,
)
from maistro.extensions.effective_authority import PublisherTrust, TrustTier
from maistro.extensions.manifest import inspect_manifest
from maistro.extensions.service import LoadedExtension, UnwiredExtensionLoader
from maistro.extensions.types import TrustClaim

PAYLOAD = b"effective-authority-payload"
MANIFEST_ID = "acme.chart_tools"
SCOPE = ExtensionScope(org_id="org-1", workspace_id="ws-9")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest_bytes(
    *,
    extension_id: str = MANIFEST_ID,
    permissions: tuple[str, ...] = ("network.http", "storage.workspace"),
    publisher: str = "acme",
    payload: bytes = PAYLOAD,
) -> bytes:
    document = {
        "manifest_version": 1,
        "id": extension_id,
        "name": "Chart Tools",
        "version": "1.4.0",
        "publisher": publisher,
        "api_version": "1.0.0",
        "permissions": list(permissions),
        "entry_points": [{"name": "main", "module": "acme_chart.main", "attribute": "activate"}],
        "artifact": {"sha256": _digest(payload), "size": len(payload)},
    }
    return json.dumps(document).encode("utf-8")


def _manifest(**overrides: object):
    return inspect_manifest(_manifest_bytes(**overrides))


def _trusted(tier: TrustTier = TrustTier.UNVERIFIED) -> PublisherTrust:
    return PublisherTrust(tier=tier, trusted=True)


def _host(
    ceiling: tuple[str, ...] = ("network.http", "storage.workspace"),
    tiers: dict[TrustTier, tuple[str, ...]] | None = None,
    families: dict[str, tuple[str, ...]] | None = None,
) -> HostExtensionPolicy:
    # Default tier ceilings mirror the host ceiling, so the default
    # configuration admits the full request at the default tier; an explicit
    # ``tiers`` mapping replaces it wholesale.
    resolved_tiers = {TrustTier.UNVERIFIED: frozenset(ceiling)} if tiers is None else tiers
    return HostExtensionPolicy(
        ceiling=frozenset(ceiling),
        tier_ceilings={k: frozenset(v) for k, v in resolved_tiers.items()},
        family_ceilings={k: frozenset(v) for k, v in (families or {}).items()},
    )


def _caller(delegated: tuple[str, ...] = ("network.http", "storage.workspace")) -> CallerAuthority:
    return CallerAuthority(principal_id="agent-7", delegated_permissions=frozenset(delegated))


def _workspace(
    *,
    enabled: str | None = MANIFEST_ID,
    ceiling: tuple[str, ...] = ("network.http", "storage.workspace"),
) -> WorkspaceExtensionPolicy:
    enabled_set = frozenset({enabled}) if enabled else frozenset()
    return WorkspaceExtensionPolicy(
        scope=SCOPE,
        enabled_extensions=enabled_set,
        permission_ceiling=frozenset(ceiling),
    )


def _authority(
    *, manifest=None, trust=None, host=None, caller=None, workspace=None
) -> EffectiveAuthority:  # type: ignore[no-untyped-def]
    """A fully-configured intersection: every layer admits the full request."""
    return compute_effective_authority(
        manifest if manifest is not None else _manifest(),
        trust=trust if trust is not None else _trusted(),
        host=host if host is not None else _host(),
        caller=caller if caller is not None else _caller(),
        workspace=workspace if workspace is not None else _workspace(),
    )


# --------------------------------------------------------------------------
# AC: effective authority is never broader than any applicable ceiling
# --------------------------------------------------------------------------


class TestNeverBroaderThanAnyCeiling:
    def test_full_configuration_grants_exactly_the_request(self) -> None:
        authority = _authority()
        assert authority.effective == ("network.http", "storage.workspace")
        assert authority.denials == () and authority.blockers == ()
        assert authority.granted_all

    def test_host_ceiling_caps_the_result(self) -> None:
        authority = _authority(host=_host(ceiling=("network.http",)))
        assert authority.effective == ("network.http",)
        denial = next(d for d in authority.denials if d.permission == "storage.workspace")
        assert "host policy ceiling excludes it" in denial.reasons

    def test_tier_ceiling_caps_the_result(self) -> None:
        authority = _authority(
            trust=_trusted(TrustTier.UNVERIFIED),
            host=_host(tiers={TrustTier.UNVERIFIED: ("storage.workspace",)}),
        )
        assert authority.effective == ("storage.workspace",)
        denial = next(d for d in authority.denials if d.permission == "network.http")
        assert "trust tier 'unverified' ceiling excludes it" in denial.reasons

    def test_family_ceiling_caps_only_its_family(self) -> None:
        authority = _authority(host=_host(families={"acme": ("network.http",)}))
        assert authority.effective == ("network.http",)
        denial = next(d for d in authority.denials if d.permission == "storage.workspace")
        assert "extension family 'acme' ceiling excludes it" in denial.reasons

    def test_unmapped_family_has_no_family_ceiling(self) -> None:
        authority = _authority(
            manifest=_manifest(extension_id="other.calendar_sync"),
            host=_host(families={"acme": ("network.http",)}),
            workspace=_workspace(enabled="other.calendar_sync"),
        )
        # The "other" family is unmapped, so no family restriction applies;
        # every fully-admitting layer admits the whole request.
        assert authority.effective == ("network.http", "storage.workspace")
        assert authority.denials == ()

    def test_caller_delegation_caps_the_result(self) -> None:
        authority = _authority(caller=_caller(delegated=("network.http",)))
        assert authority.effective == ("network.http",)
        denial = next(d for d in authority.denials if d.permission == "storage.workspace")
        assert "caller 'agent-7' has not delegated it" in denial.reasons

    def test_workspace_ceiling_caps_the_result(self) -> None:
        authority = _authority(workspace=_workspace(ceiling=("storage.workspace",)))
        assert authority.effective == ("storage.workspace",)
        denial = next(d for d in authority.denials if d.permission == "network.http")
        assert "workspace org:org-1/workspace:ws-9 ceiling excludes it" in denial.reasons

    def test_result_is_a_subset_of_every_layer_at_once(self) -> None:
        authority = _authority(
            trust=_trusted(TrustTier.VERIFIED),
            host=_host(
                ceiling=("network.http", "storage.workspace", "clipboard.read"),
                tiers={TrustTier.VERIFIED: ("network.http", "storage.workspace")},
                families={"acme": ("network.http", "storage.workspace", "secrets.read")},
            ),
            caller=_caller(("network.http", "storage.workspace", "secrets.read")),
            workspace=_workspace(ceiling=("network.http", "storage.workspace", "secrets.read")),
        )
        assert authority.effective == ("network.http", "storage.workspace")
        assert set(authority.effective) <= set(authority.requested)


# --------------------------------------------------------------------------
# AC: manifest omission cannot be recovered through ambient/default access
# --------------------------------------------------------------------------


class TestManifestOmission:
    def test_permission_absent_from_manifest_is_never_effective(self) -> None:
        # Every policy layer "allows" more than the manifest does: if the
        # calculation had an ambient/default path, secrets.read would appear.
        everything = ("network.http", "storage.workspace", "secrets.read")
        authority = _authority(
            host=_host(ceiling=everything),
            caller=_caller(everything),
            workspace=_workspace(ceiling=everything),
        )
        assert authority.effective == ("network.http", "storage.workspace")
        assert "secrets.read" not in authority.requested
        assert all(d.permission != "secrets.read" for d in authority.denials)

    def test_empty_manifest_permissions_grant_nothing(self) -> None:
        result = _authority(manifest=_manifest(permissions=()))
        assert result.requested == () and result.effective == ()
        assert result.denials == () and result.granted_none

    def test_no_layer_grants_anything_by_default(self) -> None:
        # A "configured" deployment that set no ceilings anywhere.
        authority = compute_effective_authority(
            _manifest(),
            trust=_trusted(),
            host=HostExtensionPolicy(),
            caller=CallerAuthority(principal_id="agent-7"),
            workspace=WorkspaceExtensionPolicy(
                scope=SCOPE, enabled_extensions=frozenset({MANIFEST_ID})
            ),
        )
        assert authority.effective == ()
        assert len(authority.denials) == len(authority.requested)


# --------------------------------------------------------------------------
# AC: caller delegation cannot grant authority the extension/package/host
# disallows and vice versa
# --------------------------------------------------------------------------


class TestDelegationCappedFromBothDirections:
    def test_caller_cannot_delegate_past_host(self) -> None:
        authority = _authority(
            host=_host(ceiling=("network.http",)),
            caller=_caller(("network.http", "storage.workspace")),
        )
        assert authority.effective == ("network.http",)

    def test_host_cannot_grant_past_caller(self) -> None:
        authority = _authority(host=_host(), caller=_caller(("storage.workspace",)))
        assert authority.effective == ("storage.workspace",)

    def test_workspace_and_caller_cap_each_other(self) -> None:
        a = _authority(workspace=_workspace(ceiling=("network.http",)), caller=_caller())
        assert a.effective == ("network.http",)
        b = _authority(workspace=_workspace(), caller=_caller(("storage.workspace",)))
        assert b.effective == ("storage.workspace",)

    def test_untrusted_package_cannot_be_rescued_by_caller_or_workspace(self) -> None:
        authority = _authority(
            trust=PublisherTrust(tier=TrustTier.UNTRUSTED, trusted=False, failures=("no sig",))
        )
        assert authority.effective == ()
        assert authority.blockers
        assert all("not trusted" in b for b in authority.blockers)


# --------------------------------------------------------------------------
# Deny-by-default behavior, including the trust/enablement blockers
# --------------------------------------------------------------------------


class TestDenyByDefault:
    def test_missing_tier_ceiling_denies_everything(self) -> None:
        authority = _authority(trust=_trusted(TrustTier.VERIFIED), host=_host())
        assert authority.effective == ()
        for denial in authority.denials:
            assert "trust tier 'verified' ceiling excludes it" in denial.reasons

    def test_extension_not_enabled_in_workspace_is_a_blocker(self) -> None:
        authority = _authority(workspace=_workspace(enabled=None))
        assert authority.effective == ()
        assert authority.blockers == (
            f"extension {MANIFEST_ID!r} is not enabled in org:org-1/workspace:ws-9",
        )
        for denial in authority.denials:
            assert denial.reasons == authority.blockers

    def test_malformed_policy_token_is_a_configuration_error(self) -> None:
        cases: list[dict[str, object]] = [
            {"host": _host(ceiling=("Network.HTTP",))},
            {"caller": _caller(("network.http;",))},
            {"workspace": _workspace(ceiling=("9network",))},
            {"host": _host(families={"acme": ("bad token",)})},
            {"host": _host(tiers={TrustTier.UNVERIFIED: ("UPPER",)})},
        ]
        for layer_kwargs in cases:
            with pytest.raises(ValueError, match="malformed permission token"):
                _authority(**layer_kwargs)  # type: ignore[arg-type]

    def test_family_resolution(self) -> None:
        assert extension_family("acme.chart_tools") == "acme"
        assert extension_family("singleton") == "singleton"
        assert extension_family("a.b.c.d") == "a"


class TestResolvePublisherTrust:
    POLICY = TrustPolicy(trusted_publishers=frozenset({"acme"}), require_signature=False)
    EVIDENCE = TrustClaim(publisher_id="acme", signature_present=False)

    def test_trusted_publisher_takes_the_default_tier(self) -> None:
        trust = resolve_publisher_trust(
            _manifest(),
            self.EVIDENCE,
            self.POLICY,
            tier_of={},
            default_tier=TrustTier.UNVERIFIED,
        )
        assert trust.trusted and trust.tier is TrustTier.UNVERIFIED and trust.failures == ()

    def test_publisher_mapping_overrides_the_default_tier(self) -> None:
        trust = resolve_publisher_trust(
            _manifest(),
            self.EVIDENCE,
            self.POLICY,
            tier_of={"acme": TrustTier.VERIFIED},
            default_tier=TrustTier.UNVERIFIED,
        )
        assert trust.trusted and trust.tier is TrustTier.VERIFIED

    def test_failed_trust_evaluation_forces_untrusted_with_failures(self) -> None:
        bad_evidence = TrustClaim(publisher_id="mallory", signature_present=False)
        trust = resolve_publisher_trust(
            _manifest(),
            bad_evidence,
            self.POLICY,
            tier_of={"acme": TrustTier.VERIFIED},
            default_tier=TrustTier.VERIFIED,
        )
        assert not trust.trusted
        assert trust.tier is TrustTier.UNTRUSTED
        assert trust.failures and any("mallory" in f for f in trust.failures)

    def test_publisher_pinned_to_untrusted_tier_is_untrusted(self) -> None:
        trust = resolve_publisher_trust(
            _manifest(),
            self.EVIDENCE,
            self.POLICY,
            tier_of={"acme": TrustTier.UNTRUSTED},
            default_tier=TrustTier.UNVERIFIED,
        )
        assert not trust.trusted and trust.tier is TrustTier.UNTRUSTED
        assert any("untrusted tier" in f for f in trust.failures)


# --------------------------------------------------------------------------
# AC: authorization result is stable, inspectable, linked to Run evidence
# --------------------------------------------------------------------------


class TestStableInspectable:
    def test_same_inputs_produce_equal_results_and_digest(self) -> None:
        a = _authority()
        b = _authority()
        assert a == b
        assert a.decision_digest == b.decision_digest
        assert len(a.decision_digest) == 64

    def test_digest_tracks_every_layer(self) -> None:
        base = _authority()
        variants = [
            _authority(trust=_trusted(TrustTier.VERIFIED)),
            _authority(host=_host(ceiling=("network.http",))),
            _authority(caller=_caller(("storage.workspace",))),
            _authority(workspace=_workspace(ceiling=("network.http",))),
        ]
        for variant in variants:
            assert variant.decision_digest != base.decision_digest
        assert _authority().decision_digest == base.decision_digest

    def test_digest_anchors_the_manifest_bytes(self) -> None:
        authority = _authority()
        assert authority.manifest_sha256 == _manifest().source_sha256

        wider_manifest = _manifest(permissions=("network.http", "storage.workspace", "extra.cap"))
        other = compute_effective_authority(
            wider_manifest,
            trust=_trusted(),
            host=_host(ceiling=("network.http", "storage.workspace", "extra.cap")),
            caller=_caller(("network.http", "storage.workspace", "extra.cap")),
            workspace=_workspace(ceiling=("network.http", "storage.workspace", "extra.cap")),
        )
        assert other.manifest_sha256 != authority.manifest_sha256
        assert other.decision_digest != authority.decision_digest

    def test_evidence_link_carries_run_identity_and_keeps_the_digest(self) -> None:
        authority = _authority()
        evidence = authority.with_execution_context(
            run_id="run-1", node_run_id="node-2", attempt_id="attempt-3"
        )
        assert evidence.authority is authority
        assert evidence.run_id == "run-1"
        assert evidence.node_run_id == "node-2"
        assert evidence.attempt_id == "attempt-3"
        assert evidence.authority.decision_digest == authority.decision_digest


# --------------------------------------------------------------------------
# AC: policy changes affect new operations without rewriting history
# --------------------------------------------------------------------------


class TestPolicyChangeIsForwardLooking:
    def test_historical_evidence_survives_a_policy_change(self) -> None:
        before = _authority()
        evidence = before.with_execution_context(
            run_id="run-1", node_run_id="node-2", attempt_id="attempt-3"
        )
        recorded_effective, recorded_digest = before.effective, before.decision_digest

        after = _authority(host=_host(ceiling=("network.http",)))
        assert after.decision_digest != recorded_digest
        assert after.effective != recorded_effective
        # The recorded evidence was never rewritten by the new policy:
        assert evidence.authority.effective == recorded_effective
        assert evidence.authority.decision_digest == recorded_digest
        assert evidence.authority == before

    def test_recompute_with_new_policy_reflects_the_new_policy(self) -> None:
        tightened = _authority(host=_host(ceiling=("network.http",)))
        assert tightened.effective == ("network.http",)
        assert len(tightened.denials) == 1


# --------------------------------------------------------------------------
# AC: differential/property tests over combinations and deny-by-default
# --------------------------------------------------------------------------


PERMISSIONS = st.sampled_from(
    ["network.http", "storage.workspace", "clipboard.read", "secrets.read"]
)


class TestProperties:
    @given(requested=st.sets(PERMISSIONS, min_size=1))
    def test_effective_never_exceeds_the_intersection(self, requested: set[str]) -> None:
        manifest = _manifest(permissions=tuple(sorted(requested)))
        over_broad = sorted(requested | {"ambient.capability"})
        authority = compute_effective_authority(
            manifest,
            trust=_trusted(),
            host=_host(ceiling=over_broad),  # type: ignore[arg-type]
            caller=_caller(over_broad),  # type: ignore[arg-type]
            workspace=_workspace(ceiling=over_broad),  # type: ignore[arg-type]
        )
        # The manifest is the whole universe: nothing ambient, nothing extra.
        assert set(authority.effective) <= requested
        assert "ambient.capability" not in authority.effective

    @given(requested=st.sets(PERMISSIONS, min_size=1), extra=st.sets(PERMISSIONS))
    def test_widening_a_layer_never_shrinks_authority(
        self, requested: set[str], extra: set[str]
    ) -> None:
        manifest = _manifest(permissions=tuple(sorted(requested)))
        narrow = compute_effective_authority(
            manifest,
            trust=_trusted(),
            host=_host(ceiling=tuple(sorted(requested))),
            caller=_caller(tuple(sorted(requested))),
            workspace=_workspace(ceiling=tuple(sorted(requested))),
        )
        union = sorted(requested | extra)
        widened = compute_effective_authority(
            manifest,
            trust=_trusted(),
            host=_host(ceiling=union),  # type: ignore[arg-type]
            caller=_caller(union),  # type: ignore[arg-type]
            workspace=_workspace(ceiling=union),  # type: ignore[arg-type]
        )
        assert set(narrow.effective) <= set(widened.effective)

    @given(requested=st.sets(PERMISSIONS, min_size=1))
    def test_empty_caller_delegation_denies_everything(self, requested: set[str]) -> None:
        manifest = _manifest(permissions=tuple(sorted(requested)))
        authority = compute_effective_authority(
            manifest,
            trust=_trusted(),
            host=_host(ceiling=tuple(requested)),
            caller=CallerAuthority(principal_id="agent-7"),
            workspace=_workspace(ceiling=tuple(requested)),
        )
        assert authority.effective == ()
        assert authority.granted_none
        for denial in authority.denials:
            assert "caller 'agent-7' has not delegated it" in denial.reasons

    @given(tier=st.sampled_from([TrustTier.UNVERIFIED, TrustTier.VERIFIED]))
    def test_blockers_dominate_any_ceiling_configuration(self, tier: TrustTier) -> None:
        authority = _authority(trust=PublisherTrust(tier=tier, trusted=False, failures=("x",)))
        assert authority.effective == ()
        assert authority.blockers


# --------------------------------------------------------------------------
# Service integration: the install grant freezes to the intersection
# --------------------------------------------------------------------------


def _make_service(authority_inputs: object = None) -> ExtensionInstallService:
    trust_policy = TrustPolicy(trusted_publishers=frozenset({"acme"}), require_signature=False)
    ids = iter(f"install-{n}" for n in range(10000))
    return ExtensionInstallService(
        InMemoryExtensionStore(),
        loader=UnwiredExtensionLoader(),
        trust_policy=trust_policy,
        authority_inputs=authority_inputs,  # type: ignore[arg-type]
        clock=lambda: datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC),
        install_id_factory=lambda: next(ids),
    )


async def _inspected(service: ExtensionInstallService):
    package = ExtensionPackage(manifest_bytes=_manifest_bytes(), payload=PAYLOAD)
    return await service.inspect(
        actor="operator",
        scope=SCOPE,
        package=package,
        trust_evidence=TrustClaim(publisher_id="acme", signature_present=False),
    )


def _loaded(record) -> LoadedExtension:  # type: ignore[no-untyped-def]
    return LoadedExtension(extension_id=record.extension_id, version=record.version)


class TestServiceIntegration:
    async def test_grant_freezes_to_the_intersection_not_the_request(self) -> None:
        from maistro.extensions.effective_authority import ExtensionAuthorityInputs

        inputs = ExtensionAuthorityInputs(
            trust_claim=TrustClaim(publisher_id="acme", signature_present=False),
            tier_of={"acme": TrustTier.VERIFIED},
            default_tier=TrustTier.UNVERIFIED,
            host=_host(
                tiers={TrustTier.VERIFIED: ("network.http",)},
            ),
            caller=_caller(),
            workspace=_workspace(),
        )
        service = _make_service(authority_inputs=inputs)
        record = await _inspected(service)
        assert record.state.value == "awaiting_authorization"

        authorized = await service.authorize(
            record.install_id,
            actor="operator",
            scope=SCOPE,
            approve=True,
            reason="operator approves",
        )
        assert authorized.state.value == "authorized"
        # The VERIFIED tier ceiling caps the grant below the request:
        assert authorized.granted_permissions == ("network.http",)
        transitions = await service.transitions(record.install_id, scope=SCOPE)
        reason = transitions[-1].reason
        assert "granted 1 of 2 requested permission(s)" in reason
        assert "storage.workspace (trust tier 'verified' ceiling excludes it)" in reason
        assert "decision" in reason

    async def test_loader_receives_the_intersected_grant_record(self) -> None:
        from maistro.extensions.effective_authority import ExtensionAuthorityInputs

        class SpyLoader:
            def __init__(self) -> None:
                self.records = []

            async def load(self, record, payload):  # type: ignore[no-untyped-def]
                self.records.append(record)
                return _loaded(record)

        spy = SpyLoader()
        inputs = ExtensionAuthorityInputs(
            trust_claim=TrustClaim(publisher_id="acme", signature_present=False),
            tier_of={},
            default_tier=TrustTier.VERIFIED,
            host=_host(
                tiers={TrustTier.VERIFIED: ("network.http", "storage.workspace")},
            ),
            caller=_caller(("network.http",)),
            workspace=_workspace(ceiling=("network.http", "storage.workspace")),
        )
        trust_policy = TrustPolicy(trusted_publishers=frozenset({"acme"}), require_signature=False)
        service = ExtensionInstallService(
            InMemoryExtensionStore(),
            loader=spy,
            trust_policy=trust_policy,
            authority_inputs=inputs,
            install_id_factory=lambda: "install-77",
        )
        record = await _inspected(service)
        await service.authorize(
            record.install_id,
            actor="operator",
            scope=SCOPE,
            approve=True,
            reason="operator approves",
        )
        await service.install(record.install_id, actor="operator", scope=SCOPE, payload=PAYLOAD)
        # The loader — the code-execution seam — received the intersected grant.
        assert spy.records[0].granted_permissions == ("network.http",)

    async def test_empty_intersection_denies_despite_operator_approval(self) -> None:
        from maistro.extensions.effective_authority import ExtensionAuthorityInputs

        inputs = ExtensionAuthorityInputs(
            trust_claim=TrustClaim(publisher_id="acme", signature_present=False),
            tier_of={"acme": TrustTier.VERIFIED},
            default_tier=TrustTier.UNVERIFIED,
            host=_host(),
            caller=_caller(),
            workspace=_workspace(enabled=None),
        )
        service = _make_service(authority_inputs=inputs)
        record = await _inspected(service)
        denied = await service.authorize(
            record.install_id,
            actor="operator",
            scope=SCOPE,
            approve=True,
            reason="operator approves",
        )
        assert denied.state.value == "denied"
        assert denied.granted_permissions == ()
        transitions = await service.transitions(record.install_id, scope=SCOPE)
        assert "effective authority is empty" in transitions[-1].reason
        assert "not enabled" in transitions[-1].reason

    async def test_untrusted_evidence_at_authorize_denies(self) -> None:
        from maistro.extensions.effective_authority import ExtensionAuthorityInputs

        inputs = ExtensionAuthorityInputs(
            # Evidence names a publisher the allowlist never trusted:
            trust_claim=TrustClaim(publisher_id="mallory", signature_present=False),
            tier_of={},
            default_tier=TrustTier.VERIFIED,
            host=_host(),
            caller=_caller(),
            workspace=_workspace(),
        )
        service = _make_service(authority_inputs=inputs)
        record = await _inspected(service)
        denied = await service.authorize(
            record.install_id,
            actor="operator",
            scope=SCOPE,
            approve=True,
            reason="operator approves",
        )
        assert denied.state.value == "denied"
        transitions = await service.transitions(record.install_id, scope=SCOPE)
        assert "not trusted" in transitions[-1].reason

    async def test_without_inputs_the_grant_freezes_to_the_request(self) -> None:
        # The #953 contract stays intact when no authority inputs are wired.
        service = _make_service()
        record = await _inspected(service)
        authorized = await service.authorize(
            record.install_id,
            actor="operator",
            scope=SCOPE,
            approve=True,
            reason="operator approves",
        )
        assert authorized.state.value == "authorized"
        assert authorized.granted_permissions == authorized.requested_permissions
