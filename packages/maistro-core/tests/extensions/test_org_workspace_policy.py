"""Organization/Workspace extension policy, pinning, and noninterference.

These tests drive #971 (M9-G3) against reachable production behavior, one
cluster per acceptance criterion:

- cross-Workspace noninterference of *invocation* (policy enablement) and of
  *observability/state* (tenant-keyed config/cache/checkpoints);
- organization deny overriding a Workspace enable request — at the engine and
  at every install-machine phase it can matter;
- version/publisher pinning enforced server-side, including under concurrent
  callers and across a policy change racing an activation;
- deterministic, explainable resolution (fixed rule order, full trace);
- hypothesis property tests over mixed operations in multiple Workspaces.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from maistro.container import Container
from maistro.extensions import (
    ExtensionCandidate,
    ExtensionPin,
    ExtensionPolicyEngine,
    ExtensionPolicyViolation,
    ExtensionScope,
    InMemoryExtensionStore,
    InvalidTransition,
    OrgExtensionPolicy,
    PolicyAuditLog,
    PolicyConfigurationError,
    PolicyLayer,
    PolicyVerdict,
    TrustPolicy,
    UnknownInstall,
)
from maistro.extensions.policy import INHERITANCE_SEMANTICS, WorkspaceExtensionPolicy
from maistro.extensions.service import (
    ExtensionCodeLoader,
    ExtensionInstallService,
    LoadedExtension,
)
from maistro.extensions.tenancy import TenantScopedExtensionState, tenant_scope_key
from maistro.extensions.types import ExtensionPackage, ExtensionState, TrustClaim

PAYLOAD = b"extension-payload-v1"
TRUST = TrustClaim(publisher_id="acme", signature_present=True, signer_key_id="key-1")
TRUST_POLICY = TrustPolicy(
    trusted_publishers=frozenset({"acme"}),
    require_signature=True,
    allowed_signer_keys=frozenset({"key-1"}),
)

_ids = iter(f"install-{n}" for n in range(100000))


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_bytes(
    *,
    extension_id: str = "acme.chart_tools",
    version: str = "1.4.0",
    permissions: tuple[str, ...] = ("network.http", "storage.workspace"),
    publisher: str = "acme",
    payload: bytes = PAYLOAD,
) -> bytes:
    """A valid manifest whose artifact claim describes ``payload`` exactly."""
    document = {
        "manifest_version": 1,
        "id": extension_id,
        "name": "Chart Tools",
        "version": version,
        "publisher": publisher,
        "api_version": "1.0.0",
        "permissions": list(permissions),
        "entry_points": [{"name": "main", "module": "acme_chart.main", "attribute": "activate"}],
        "artifact": {"sha256": _digest(payload), "size": len(payload)},
    }
    return json.dumps(document).encode("utf-8")


class RecordingLoader:
    """Loader spy: records every activation the machine actually reached."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def load(self, record: Any, payload: bytes) -> LoadedExtension:
        self.calls.append((record.extension_id, record.version))
        return LoadedExtension(extension_id=record.extension_id, version=record.version)


def make_service(
    *,
    engine: ExtensionPolicyEngine | None = None,
    store: InMemoryExtensionStore | None = None,
    loader: ExtensionCodeLoader | None = None,
) -> tuple[ExtensionInstallService, InMemoryExtensionStore, ExtensionCodeLoader]:
    """A service wired exactly as production wires it, policy optional."""
    chosen_loader = loader if loader is not None else RecordingLoader()
    chosen_store = store if store is not None else InMemoryExtensionStore()
    service = ExtensionInstallService(
        chosen_store,
        loader=chosen_loader,
        trust_policy=TRUST_POLICY,
        platform_api_version="1.0.0",
        clock=lambda: datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC),
        authorization_ttl=timedelta(minutes=15),
        install_id_factory=lambda: next(_ids),
        policy_engine=engine,
    )
    return service, chosen_store, chosen_loader


def candidate(
    extension_id: str = "acme.chart_tools",
    version: str = "1.4.0",
    publisher: str = "acme",
    permissions: tuple[str, ...] = ("network.http", "storage.workspace"),
) -> ExtensionCandidate:
    return ExtensionCandidate(
        extension_id=extension_id,
        version=version,
        publisher=publisher,
        permissions=permissions,
    )


async def inspect_candidate(
    service: ExtensionInstallService,
    scope: ExtensionScope,
    *,
    version: str = "1.4.0",
    extension_id: str = "acme.chart_tools",
    actor: str = "operator-1",
):
    return await service.inspect(
        actor=actor,
        scope=scope,
        package=ExtensionPackage(
            manifest_bytes=manifest_bytes(extension_id=extension_id, version=version),
            payload=PAYLOAD,
        ),
        trust_evidence=TRUST,
    )


async def drive_to_authorized(service: ExtensionInstallService, scope: ExtensionScope) -> str:
    """Inspect + authorize through the real machine; policy must allow."""
    inspected = await inspect_candidate(service, scope)
    decided = await service.authorize(
        inspected.install_id,
        actor="operator-1",
        scope=scope,
        approve=True,
        reason="reviewed",
    )
    return decided.install_id


# ---------------------------------------------------------------------------
# Engine-level resolution: deterministic and explainable
# ---------------------------------------------------------------------------


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
class TestPolicyResolution:
    async def test_deterministic_same_inputs_same_decision(self) -> None:
        engine = ExtensionPolicyEngine()
        await engine.set_org_policy(
            OrgExtensionPolicy(
                org_id="org-1",
                denied_extensions=frozenset({"bad.ext"}),
                approved_publishers=frozenset({"acme"}),
                pins={"acme.chart_tools": ExtensionPin(publisher_id="acme", version="1.2.3")},
            ),
            actor="org-admin",
        )
        await engine.set_workspace_policy(
            WorkspaceExtensionPolicy(
                org_id="org-1",
                workspace_id="ws-a",
                enabled_extensions=frozenset({"acme.chart_tools"}),
                permission_ceilings={"acme.chart_tools": frozenset({"network.http"})},
            ),
            actor="ws-admin",
        )
        scope = ExtensionScope(org_id="org-1", workspace_id="ws-a")
        first = engine.explain(candidate(), scope)
        for _ in range(5):
            assert engine.explain(candidate(), scope) == first
        # The decision carries the full candidate and scope identity, so the
        # audit row answers "what was decided, where, and why" by itself.
        assert (first.org_id, first.workspace_id) == ("org-1", "ws-a")
        assert (first.extension_id, first.version, first.publisher) == (
            "acme.chart_tools",
            "1.4.0",
            "acme",
        )

    async def test_trace_evaluates_rules_in_fixed_order(self) -> None:
        engine = ExtensionPolicyEngine()
        await engine.set_org_policy(
            OrgExtensionPolicy(
                org_id="org-1",
                allowed_extensions=frozenset({"acme.chart_tools"}),
                approved_publishers=frozenset({"acme"}),
            ),
            actor="org-admin",
        )
        await engine.set_workspace_policy(
            WorkspaceExtensionPolicy(
                org_id="org-1",
                workspace_id="ws-a",
                enabled_extensions=frozenset({"acme.chart_tools"}),
            ),
            actor="ws-admin",
        )
        decision = engine.explain(candidate(), ExtensionScope("org-1", "ws-a"))
        assert [outcome.rule for outcome in decision.trace] == [
            "org.deny-list",
            "org.allow-list",
            "org.approved-publishers",
            "org.pin",
            "workspace.deny-list",
            "workspace.enablement",
            "workspace.permission-ceiling",
        ]
        assert decision.allowed
        # Explainable when allowed too: the trace names every rule consulted.
        assert "org.allow-list" in decision.explanation

    async def test_org_deny_overrides_workspace_enable(self) -> None:
        engine = ExtensionPolicyEngine()
        await engine.set_org_policy(
            OrgExtensionPolicy(org_id="org-1", denied_extensions=frozenset({"acme.chart_tools"})),
            actor="org-admin",
        )
        await engine.set_workspace_policy(
            WorkspaceExtensionPolicy(
                org_id="org-1",
                workspace_id="ws-a",
                enabled_extensions=frozenset({"acme.chart_tools"}),
            ),
            actor="ws-admin",
        )
        decision = engine.explain(candidate(), ExtensionScope("org-1", "ws-a"))
        assert decision.verdict is PolicyVerdict.DENY
        assert "organization deny-list" in decision.explanation
        # The Workspace layer is recorded as skipped, not silently absent:
        # the org layer decided, and no Workspace rule was consulted.
        skipped = [o for o in decision.trace if o.rule == "workspace.skipped"]
        assert len(skipped) == 1
        assert skipped[0].layer is PolicyLayer.WORKSPACE

    async def test_publisher_and_version_pins_are_separately_explained(self) -> None:
        engine = ExtensionPolicyEngine()
        await engine.set_org_policy(
            OrgExtensionPolicy(
                org_id="org-1",
                pins={
                    "acme.chart_tools": ExtensionPin(publisher_id="acme", version="1.2.3"),
                    "other.ext": ExtensionPin(publisher_id="someone-else"),
                },
            ),
            actor="org-admin",
        )
        scope = ExtensionScope("org-1", "ws-a")
        wrong_version = engine.explain(candidate(version="9.9.9"), scope)
        assert wrong_version.verdict is PolicyVerdict.DENY
        assert "organization pin requires version 1.2.3" in wrong_version.explanation
        wrong_publisher = engine.explain(
            candidate(extension_id="other.ext", publisher="acme"), scope
        )
        assert wrong_publisher.verdict is PolicyVerdict.DENY
        assert "organization pin requires publisher" in wrong_publisher.explanation
        pinned_ok = engine.explain(candidate(version="1.2.3"), scope)
        assert pinned_ok.allowed

    async def test_workspace_policy_switches_to_opt_in_enablement(self) -> None:
        engine = ExtensionPolicyEngine()
        await engine.set_workspace_policy(
            WorkspaceExtensionPolicy(
                org_id="org-1",
                workspace_id="ws-b",
                enabled_extensions=frozenset({"other.ext"}),
            ),
            actor="ws-admin",
        )
        decision = engine.explain(candidate(), ExtensionScope("org-1", "ws-b"))
        assert decision.verdict is PolicyVerdict.DENY
        assert "not enabled for Workspace ws-b" in decision.explanation

    async def test_workspace_without_policy_inherits_org_layer_unchanged(self) -> None:
        engine = ExtensionPolicyEngine()
        await engine.set_org_policy(
            OrgExtensionPolicy(org_id="org-1", approved_publishers=frozenset({"acme"})),
            actor="org-admin",
        )
        allowed = engine.explain(candidate(), ExtensionScope("org-1", "ws-b"))
        assert allowed.allowed
        assert [o.rule for o in allowed.trace if o.rule == "workspace.default"] == [
            "workspace.default"
        ]
        # Org gates still bind a policy-less workspace: a non-approved
        # publisher is denied there with the org reason.
        denied = engine.explain(candidate(publisher="evil-co"), ExtensionScope("org-1", "ws-b"))
        assert denied.verdict is PolicyVerdict.DENY
        assert "not approved by the organization" in denied.explanation

    async def test_permission_ceiling_fails_closed_and_names_offending_permissions(self) -> None:
        engine = ExtensionPolicyEngine()
        await engine.set_workspace_policy(
            WorkspaceExtensionPolicy(
                org_id="org-1",
                workspace_id="ws-a",
                enabled_extensions=frozenset({"acme.chart_tools"}),
                permission_ceilings={"acme.chart_tools": frozenset({"network.http"})},
            ),
            actor="ws-admin",
        )
        decision = engine.explain(candidate(), ExtensionScope("org-1", "ws-a"))
        assert decision.verdict is PolicyVerdict.DENY
        assert "storage.workspace" in decision.explanation
        within = engine.explain(
            candidate(permissions=("network.http",)), ExtensionScope("org-1", "ws-a")
        )
        assert within.allowed

    async def test_unconfigured_layers_impose_nothing_and_say_so(self) -> None:
        engine = ExtensionPolicyEngine()
        decision = engine.explain(candidate(), ExtensionScope("org-9", "ws-x"))
        assert decision.allowed
        assert [o.rule for o in decision.trace] == ["org.default", "workspace.default"]
        org_default = next(o for o in decision.trace if o.rule == "org.default")
        assert "imposes nothing" in org_default.detail

    async def test_explain_is_a_dry_run_with_no_audit_row(self) -> None:
        log = PolicyAuditLog()
        engine = ExtensionPolicyEngine(audit=log)
        engine.explain(candidate(), ExtensionScope("org-1", "ws-a"))
        assert engine.audit_events("org-1") == ()
        engine.evaluate(candidate(), ExtensionScope("org-1", "ws-a"), actor="svc")
        events = engine.audit_events("org-1")
        assert [e.kind for e in events] == ["decision"]
        assert events[0].actor == "svc"

    async def test_policy_changes_and_decisions_are_all_audited(self) -> None:
        engine = ExtensionPolicyEngine()
        await engine.set_org_policy(
            OrgExtensionPolicy(org_id="org-1", denied_extensions=frozenset({"bad.ext"})),
            actor="org-admin",
        )
        await engine.set_workspace_policy(
            WorkspaceExtensionPolicy(org_id="org-1", workspace_id="ws-a"),
            actor="ws-admin",
        )
        engine.evaluate(candidate(), ExtensionScope("org-1", "ws-a"), actor="svc")
        kinds = [(e.kind, e.actor) for e in engine.audit_events("org-1")]
        assert kinds == [
            ("org-policy-set", "org-admin"),
            ("workspace-policy-set", "ws-admin"),
            ("decision", "svc"),
        ]
        # The trail filters for inspection without rewriting anything.
        ws_only = engine.audit_events("org-1", workspace_id="ws-a")
        assert [e.kind for e in ws_only] == ["workspace-policy-set", "decision"]
        assert len(engine.audit_events("org-1", kind="decision")) == 1

    async def test_published_policy_is_caller_proof(self) -> None:
        """A retained reference cannot change enforcement behind the engine's back.

        ``set_org_policy``/``set_workspace_policy`` publish immutable
        snapshots: mutating the caller's dict/set after the call returns must
        not alter any decision, and such a mutation — which bypassed the
        per-org lock — must leave no audit row. Every assertion here fails
        against an engine that stores the submitted policy object as-is.
        """
        engine = ExtensionPolicyEngine()
        pins: dict[str, ExtensionPin] = {
            "acme.chart_tools": ExtensionPin(publisher_id="acme"),
        }
        allowed: set[str] = {"acme.chart_tools"}
        await engine.set_org_policy(
            OrgExtensionPolicy(org_id="org-1", allowed_extensions=allowed, pins=pins),
            actor="org-admin",
        )
        ceilings: dict[str, set[str]] = {"acme.chart_tools": {"network.http"}}
        enabled: set[str] = {"acme.chart_tools"}
        await engine.set_workspace_policy(
            WorkspaceExtensionPolicy(
                org_id="org-1",
                workspace_id="ws-1",
                enabled_extensions=enabled,
                permission_ceilings=ceilings,
            ),
            actor="ws-admin",
        )

        # The caller keeps every reference and mutates them post-publication:
        # a version-pin tightening, an allow-list/enablement widening, and a
        # ceiling widening. None of this may reach enforcement.
        pins["acme.chart_tools"] = ExtensionPin(publisher_id="acme", version="9.9.9")
        pins["evil.ext"] = ExtensionPin(publisher_id="evil")
        allowed.add("evil.ext")
        enabled.add("evil.ext")
        ceilings["acme.chart_tools"] = {"network.http", "host.exec"}
        ceilings["evil.ext"] = {"host.exec"}
        scope = ExtensionScope("org-1", "ws-1")

        # evil.ext stays outside the published allow-list and enablement; if
        # either collection were aliased it would now be admitted.
        assert not engine.explain(
            candidate(extension_id="evil.ext", publisher="evil", permissions=("host.exec",)),
            scope,
        ).allowed
        # The published pin binds the publisher only: 2.0.0 is still admitted
        # even though the caller's dict now pins 9.9.9.
        assert engine.explain(
            candidate(version="2.0.0", permissions=("network.http",)), scope
        ).allowed
        # The published ceiling still excludes host.exec.
        ceiling_decision = engine.explain(
            candidate(permissions=("network.http", "host.exec")), scope
        )
        assert not ceiling_decision.allowed
        ceiling_outcome = next(
            o for o in ceiling_decision.trace if o.rule == "workspace.permission-ceiling"
        )
        assert "host.exec" in ceiling_outcome.detail

        # The side channel wrote no evidence: enforcement only changes through
        # set_org_policy, inside the lock, with an audit row.
        assert [e.kind for e in engine.audit_events("org-1")] == [
            "org-policy-set",
            "workspace-policy-set",
        ]

        # What is stored is itself immutable, not merely equal.
        stored_org = engine.org_policy("org-1")
        assert stored_org is not None
        assert isinstance(stored_org.allowed_extensions, frozenset)
        assert isinstance(stored_org.pins, MappingProxyType)
        with pytest.raises(FrozenInstanceError):
            stored_org.denied_extensions = frozenset({"acme.chart_tools"})  # type: ignore[misc]
        with pytest.raises(TypeError):
            stored_org.pins["evil.ext"] = ExtensionPin(publisher_id="evil")  # type: ignore[index]
        stored_ws = engine.workspace_policy("org-1", "ws-1")
        assert stored_ws is not None
        assert isinstance(stored_ws.permission_ceilings, MappingProxyType)
        assert isinstance(stored_ws.permission_ceilings["acme.chart_tools"], frozenset)

    async def test_malformed_policies_are_refused(self) -> None:
        engine = ExtensionPolicyEngine()
        with pytest.raises(PolicyConfigurationError):
            await engine.set_org_policy(OrgExtensionPolicy(org_id="  "), actor="org-admin")
        with pytest.raises(PolicyConfigurationError):
            await engine.set_org_policy(
                OrgExtensionPolicy(
                    org_id="org-1",
                    pins={"acme.chart_tools": ExtensionPin(publisher_id="acme", version=" ")},
                ),
                actor="org-admin",
            )
        with pytest.raises(PolicyConfigurationError):
            await engine.set_workspace_policy(
                WorkspaceExtensionPolicy(
                    org_id="org-1",
                    workspace_id="ws-a",
                    # Ceiling tokens must use the shared permission grammar.
                    permission_ceilings={"acme.chart_tools": frozenset({"BAD TOKEN"})},
                ),
                actor="ws-admin",
            )
        with pytest.raises(PolicyConfigurationError):
            await engine.set_workspace_policy(
                WorkspaceExtensionPolicy(org_id="org-1", workspace_id=""),
                actor="ws-admin",
            )
        # Refusals leave no policy and no audit row.
        assert engine.org_policy("org-1") is None
        assert engine.workspace_policy("org-1", "ws-a") is None
        assert engine.audit_events("org-1") == ()

    def test_inheritance_semantics_are_published_for_inspection(self) -> None:
        # The static half of "deterministic and explainable": the layer model
        # is a published constant the admin surface serves verbatim.
        assert len(INHERITANCE_SEMANTICS) == 7
        assert any("deny" in rule for rule in INHERITANCE_SEMANTICS)


# ---------------------------------------------------------------------------
# Install-machine enforcement
# ---------------------------------------------------------------------------


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
class TestServiceEnforcement:
    async def test_inspection_of_org_denied_extension_is_rejected_at_the_door(self) -> None:
        engine = ExtensionPolicyEngine()
        await engine.set_org_policy(
            OrgExtensionPolicy(org_id="org-1", denied_extensions=frozenset({"acme.chart_tools"})),
            actor="org-admin",
        )
        service, store, loader = make_service(engine=engine)
        scope = ExtensionScope("org-1", "ws-1")
        record = await inspect_candidate(service, scope)
        assert record.state is ExtensionState.REJECTED
        assert "denied by extension policy" in (record.failure_reason or "")
        assert "organization deny-list" in (record.failure_reason or "")
        # Nothing parked for authorization: there is no open request an
        # operator could approve, and no code ever ran.
        assert await store.active_record(scope, "acme.chart_tools") is None
        assert loader.calls == []

    async def test_org_deny_overrides_workspace_enable_request_at_authorization(self) -> None:
        """The acceptance order that matters: inspected while allowed, denied
        once the organization denies — the Workspace enable request loses."""
        engine = ExtensionPolicyEngine()
        await engine.set_workspace_policy(
            WorkspaceExtensionPolicy(
                org_id="org-1",
                workspace_id="ws-1",
                enabled_extensions=frozenset({"acme.chart_tools"}),
            ),
            actor="ws-admin",
        )
        service, store, loader = make_service(engine=engine)
        scope = ExtensionScope("org-1", "ws-1")
        inspected = await inspect_candidate(service, scope)
        assert inspected.state is ExtensionState.AWAITING_AUTHORIZATION

        await engine.set_org_policy(
            OrgExtensionPolicy(org_id="org-1", denied_extensions=frozenset({"acme.chart_tools"})),
            actor="org-admin",
        )
        decided = await service.authorize(
            inspected.install_id,
            actor="operator-1",
            scope=scope,
            approve=True,
            reason="workspace requests enablement",
        )
        assert decided.state is ExtensionState.DENIED
        assert "extension policy overrides this enablement" in (decided.failure_reason or "")
        # Denial is terminal and leaves nothing active.
        assert await store.active_record(scope, "acme.chart_tools") is None
        assert loader.calls == []

    async def test_activation_after_a_pin_lands_is_refused_and_record_unchanged(self) -> None:
        engine = ExtensionPolicyEngine()
        service, store, loader = make_service(engine=engine)
        scope = ExtensionScope("org-1", "ws-1")
        install_id = await drive_to_authorized(service, scope)

        await engine.set_org_policy(
            OrgExtensionPolicy(
                org_id="org-1",
                pins={"acme.chart_tools": ExtensionPin(publisher_id="acme", version="1.2.3")},
            ),
            actor="org-admin",
        )
        with pytest.raises(ExtensionPolicyViolation) as excinfo:
            await service.install(install_id, actor="operator-1", scope=scope, payload=PAYLOAD)
        assert "organization pin requires version 1.2.3" in str(excinfo.value)
        # The record keeps its AUTHORIZED state: the approval stands, the
        # policy blocks activation. No INSTALLING/FAILED churn, no code run.
        record = await service.get(install_id, scope=scope)
        assert record.state is ExtensionState.AUTHORIZED
        assert loader.calls == []
        assert await store.active_record(scope, "acme.chart_tools") is None

    async def test_authorized_records_cannot_install_after_an_org_deny(self) -> None:
        engine = ExtensionPolicyEngine()
        service, store, loader = make_service(engine=engine)
        scope = ExtensionScope("org-1", "ws-1")
        install_id = await drive_to_authorized(service, scope)
        await engine.set_org_policy(
            OrgExtensionPolicy(org_id="org-1", denied_extensions=frozenset({"acme.chart_tools"})),
            actor="org-admin",
        )
        with pytest.raises(ExtensionPolicyViolation):
            await service.install(install_id, actor="operator-1", scope=scope, payload=PAYLOAD)
        assert await store.active_record(scope, "acme.chart_tools") is None
        assert loader.calls == []

    async def test_pinned_version_installs_end_to_end(self) -> None:
        engine = ExtensionPolicyEngine()
        await engine.set_org_policy(
            OrgExtensionPolicy(
                org_id="org-1",
                pins={"acme.chart_tools": ExtensionPin(publisher_id="acme", version="1.4.0")},
            ),
            actor="org-admin",
        )
        await engine.set_workspace_policy(
            WorkspaceExtensionPolicy(
                org_id="org-1",
                workspace_id="ws-1",
                enabled_extensions=frozenset({"acme.chart_tools"}),
            ),
            actor="ws-admin",
        )
        service, store, loader = make_service(engine=engine)
        scope = ExtensionScope("org-1", "ws-1")
        install_id = await drive_to_authorized(service, scope)
        active = await service.install(install_id, actor="operator-1", scope=scope, payload=PAYLOAD)
        assert active.state is ExtensionState.ACTIVE
        assert loader.calls == [("acme.chart_tools", "1.4.0")]
        assert await store.active_record(scope, "acme.chart_tools") is not None

    async def test_pin_enforced_under_concurrent_callers(self) -> None:
        """N callers race full flows of an unpinned version; the pin exists
        before any of them start, so every path must refuse and nothing may
        activate — however the event loop interleaves them."""
        engine = ExtensionPolicyEngine()
        await engine.set_org_policy(
            OrgExtensionPolicy(
                org_id="org-1",
                pins={"acme.chart_tools": ExtensionPin(publisher_id="acme", version="1.2.3")},
            ),
            actor="org-admin",
        )
        service, store, loader = make_service(engine=engine)
        scope = ExtensionScope("org-1", "ws-1")

        async def one_flow() -> str:
            inspected = await inspect_candidate(service, scope, version="1.4.0")
            assert inspected.state is ExtensionState.REJECTED
            with pytest.raises(InvalidTransition):
                await service.authorize(
                    inspected.install_id,
                    actor="operator-1",
                    scope=scope,
                    approve=True,
                    reason="racing the pin",
                )
            return inspected.install_id

        results = await asyncio.gather(*(one_flow() for _ in range(8)))
        assert len(set(results)) == 8, "every caller got its own durable refusal"
        assert loader.calls == []
        assert await store.active_record(scope, "acme.chart_tools") is None
        decisions = engine.audit_events("org-1", kind="decision")
        assert len(decisions) == 8
        assert all("pin requires version 1.2.3" in e.detail for e in decisions)

    async def test_policy_set_serializes_against_an_in_flight_activation(self) -> None:
        """The pin change waits for the enforcement window: an activation is
        ordered entirely before (or entirely after) a policy change, never
        split across one."""
        engine = ExtensionPolicyEngine()
        service, store, _loader = make_service(engine=engine)
        scope = ExtensionScope("org-1", "ws-1")
        install_id = await drive_to_authorized(service, scope)

        events: list[str] = []
        activation_started = asyncio.Event()

        class SignallingLoader(ExtensionCodeLoader):
            async def load(self, record: Any, payload: bytes) -> LoadedExtension:
                events.append("activation-started")
                activation_started.set()
                await asyncio.sleep(0.01)
                events.append("activation-finished")
                return LoadedExtension(extension_id=record.extension_id, version=record.version)

        service._loader = SignallingLoader()

        async def do_install() -> None:
            active = await service.install(
                install_id, actor="operator-1", scope=scope, payload=PAYLOAD
            )
            assert active.state is ExtensionState.ACTIVE

        async def do_pin() -> None:
            await activation_started.wait()
            await asyncio.sleep(0.001)  # let the activation reach the window
            await engine.set_org_policy(
                OrgExtensionPolicy(
                    org_id="org-1",
                    pins={"acme.chart_tools": ExtensionPin(publisher_id="acme")},
                ),
                actor="org-admin",
            )
            events.append("pin-set")

        await asyncio.gather(do_install(), do_pin())
        # Linearized: the pin cannot land inside the activation window.
        assert events.index("activation-finished") < events.index("pin-set")
        # The activation was judged under the pin-free policy and won the
        # ordering race — consistent with the window discipline.
        assert await store.active_record(scope, "acme.chart_tools") is not None

    async def test_unwired_policy_preserves_previous_machine_behavior(self) -> None:
        service, store, loader = make_service(engine=None)
        scope = ExtensionScope("org-1", "ws-1")
        install_id = await drive_to_authorized(service, scope)
        active = await service.install(install_id, actor="operator-1", scope=scope, payload=PAYLOAD)
        assert active.state is ExtensionState.ACTIVE
        assert loader.calls == [("acme.chart_tools", "1.4.0")]
        assert await store.active_record(scope, "acme.chart_tools") is not None


# ---------------------------------------------------------------------------
# Tenant-scoped runtime state
# ---------------------------------------------------------------------------


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
class TestTenantScopedState:
    async def test_service_gates_state_handles_on_activation_in_scope(self) -> None:
        service, _store, _loader = make_service(engine=None)
        scope_a = ExtensionScope("org-1", "ws-a")
        with pytest.raises(UnknownInstall):
            await service.extension_state(scope_a, "acme.chart_tools")
        install_id = await drive_to_authorized(service, scope_a)
        await service.install(install_id, actor="operator-1", scope=scope_a, payload=PAYLOAD)
        assert await service.extension_state(scope_a, "acme.chart_tools") is not None

    async def test_foreign_workspace_cannot_bind_or_observe(self) -> None:
        """The acceptance pair: A activates + configures; B can neither bind
        the extension nor observe A's config/cache/checkpoint bytes."""
        service, _store, _loader = make_service(engine=None)
        scope_a = ExtensionScope("org-1", "ws-a")
        scope_b = ExtensionScope("org-1", "ws-b")
        install_id = await drive_to_authorized(service, scope_a)
        await service.install(install_id, actor="operator-1", scope=scope_a, payload=PAYLOAD)

        state_a = await service.extension_state(scope_a, "acme.chart_tools")
        state_a.set_config("api_key", "a-secret")
        state_a.cache_set("responses", b"a-bytes")
        state_a.checkpoint_save("progress", b"a-checkpoint")

        # B cannot even obtain a handle: no active record in B's scope, and
        # the refusal is the scope-blind UnknownInstall (no existence leak).
        with pytest.raises(UnknownInstall):
            await service.extension_state(scope_b, "acme.chart_tools")

        # Even a B handle minted directly (the host path) observes absence,
        # never A's values, for the very same extension and keys.
        shared = TenantScopedExtensionState()
        bind_a = shared.bind(scope_a, "acme.chart_tools")
        bind_b = shared.bind(scope_b, "acme.chart_tools")
        bind_a.set_config("api_key", "a-secret")
        bind_a.cache_set("responses", b"a-bytes")
        bind_a.checkpoint_save("progress", b"a-checkpoint")
        assert bind_b.get_config("api_key") is None
        assert bind_b.cache_get("responses") is None
        assert bind_b.checkpoint_load("progress") is None
        assert bind_b.checkpoint_names() == ()
        # And A still sees its own state after B's probes.
        assert bind_a.get_config("api_key") == "a-secret"
        assert bind_a.cache_get("responses") == b"a-bytes"
        assert bind_a.checkpoint_load("progress") == b"a-checkpoint"

    async def test_org_only_scope_is_its_own_tenant_never_a_wildcard(self) -> None:
        state = TenantScopedExtensionState()
        org_scope = ExtensionScope(org_id="org-1")
        ws_scope = ExtensionScope("org-1", "ws-a")
        org_handle = state.bind(org_scope, "acme.chart_tools")
        ws_handle = state.bind(ws_scope, "acme.chart_tools")
        org_handle.set_config("k", "org-value")
        assert ws_handle.get_config("k") is None
        assert tenant_scope_key(org_scope, "acme.chart_tools") == (
            "org-1",
            "",
            "acme.chart_tools",
        )
        assert tenant_scope_key(ws_scope, "acme.chart_tools") != tenant_scope_key(
            org_scope, "acme.chart_tools"
        )

    async def test_clear_scope_drops_only_one_tenant_key(self) -> None:
        state = TenantScopedExtensionState()
        scope_a = ExtensionScope("org-1", "ws-a")
        scope_b = ExtensionScope("org-1", "ws-b")
        handle_a = state.bind(scope_a, "acme.chart_tools")
        handle_b = state.bind(scope_b, "acme.chart_tools")
        handle_a.set_config("k", "v")
        handle_a.cache_set("c", b"1")
        handle_a.checkpoint_save("p", b"2")
        handle_b.set_config("k", "bv")
        assert state.clear_scope(scope_a, "acme.chart_tools") == 3
        assert handle_a.get_config("k") is None
        assert handle_a.cache_get("c") is None
        assert handle_a.checkpoint_load("p") is None
        assert handle_b.get_config("k") == "bv"

    async def test_blank_keys_are_refused(self) -> None:
        state = TenantScopedExtensionState()
        handle = state.bind(ExtensionScope("org-1", "ws-a"), "acme.chart_tools")
        with pytest.raises(ValueError, match="config key"):
            handle.set_config(" ", "v")
        with pytest.raises(ValueError, match="extension_id"):
            state.bind(ExtensionScope("org-1", "ws-a"), "  ")
        with pytest.raises(ValueError, match="checkpoint name"):
            handle.checkpoint_save("", b"d")

    async def test_deletes_report_what_this_tenant_held_and_nothing_else(self) -> None:
        """Config/cache deletes answer truthfully per tenant key: a miss on
        an unbound bucket, a hit only for the holder, and never a foreign
        tenant's entry."""
        state = TenantScopedExtensionState()
        handle_a = state.bind(ExtensionScope("org-1", "ws-a"), "acme.chart_tools")
        handle_b = state.bind(ExtensionScope("org-1", "ws-b"), "acme.chart_tools")
        # Misses with no bucket at all for this tenant key.
        assert handle_a.delete_config("k") is False
        assert handle_a.cache_delete("c") is False
        handle_a.set_config("k", "v")
        handle_a.cache_set("c", b"1")
        # Hits remove exactly this tenant's entries; a second delete misses.
        assert handle_a.delete_config("k") is True
        assert handle_a.delete_config("k") is False
        assert handle_a.cache_delete("c") is True
        assert handle_a.cache_delete("c") is False
        assert handle_a.get_config("k") is None
        assert handle_a.cache_get("c") is None
        # B's same-named keys were never reachable, so nothing changed there.
        handle_b.set_config("k", "b-v")
        handle_b.cache_set("c", b"b-1")
        assert handle_b.delete_config("k") is True
        assert handle_b.cache_delete("c") is True


# ---------------------------------------------------------------------------
# Cross-Workspace noninterference (property)
# ---------------------------------------------------------------------------

EXTENSIONS = ["acme.chart_tools", "acme.maps"]
KEYS = ["k1", "k2"]
WORKSPACE_A = ExtensionScope("org-1", "ws-a")
WORKSPACE_B = ExtensionScope("org-1", "ws-b")


@pytest.mark.contract("boundary")
@pytest.mark.scope("property")
class TestCrossWorkspaceNoninterference:
    @settings(max_examples=30, deadline=None)
    @given(
        enable_a=st.sets(st.sampled_from(EXTENSIONS), min_size=0),
        enable_b=st.sets(st.sampled_from(EXTENSIONS), min_size=0),
        ops=st.lists(
            st.tuples(
                st.sampled_from(["a_config", "b_config", "a_cache", "b_cache", "b_reads"]),
                st.sampled_from(EXTENSIONS),
                st.sampled_from(KEYS),
                st.integers(0, 5),
            ),
            max_size=24,
        ),
    )
    def test_mixed_operations_never_leak_across_workspaces(
        self,
        enable_a: set[str],
        enable_b: set[str],
        ops: list[tuple[str, str, str, int]],
    ) -> None:
        """Mixed extension operations across two Workspaces.

        Property 1 (invocation): the policy decision for a Workspace is a
        pure function of the org layer and *that* Workspace's enablement —
        B is denied exactly the extensions enabled only for A, whatever A
        does otherwise. Property 2 (state): after any interleaving of config
        and cache writes in both Workspaces, B's handles return only values
        B wrote under B's keys — never A's value for the same key.
        """
        engine = ExtensionPolicyEngine()
        asyncio.run(_wire_enablement(engine, enable_a, enable_b))
        runtime = TenantScopedExtensionState()
        # Model: what each workspace last wrote, per (extension, kind, key).
        writes: dict[tuple[str, str, str, str], object] = {}

        for op, extension, key, nonce in ops:
            handle_a = runtime.bind(WORKSPACE_A, extension)
            handle_b = runtime.bind(WORKSPACE_B, extension)

            if op == "a_config":
                handle_a.set_config(key, f"a-{nonce}")
                writes[("a", extension, "config", key)] = f"a-{nonce}"
                assert handle_a.get_config(key) == f"a-{nonce}"
            elif op == "b_config":
                handle_b.set_config(key, f"b-{nonce}")
                writes[("b", extension, "config", key)] = f"b-{nonce}"
                # B observes B's own last write — even for a key A wrote.
                assert handle_b.get_config(key) == f"b-{nonce}"
            elif op == "a_cache":
                handle_a.cache_set(key, f"a-{nonce}".encode())
                writes[("a", extension, "cache", key)] = f"a-{nonce}".encode()
                assert handle_a.cache_get(key) == f"a-{nonce}".encode()
            elif op == "b_cache":
                handle_b.cache_set(key, f"b-{nonce}".encode())
                writes[("b", extension, "cache", key)] = f"b-{nonce}".encode()
                assert handle_b.cache_get(key) == f"b-{nonce}".encode()
            elif op == "b_reads":
                # B reads the exact keys A may have written for the same
                # extension: the answer is B's own last value or absence —
                # never A's.
                assert handle_b.get_config(key) == writes.get(("b", extension, "config", key))
                assert handle_b.cache_get(key) == writes.get(("b", extension, "cache", key))

        # Invocation noninterference, re-checked after all mixed operations:
        # B's verdicts depend only on B's enablement (org layer is empty).
        for extension in EXTENSIONS:
            decision_b = engine.explain(
                candidate(extension_id=extension, permissions=()), WORKSPACE_B
            )
            assert decision_b.allowed == (extension in enable_b)
            decision_a = engine.explain(
                candidate(extension_id=extension, permissions=()), WORKSPACE_A
            )
            assert decision_a.allowed == (extension in enable_a)


async def _wire_enablement(
    engine: ExtensionPolicyEngine,
    enable_a: set[str],
    enable_b: set[str],
) -> None:
    # Both Workspaces get a policy (an empty enablement set means "enable
    # nothing"), so enablement is opt-in on both sides and the invocation
    # property is uniform: allowed == enabled.
    for workspace_id, enabled in (("ws-a", enable_a), ("ws-b", enable_b)):
        await engine.set_workspace_policy(
            WorkspaceExtensionPolicy(
                org_id="org-1", workspace_id=workspace_id, enabled_extensions=frozenset(enabled)
            ),
            actor="ws-admin",
        )


# ---------------------------------------------------------------------------
# Container wiring
# ---------------------------------------------------------------------------


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
class TestContainerPolicyWiring:
    def test_policy_engine_is_lazily_built_cached_and_wired_into_the_service(self) -> None:
        container = Container(
            config=None,
            router=None,
            classifier=None,
            quota_tracker=None,
            learning_store=None,
            learning_extractor=None,
            outcome_store=None,
            session_store=None,
            warden=None,
            gate=None,
            sentinel=None,
            context_builder=None,
            intent_registry=None,
        )
        assert container.extension_policy_engine is None
        engine = container.ensure_extension_policy_engine()
        assert engine is container.ensure_extension_policy_engine()
        service = container.ensure_extension_install_service()
        assert service._policy is engine
        assert isinstance(service._runtime, TenantScopedExtensionState)
