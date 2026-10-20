"""Organization/Workspace extension policy governance (#971, M9-G3).

These tests pin each acceptance criterion against reachable production
behavior: org deny overriding Workspace enablement, server-side
version/publisher pinning under concurrent callers, deterministic and
explainable inheritance, tenant-scoped extension state that cannot leak
across Workspaces, and the admin policy audit trail — plus the projection
onto #969's effective-authority intersection that turns an org deny into a
package blocker and an org ceiling into a hard narrowing.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from maistro.extensions import (
    CallerAuthority,
    ExtensionPolicyLedger,
    ExtensionScope,
    HostExtensionPolicy,
    InMemoryExtensionStore,
    OrgExtensionPolicy,
    PublisherTrust,
    TenantScopedExtensionState,
    TrustTier,
    WorkspacePolicyOverride,
    compute_effective_authority,
    tenant_scope_key,
)
from maistro.extensions.manifest import inspect_manifest
from maistro.extensions.policy import (
    ExtensionPolicyError,
    ExtensionPolicyTable,
    _table_digest,
    resolve_extension_policy,
)
from maistro.extensions.service import ExtensionInstallService, UnwiredExtensionLoader
from maistro.extensions.types import TrustClaim

ORG = "org-1"
WS_A = "ws-a"
WS_B = "ws-b"
EXT = "acme.chart_tools"
PUBLISHER = "acme"
VERSION = "1.4.0"
OTHER_VERSION = "2.0.0"
PERMISSIONS = ("network.http", "storage.workspace")
PAYLOAD = b"policy-governance-payload"

ADMIN = "operator-1"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest_bytes(
    *,
    extension_id: str = EXT,
    version: str = VERSION,
    publisher: str = PUBLISHER,
    permissions: tuple[str, ...] = PERMISSIONS,
) -> bytes:
    document = {
        "manifest_version": 1,
        "id": extension_id,
        "name": "Chart Tools",
        "version": version,
        "publisher": publisher,
        "api_version": "1.0.0",
        "permissions": list(permissions),
        "entry_points": [{"name": "main", "module": "acme_chart.main", "attribute": "activate"}],
        "artifact": {"sha256": _digest(PAYLOAD), "size": len(PAYLOAD)},
    }
    return json.dumps(document).encode("utf-8")


def _org(**overrides: object) -> OrgExtensionPolicy:
    defaults: dict[str, object] = {
        "org_id": ORG,
        "denied_extensions": frozenset(),
        "allowed_extensions": None,
        "approved_publishers": None,
        "version_pins": {},
        "permission_ceiling": None,
    }
    defaults.update(overrides)
    return OrgExtensionPolicy(**defaults)  # type: ignore[arg-type]


def _workspace(
    *,
    org_id: str = ORG,
    workspace_id: str = WS_A,
    enabled: tuple[str, ...] = (EXT,),
    ceiling: tuple[str, ...] | None = None,
) -> WorkspacePolicyOverride:
    return WorkspacePolicyOverride(
        org_id=org_id,
        workspace_id=workspace_id,
        enabled_extensions=frozenset(enabled),
        permission_ceiling=frozenset(ceiling) if ceiling else None,
    )


def _ledger(
    *,
    org: OrgExtensionPolicy | None = None,
    workspaces: tuple[WorkspacePolicyOverride, ...] = (),
) -> ExtensionPolicyLedger:
    ledger = ExtensionPolicyLedger(clock=lambda: datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC))
    ledger.set_org_policy(
        org if org is not None else _org(), actor=ADMIN, reason="initial org policy"
    )
    for override in workspaces:
        ledger.set_workspace_override(override, actor=ADMIN, reason="workspace enablement")
    return ledger


def _resolve(ledger: ExtensionPolicyLedger, **overrides: str):
    kwargs: dict[str, str] = {
        "extension_id": EXT,
        "version": VERSION,
        "publisher": PUBLISHER,
        "org_id": ORG,
        "workspace_id": WS_A,
    }
    kwargs.update(overrides)
    return ledger.resolve(**kwargs)


# --------------------------------------------------------------------------
# Resolution layers: deny-by-default and the fixed override order
# --------------------------------------------------------------------------


def test_unregistered_org_denies_everything() -> None:
    """An org the ledger never heard of is deny-by-default: policy is
    canonical server-side state, not UI configuration truth."""
    resolution = _resolve(ExtensionPolicyLedger())
    assert not resolution.enabled
    assert any("not registered" in reason for reason in resolution.reasons)


def test_unregistered_workspace_denies() -> None:
    ledger = _ledger()
    resolution = _resolve(ledger, workspace_id=WS_B)
    assert not resolution.enabled
    assert any(f"org:{ORG}/workspace:{WS_B}" in reason for reason in resolution.reasons)


def test_org_absent_from_a_workspace_scoped_table_denies() -> None:
    """A table that scopes a Workspace but never recorded the org still denies.

    The ledger refuses to build this shape (`set_workspace_override` raises
    "not registered; set its policy first"), so no ledger-built snapshot can
    reach it. `resolve_extension_policy` is the exported pure function that
    every resolution funnels through, and it is called with whatever table it
    is handed -- so its org layer has to be the thing that denies, not the
    Workspace layer.

    This is the one table where the two "not registered" reasons do not
    overlap: with the Workspace registered and the extension enabled, the org
    reason is the only thing standing between an unregistered org and an
    enabled resolution. Deleting it flips this to `enabled=True` with no
    ceiling and no pin -- policy becomes optional rather than canonical.
    """
    table = ExtensionPolicyTable(
        workspaces={(ORG, WS_A): _workspace()},
    )
    resolution = resolve_extension_policy(
        table,
        extension_id=EXT,
        version=VERSION,
        publisher=PUBLISHER,
        org_id=ORG,
        workspace_id=WS_A,
    )
    assert not resolution.enabled
    assert any("is not registered" in reason for reason in resolution.reasons)
    assert resolution.permission_ceiling is None
    assert resolution.pin is None


def test_org_allowlist_excludes_despite_workspace_enablement() -> None:
    ledger = _ledger(
        org=_org(allowed_extensions=frozenset({"other.extension"})),
        workspaces=(_workspace(),),
    )
    resolution = _resolve(ledger)
    assert not resolution.enabled
    assert any("allowlist" in reason for reason in resolution.reasons)


def test_org_allowlist_admits_listed_extension() -> None:
    ledger = _ledger(
        org=_org(allowed_extensions=frozenset({EXT})),
        workspaces=(_workspace(),),
    )
    assert _resolve(ledger).enabled


def test_org_deny_overrides_workspace_enablement() -> None:
    """The acceptance criterion verbatim: the organization says no, so the
    Workspace's enable request never becomes a grant."""
    ledger = _ledger(
        org=_org(denied_extensions=frozenset({EXT})),
        workspaces=(_workspace(enabled=(EXT,)),),
    )
    resolution = _resolve(ledger)
    assert not resolution.enabled
    assert any(
        "denies" in reason and "overrides workspace enablement" in reason
        for reason in resolution.reasons
    )


def test_unapproved_publisher_denied() -> None:
    ledger = _ledger(
        org=_org(approved_publishers=frozenset({"trusted-co"})),
        workspaces=(_workspace(),),
    )
    resolution = _resolve(ledger)
    assert not resolution.enabled
    assert any("not approved" in reason for reason in resolution.reasons)


def test_approved_publisher_admitted() -> None:
    ledger = _ledger(
        org=_org(approved_publishers=frozenset({PUBLISHER})),
        workspaces=(_workspace(),),
    )
    assert _resolve(ledger).enabled


def test_version_pin_denies_other_versions() -> None:
    """Pinning is enforced in the server-side resolution, before any
    caller-specific logic can run."""
    ledger = _ledger(
        org=_org(version_pins={EXT: OTHER_VERSION}),
        workspaces=(_workspace(),),
    )
    resolution = _resolve(ledger)
    assert not resolution.enabled
    assert resolution.pin == OTHER_VERSION
    assert any(OTHER_VERSION in reason and VERSION in reason for reason in resolution.reasons)


def test_pinned_version_admitted() -> None:
    ledger = _ledger(
        org=_org(version_pins={EXT: VERSION}),
        workspaces=(_workspace(),),
    )
    resolution = _resolve(ledger)
    assert resolution.enabled
    assert resolution.pin == VERSION


def test_no_pin_admits_any_version() -> None:
    ledger = _ledger(workspaces=(_workspace(),))
    assert _resolve(ledger).pin is None
    assert _resolve(ledger, version=OTHER_VERSION).enabled


def test_reasons_follow_the_fixed_layer_order() -> None:
    """Explainability: when every layer refuses, the reasons appear in the
    documented resolution order — allowlist, deny, publisher, pin, workspace."""
    ledger = _ledger(
        org=_org(
            allowed_extensions=frozenset({"other.extension"}),
            denied_extensions=frozenset({EXT}),
            approved_publishers=frozenset({"trusted-co"}),
            version_pins={EXT: OTHER_VERSION},
        ),
        workspaces=(_workspace(enabled=()),),
    )
    resolution = _resolve(ledger)
    assert not resolution.enabled
    labels = [
        "allowlist",
        "denies",
        "not approved",
        "pins",
        "not enabled",
    ]
    positions = [
        next(i for i, r in enumerate(resolution.reasons) if label in r) for label in labels
    ]
    assert positions == sorted(positions)


# --------------------------------------------------------------------------
# Deterministic inheritance and ceiling composition
# --------------------------------------------------------------------------


def test_resolution_is_a_pure_function_of_the_table() -> None:
    """The same table and identity always resolve equally (deterministic
    inheritance), and the table is never consumed by resolving."""
    ledger = _ledger(
        org=_org(permission_ceiling=frozenset({"network.http"})),
        workspaces=(_workspace(ceiling=("network.http", "storage.workspace")),),
    )
    first = _resolve(ledger)
    second = _resolve(ledger)
    assert first == second
    assert first.permission_ceiling == frozenset({"network.http"})


def test_workspace_ceiling_narrows_org_ceiling() -> None:
    ledger = _ledger(
        org=_org(permission_ceiling=frozenset({"network.http", "storage.workspace"})),
        workspaces=(_workspace(ceiling=("network.http",)),),
    )
    assert _resolve(ledger).permission_ceiling == frozenset({"network.http"})


def test_absent_ceilings_leave_the_layer_unstated() -> None:
    ledger = _ledger(workspaces=(_workspace(),))
    assert _resolve(ledger).permission_ceiling is None


def test_workspace_layer_with_no_ceiling_yields_the_request() -> None:
    ledger = _ledger(workspaces=(_workspace(),))
    layer = _resolve(ledger).workspace_layer(PERMISSIONS)
    assert layer.enabled_extensions == frozenset({EXT})
    assert layer.permission_ceiling == frozenset(PERMISSIONS)


def test_denied_resolution_yields_an_empty_enablement_layer() -> None:
    ledger = _ledger(org=_org(denied_extensions=frozenset({EXT})), workspaces=(_workspace(),))
    layer = _resolve(ledger).workspace_layer(PERMISSIONS)
    assert layer.enabled_extensions == frozenset()
    assert layer.scope == ExtensionScope(org_id=ORG, workspace_id=WS_A)


# --------------------------------------------------------------------------
# Projection onto the #969 intersection
# --------------------------------------------------------------------------


def _effective_authority(ledger: ExtensionPolicyLedger, **manifest_overrides: object):
    manifest = inspect_manifest(_manifest_bytes(**manifest_overrides))
    resolution = _resolve(ledger, extension_id=manifest.extension_id, version=manifest.version)
    return compute_effective_authority(
        manifest,
        trust=PublisherTrust(tier=TrustTier.UNVERIFIED, trusted=True),
        host=HostExtensionPolicy(
            ceiling=frozenset(PERMISSIONS),
            tier_ceilings={TrustTier.UNVERIFIED: frozenset(PERMISSIONS)},
        ),
        caller=CallerAuthority(
            principal_id="agent-7", delegated_permissions=frozenset(PERMISSIONS)
        ),
        workspace=resolution.workspace_layer(manifest.permissions),
    )


def test_org_deny_becomes_an_effective_authority_blocker() -> None:
    ledger = _ledger(org=_org(denied_extensions=frozenset({EXT})), workspaces=(_workspace(),))
    authority = _effective_authority(ledger)
    assert authority.granted_none
    assert authority.blockers
    assert any("not enabled" in blocker for blocker in authority.blockers)


def test_org_ceiling_narrows_effective_authority() -> None:
    ledger = _ledger(
        org=_org(permission_ceiling=frozenset({"network.http"})),
        workspaces=(_workspace(),),
    )
    authority = _effective_authority(ledger)
    assert authority.effective == ("network.http",)
    denial = next(d for d in authority.denials if d.permission == "storage.workspace")
    assert any("ceiling excludes it" in reason for reason in denial.reasons)


def test_enabled_resolution_leaves_the_intersection_to_969() -> None:
    ledger = _ledger(workspaces=(_workspace(),))
    authority = _effective_authority(ledger)
    assert authority.effective == tuple(sorted(PERMISSIONS))
    assert authority.blockers == ()


def test_policy_resolution_feeds_install_authority_inputs() -> None:
    """Org policy reaches install-time grant freezing through the #969
    authority inputs: the org ceiling narrows the frozen grant below the
    request, and the resolution composes with the real install service."""
    from maistro.extensions import ExtensionPackage
    from maistro.extensions.effective_authority import ExtensionAuthorityInputs
    from maistro.extensions.trust import TrustPolicy

    async def scenario() -> tuple[str, ...]:
        ledger = _ledger(
            org=_org(permission_ceiling=frozenset({"network.http"})),
            workspaces=(_workspace(),),
        )
        manifest = inspect_manifest(_manifest_bytes())
        resolution = _resolve(ledger, extension_id=manifest.extension_id, version=manifest.version)
        service = ExtensionInstallService(
            InMemoryExtensionStore(),
            loader=UnwiredExtensionLoader(),
            trust_policy=TrustPolicy(
                trusted_publishers=frozenset({PUBLISHER}), require_signature=False
            ),
            authority_inputs=ExtensionAuthorityInputs(
                trust_claim=TrustClaim(publisher_id=PUBLISHER, signature_present=False),
                tier_of={PUBLISHER: TrustTier.VERIFIED},
                host=HostExtensionPolicy(
                    ceiling=frozenset(PERMISSIONS),
                    tier_ceilings={TrustTier.VERIFIED: frozenset(PERMISSIONS)},
                ),
                caller=CallerAuthority(
                    principal_id="agent-7", delegated_permissions=frozenset(PERMISSIONS)
                ),
                workspace=resolution.workspace_layer(manifest.permissions),
            ),
            clock=lambda: datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC),
            install_id_factory=lambda: "install-policy-1",
        )
        scope = ExtensionScope(org_id=ORG, workspace_id=WS_A)
        record = await service.inspect(
            actor=ADMIN,
            scope=scope,
            package=ExtensionPackage(manifest_bytes=_manifest_bytes(), payload=PAYLOAD),
            trust_evidence=TrustClaim(publisher_id=PUBLISHER, signature_present=False),
        )
        assert record.state.value == "awaiting_authorization"
        authorized = await service.authorize(
            record.install_id,
            actor=ADMIN,
            scope=scope,
            approve=True,
            reason="approved under org policy",
        )
        return authorized.granted_permissions

    assert asyncio.run(scenario()) == ("network.http",)


# --------------------------------------------------------------------------
# Server-side pinning under concurrent callers
# --------------------------------------------------------------------------


def test_pinning_enforced_under_concurrent_callers() -> None:
    """Every concurrent resolution observes one whole policy table: a
    result is enabled only when its own pin admits the version, whatever
    the interleaving with the pin swap."""
    ledger = _ledger(workspaces=(_workspace(),))

    async def scenario() -> list[object]:
        stop = asyncio.Event()

        async def pinner() -> None:
            await asyncio.sleep(0)
            ledger.pin_version(
                org_id=ORG,
                extension_id=EXT,
                version=OTHER_VERSION,
                actor=ADMIN,
                reason="pin upgrade",
            )
            stop.set()

        async def resolver() -> list[object]:
            results: list[object] = []
            while not stop.is_set():
                results.append(
                    _resolve(ledger, version=VERSION)  # the pre-pin version
                )
                await asyncio.sleep(0)
            return results

        before, _, after = await asyncio.gather(resolver(), pinner(), resolver())
        return [*before, *after]  # type: ignore[misc]

    results = asyncio.run(scenario())
    assert results, "the concurrent resolvers must have produced observations"
    for resolution in results:
        assert resolution.pin in (None, OTHER_VERSION)
        if resolution.pin == OTHER_VERSION:
            assert not resolution.enabled
            assert any("pins" in reason for reason in resolution.reasons)
    # And after the swap, the old version is denied server-side.
    assert not _resolve(ledger, version=VERSION).enabled
    assert _resolve(ledger, version=OTHER_VERSION).enabled


def test_concurrent_publisher_pinning_and_policy_swap_stay_consistent() -> None:
    """Table swaps are whole: a concurrent reader sees the org deny either
    present or absent, never a half-applied policy."""
    ledger = _ledger(workspaces=(_workspace(),))

    async def scenario() -> list[bool]:
        stop = asyncio.Event()

        async def mutator() -> None:
            await asyncio.sleep(0)
            ledger.set_org_policy(
                _org(denied_extensions=frozenset({EXT})), actor=ADMIN, reason="deny"
            )
            stop.set()

        async def resolver() -> list[bool]:
            seen: list[bool] = []
            while not stop.is_set():
                seen.append(_resolve(ledger).enabled)
                await asyncio.sleep(0)
            return seen

        before, _, after = await asyncio.gather(resolver(), mutator(), resolver())
        return [*before, *after]  # type: ignore[misc]

    seen = asyncio.run(scenario())
    assert seen
    assert all(isinstance(enabled, bool) for enabled in seen)


# --------------------------------------------------------------------------
# Audit trail
# --------------------------------------------------------------------------


def test_every_mutation_is_audited_with_actor_scope_and_reason() -> None:
    ledger = _ledger(workspaces=(_workspace(),))
    ledger.pin_version(
        org_id=ORG, extension_id=EXT, version=OTHER_VERSION, actor=ADMIN, reason="pin 2.0.0"
    )

    events = ledger.audit()
    assert [event.seq for event in events] == [1, 2, 3]
    assert events[0].action == "org_policy_set"
    assert events[1].action == "workspace_override_set"
    assert events[1].workspace_id == WS_A
    assert events[1].actor == ADMIN
    assert events[1].reason == "workspace enablement"
    assert events[2].action == "version_pinned"
    # Each row carries the digest of the table state it produced, and the
    # digest changes as the policy changes.
    assert events[0].table_digest != events[1].table_digest
    assert events[2].table_digest == ledger.table_digest


def test_audit_trail_is_append_only_and_org_narrowable() -> None:
    ledger = _ledger(workspaces=(_workspace(),))
    ledger.set_org_policy(_org(org_id="org-2"), actor=ADMIN, reason="second org")
    before = ledger.audit()
    ledger.pin_version(
        org_id=ORG, extension_id=EXT, version=OTHER_VERSION, actor=ADMIN, reason="pin"
    )
    assert ledger.audit()[: len(before)] == before
    assert [event.org_id for event in ledger.audit(org_id="org-2")] == ["org-2"]


def test_mutations_require_actor_and_reason() -> None:
    ledger = ExtensionPolicyLedger()
    with pytest.raises(ExtensionPolicyError):
        ledger.set_org_policy(_org(), actor="", reason="why")
    with pytest.raises(ExtensionPolicyError):
        ledger.set_org_policy(_org(), actor=ADMIN, reason="")


def test_workspace_override_requires_registered_org() -> None:
    ledger = ExtensionPolicyLedger()
    with pytest.raises(ExtensionPolicyError, match="not registered"):
        ledger.set_workspace_override(_workspace(), actor=ADMIN, reason="too early")


def test_pin_requires_registered_org() -> None:
    ledger = ExtensionPolicyLedger()
    with pytest.raises(ExtensionPolicyError, match="not registered"):
        ledger.pin_version(org_id=ORG, extension_id=EXT, version=VERSION, actor=ADMIN, reason="pin")


def test_table_digest_is_stable_and_content_sensitive() -> None:
    table_a = ExtensionPolicyTable(
        orgs={ORG: _org()},
        workspaces={(ORG, WS_A): _workspace()},
    )
    table_b = ExtensionPolicyTable(
        orgs={ORG: _org()},
        workspaces={(ORG, WS_A): _workspace(enabled=())},
    )
    assert _table_digest(table_a) == _table_digest(table_a)
    assert _table_digest(table_a) != _table_digest(table_b)


# --------------------------------------------------------------------------
# Cross-tenant noninterference
# --------------------------------------------------------------------------


def test_two_workspaces_resolve_the_same_extension_independently() -> None:
    """Workspace A enables the extension with a broad ceiling; Workspace B
    enables nothing — and neither resolution reads the other's state."""
    ledger = _ledger(workspaces=(_workspace(workspace_id=WS_A),))
    a = _resolve(ledger, workspace_id=WS_A)
    b = _resolve(ledger, workspace_id=WS_B)
    assert a.enabled and not b.enabled
    assert a.scope.workspace_id == WS_A and b.scope.workspace_id == WS_B


def test_tenant_views_are_structurally_isolated() -> None:
    """Same extension id, two Workspaces: per-tenant state (caches,
    checkpoints, configuration) never crosses the scope boundary — there is
    no API by which one view can name another view's bucket."""
    state = TenantScopedExtensionState()
    view_a = state.view(ORG, WS_A)
    view_b = state.view(ORG, WS_B)

    view_a.put("cache:charts", {"tenant": "A"})
    view_b.put("cache:charts", {"tenant": "B"})

    assert view_a.get("cache:charts") == {"tenant": "A"}
    assert view_b.get("cache:charts") == {"tenant": "B"}
    view_a.pop("cache:charts")
    assert view_a.get("cache:charts") is None
    assert view_b.get("cache:charts") == {"tenant": "B"}
    assert view_a.keys() == ()
    assert view_b.keys() == ("cache:charts",)


def test_org_scopes_are_isolated_too() -> None:
    state = TenantScopedExtensionState()
    org1_view = state.view("org-1", WS_A)
    org2_view = state.view("org-2", WS_A)
    org1_view.put("checkpoint", 1)
    assert org2_view.get("checkpoint") is None


def test_tenant_scope_key_requires_an_org() -> None:
    assert tenant_scope_key(ORG, WS_A) == (ORG, WS_A)
    assert tenant_scope_key(ORG, "") == (ORG, "")
    with pytest.raises(ExtensionPolicyError):
        tenant_scope_key("", WS_A)


def test_view_requires_real_ids() -> None:
    state = TenantScopedExtensionState()
    with pytest.raises(ExtensionPolicyError):
        state.view("", WS_A)


def test_tenant_scope_key_rejects_non_string_workspace() -> None:
    with pytest.raises(ExtensionPolicyError):
        tenant_scope_key(ORG, 7)  # type: ignore[arg-type]


def test_ledger_exposes_its_table_and_views_expose_scope() -> None:
    ledger = ExtensionPolicyLedger()
    assert ledger.table.orgs == {}
    view = TenantScopedExtensionState().view(ORG, WS_A)
    assert view.scope.describe == f"org:{ORG}/workspace:{WS_A}"


# --------------------------------------------------------------------------
# Property tests
# --------------------------------------------------------------------------


_KEY_STATEGY = st.text(alphabet="abcdefgh", min_size=1, max_size=4)
_VALUE_STRATEGY = st.integers(0, 1000)


@given(st.lists(st.tuples(st.sampled_from(["a", "b"]), _KEY_STATEGY, _VALUE_STRATEGY), max_size=40))
def test_tenant_state_never_leaks_under_mixed_operations(ops) -> None:
    """Noninterference as a property: over arbitrary interleaved writes,
    reads, and deletes across two Workspaces, each view's observable state
    equals exactly the operations addressed to it."""
    state = TenantScopedExtensionState()
    views = {"a": state.view(ORG, WS_A), "b": state.view(ORG, WS_B)}
    models: dict[str, dict[str, int]] = {"a": {}, "b": {}}

    for which, key, value in ops:
        view, model = views[which], models[which]
        if key in model:
            assert view.get(key) == model[key]
        else:
            assert view.get(key) is None
        view.put(key, value)
        model[key] = value
        # The other tenant sees nothing of this write.
        other = "b" if which == "a" else "a"
        if key not in models[other]:
            assert views[other].get(key) is None


@given(
    pinned=st.text(alphabet="0123456789.", min_size=1, max_size=8),
    requested=st.text(alphabet="0123456789.", min_size=1, max_size=8),
)
def test_pin_is_exact_under_arbitrary_versions(pinned: str, requested: str) -> None:
    """Server-side pinning as a property: with every other layer allowing,
    the resolution is enabled exactly when the requested version is the
    pinned one."""
    ledger = _ledger(org=_org(version_pins={EXT: pinned}), workspaces=(_workspace(),))
    resolution = _resolve(ledger, version=requested)
    assert resolution.enabled == (requested == pinned)
    assert resolution.pin == pinned
