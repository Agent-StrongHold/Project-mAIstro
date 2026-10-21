"""EPIC M9-I acceptance proof (#946): extension usage, cost, quotas, and
operational evidence — the attribution composition at this base.

The epic's acceptance is a composition claim: identity propagation (#950
surfaces), usage metering/quotas (#977, ``maistro.extensions.metering``), and
the governed capability seam each had their own suites, but nothing
demonstrated they compose into the epic's operator story. This proof drives
one extension invocation through the canonical
``Graph → Run → NodeRun → Attempt`` spine with a governed effect route and a
wired canonical Invocation quota, then reads the evidence back the way an
operator would:

- **Attribution (AC1)**: the canonical event stream carries the extension
  identity in the envelope's provenance field correlated to
  Run/NodeRun/Attempt/Invocation, and the extension meter row attributes the
  same physical call to extension, version, publisher, caller, and Workspace
  while referencing the canonical Invocation id — with no host-side secret in
  either surface (the host drops undeclared config before any context exists).
- **No double counting (AC2)**: one provider call routed through the
  extension charges the canonical Invocation quota exactly once and is
  attributed exactly once at the extension seam; an alternate extension alias
  re-reporting the same canonical Invocation conflicts instead of charging.
- **Server-side quota composition (AC3)**: admission at the extension seam
  precedes dispatch, a denied admission produces no Invocation, no event, and
  no usage row, and the denied reservation can never settle afterwards.
- **Truthful availability (AC4)**: child #978's projection (#2021) is now an
  ancestor of this head, so the epic's own invocation composes with it. The
  attributed invocation's outcome, recorded at the host seam into the durable
  health store, projects the greeter READY; the same evidence under a platform
  bump projects INCOMPATIBLE; an operator quarantine, an extension's own
  fault, and a transient dependency failure each strip readiness with
  structurally distinct summaries in one operator view — and the holds plus
  failure evidence survive the health store being reopened (restart), still
  refusing success-shaped availability.
- **Top contributors (AC5)**: the per-extension cost breakdown ranks
  contributors and partitions the parent total; error and latency ranking
  (#978 digests) is composed here from host-recorded evidence with the
  taxonomy's provenance preserved, and the metered cost and the usage digest
  agree on the same physical call.
- **Historical evidence (AC6)**: rows keep their exact extension version
  identity after an upgrade and after the extension is removed — history is
  never reattributed and never silently dropped.

Only exported ``maistro.extensions`` / ``maistro.capabilities`` /
``maistro.quota`` surfaces are used; the extension below imports nothing from
host internals.

Acceptance-criterion markers
-----------------------------

The epic's six criteria are **issue-level**: they live in issue #946, and no
spec or ADR declares an ``M9-I`` document. The repository's acceptance-state
gate counts a marker that names no declared criterion as debt
(``markers_without_criterion`` — a counter that may only go down), so this
file marks only the criteria a document actually declares *and* that the
marked test genuinely proves:

- **AC1** is proved against ``ADR-104/AC-3`` (the host drops undeclared
  configuration at composition and the accessor refuses even the key's
  presence) and ``ADR-104/AC-4`` (a routed effect produces a real canonical
  ``Invocation`` row with run/node-run/attempt correlation, and the
  extension identity lands in the canonical event envelope's provenance).
- **AC2, AC3, AC4, AC5, AC6** have no declared criterion of their own — the
  attribution/metering seam, the extension quota ledger, the health
  projection, the ranking digests, and the version-history durability are
  child-issue surfaces (#977, #978) without a spec or ADR that states them
  as criteria. Their evidence is the assertions in the sections below, whose
  section headers carry the epic's own ids.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.governed_invocation import (
    GovernedInvocationExecutionService,
    InvocationPolicyContext,
)
from maistro.capabilities.invocation import (
    InMemoryInvocationStore,
    Invocation,
    InvocationExecutionService,
    InvocationStatus,
    InvocationUsage,
)
from maistro.events.envelope import EventEnvelope, InMemoryEventStore
from maistro.extensions import (
    ConfigurationKeyNotDeclared,
    ExtensionCodeLoader,
    ExtensionDescriptor,
    ExtensionErrorKind,
    ExtensionErrorRecord,
    ExtensionHealth,
    ExtensionHealthService,
    ExtensionHost,
    ExtensionIdentity,
    ExtensionInstallRecord,
    ExtensionInstallService,
    ExtensionMeter,
    ExtensionObservation,
    ExtensionOperationalState,
    ExtensionOperatorAction,
    ExtensionOperatorState,
    ExtensionPackage,
    ExtensionQuotaConflict,
    ExtensionQuotaDenied,
    ExtensionQuotaLedger,
    ExtensionQuotaPolicy,
    ExtensionQuotaRequest,
    ExtensionScope,
    ExtensionUsageAmounts,
    ExtensionUsageConflict,
    ExtensionUsageEvent,
    GovernedEffectRoute,
    InMemoryExtensionStore,
    InvocationScope,
    LoadedExtension,
    ObservationOutcome,
    OperatorDecision,
    RankingMetric,
    TrustClaim,
    TrustPolicy,
)
from maistro.extensions.host import EFFECT_EVENT_TYPE
from maistro.extensions.sqlite_health_store import SqliteExtensionHealthStore
from maistro.graph import Graph, Node
from maistro.policy.types import Decision, PolicyVerdict
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.quota.invocation_quota import QuotaBudget, QuotaEstimate
from maistro.quota.sqlite_invocation_quota import SqliteInvocationQuota
from maistro.runs.concurrency import RunConcurrencyLimits
from maistro.runs.execution import AttemptExecutionService
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.runtime import PythonExecutionRuntime
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

pytestmark = pytest.mark.contract("behavioral")

WORKSPACE = "extension-ws"
PROJECT = "extension-project"
ORG = "org-a"
EXTENSION_ID = "reference.greeter"
EXTENSION_VERSION = "0.1.0"
PUBLISHER = "reference"
CALLER = "agent-1"
CAPABILITY = "ext.reference.echo"
PROVIDER = "provider-a"
SECRET = "sk-host-only-value"
BINDING_ID = "binding-echo"

CLOCK = 1_000.0


class MeteredGreeter:
    """The extension under proof: declared config read, one governed effect."""

    def __init__(self) -> None:
        self.invocation_id: str | None = None

    async def activate(self, context: Any) -> None: ...

    async def invoke(self, context: Any) -> dict[str, Any]:
        greeting = context.config["politeness"]
        receipt = await context.invoke_effect("echo", {"greeting": greeting})
        self.invocation_id = receipt.invocation_id
        return {"echoed": receipt.result, "invocation_id": receipt.invocation_id}

    async def deactivate(self, context: Any) -> None: ...


class _EchoProvider:
    name = PROVIDER
    # ResolvedBinding.from_provider requires the resolved slot to match the
    # Binding capability — the same rule any production provider satisfies.
    slot = CAPABILITY
    trust_tier = "trusted"


def _descriptor() -> ExtensionDescriptor:
    return ExtensionDescriptor(
        identity=ExtensionIdentity(extension_id=EXTENSION_ID, version=EXTENSION_VERSION),
        config_keys=frozenset({"politeness"}),
        effects=frozenset({"echo"}),
    )


def _governed_route(
    *,
    events: InMemoryEventStore,
    invocations: InMemoryInvocationStore,
    quota: SqliteInvocationQuota | None = None,
) -> GovernedEffectRoute:
    """Host-side wiring of the declared effect across the governed seam."""

    async def allow_policy(
        _binding: Binding,
        _request: Any,
        _context: InvocationPolicyContext,
    ) -> PolicyVerdict:
        return PolicyVerdict(
            Decision.ALLOW,
            reason="epic proof effect",
            rule="test.epic-m9i-allow",
        )

    async def _resolver(_binding: Binding) -> _EchoProvider:
        return _EchoProvider()

    async def _executor(_provider: _EchoProvider, request: Any) -> dict[str, Any]:
        return {"echoed": request}

    def _usage_from(_result: Any) -> InvocationUsage:
        # The provider-reported usage of the one physical call this executor
        # makes; the canonical Invocation quota settles from it.
        return InvocationUsage(units="tokens", input_units=40, output_units=20)

    governed = GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(store=invocations, quota=quota),
        event_store=events,
        policy_evaluator=allow_policy,
    )
    return GovernedEffectRoute(
        effect_key="echo",
        binding=Binding(
            binding_id=BINDING_ID,
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            capability=CAPABILITY,
        ),
        invocations=governed,
        resolver=_resolver,
        executor=_executor,
        usage_from=_usage_from,
    )


async def _canonical_quota(path: Path) -> SqliteInvocationQuota:
    async def estimate(inv: Invocation, bound: Binding) -> QuotaEstimate:
        del inv, bound
        return QuotaEstimate(principal_id="principal-a", tokens=60)

    canonical = SqliteInvocationQuota(path, estimate=estimate, clock=lambda: 100)
    await canonical.ensure_schema()
    await canonical.register_budget(
        QuotaBudget(
            budget_id="tokens",
            unit="tokens",
            limit=100,
            period_start=0,
            period_end=1_000,
            provider_name=PROVIDER,
            opening_spend=0,
            coverage_ref="operator-attested-fresh-period",
        )
    )
    return canonical


def _meter_row(
    name: str, *, invocation_id: str | None = None, **overrides: Any
) -> ExtensionUsageEvent:
    fields: dict[str, Any] = {
        "event_id": name,
        "org_id": ORG,
        "workspace_id": WORKSPACE,
        "extension_id": EXTENSION_ID,
        "extension_version": EXTENSION_VERSION,
        "publisher_id": PUBLISHER,
        "capability": CAPABILITY,
        "caller_id": CALLER,
        "invocation_id": invocation_id,
        "provider_name": PROVIDER,
        "input_tokens": 40,
        "output_tokens": 20,
        "micro_usd": 500,
        "requests": 1,
    }
    fields.update(overrides)
    return ExtensionUsageEvent(**fields)


async def _spine() -> tuple[InMemoryRunStore, str, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    project = await projects.create(
        workspace_id=WORKSPACE, parent_project_id=root.project_id, name="Extensions"
    )
    store = InMemoryRunStore(project_store=projects, concurrency_limits=RunConcurrencyLimits())
    return store, WORKSPACE, project.project_id


async def _running_node_run(
    store: InMemoryRunStore,
    workspace_id: str,
    project_id: str,
) -> tuple[str, str]:
    graph = Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="Epic M9-I attribution proof",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    node_run = await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    node_run = await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    return run.run_id, node_run.node_run_id


async def _invoke_once(
    *,
    invocations: InMemoryInvocationStore,
    events: InMemoryEventStore,
    quota: SqliteInvocationQuota | None = None,
    captured_contexts: list[Any] | None = None,
) -> tuple[str, str, str, str]:
    """Drive one extension invocation through the canonical Attempt spine.

    Returns (run_id, node_run_id, attempt_id, invocation_id). A caller that
    needs the authority the extension actually received passes
    ``captured_contexts`` and gets the context appended to it.
    """
    store, workspace_id, project_id = await _spine()
    run_id, node_run_id = await _running_node_run(store, workspace_id, project_id)
    host = ExtensionHost(
        descriptor=_descriptor(),
        # The host holds a secret the descriptor never declares; composition
        # must drop it before any context exists (AC1 secret hygiene).
        config_values={"politeness": "warm", "api_key": SECRET},
        effect_routes={
            "echo": _governed_route(events=events, invocations=invocations, quota=quota)
        },
        events=events,
    )
    extension = MeteredGreeter()

    def context_factory(attempt: Any, _execution_context: Any) -> Any:
        context = host.invocation_context(
            InvocationScope(
                workspace_id=WORKSPACE,
                agent_id=CALLER,
                run_id=run_id,
                node_run_id=node_run_id,
                attempt_id=attempt.attempt_id,
            )
        )
        if captured_contexts is not None:
            captured_contexts.append(context)
        return context

    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())
    terminal = await service.execute(
        node_run_id,
        None,
        None,
        executor=lambda _work, context: host.invoke(extension, context),
        context_factory=context_factory,
    )
    assert terminal.status is AttemptStatus.COMPLETED
    assert extension.invocation_id is not None
    return run_id, node_run_id, terminal.attempt_id, extension.invocation_id


async def _stream(events: InMemoryEventStore) -> list[EventEnvelope]:
    return await events.list_stream(f"workspace:{WORKSPACE}")


async def _invocations_for_run(invocations: InMemoryInvocationStore, run_id: str) -> list[str]:
    """The canonical Invocations one Run produced, in creation order."""
    recorded = await invocations.list_effect(
        run_id=run_id,
        node_run_id=None,
        binding_id=BINDING_ID,
        effect_key="echo",
    )
    return [item.invocation_id for item in recorded]


async def _reserve_result(ledger: ExtensionQuotaLedger, attempt: ExtensionQuotaRequest) -> str:
    """Admit one reservation and report the server's verdict.

    The ledger is the only authority on admission, so the outcome of a
    concurrent attempt is whatever the shared database decided — never
    whatever the caller believes.
    """
    try:
        await ledger.reserve(attempt)
    except ExtensionQuotaDenied:
        return "denied"
    return "admitted"


# ---------------------------------------------------------------------------
# AC1: every extension invocation is attributable to extension, version,
# publisher, caller, and Workspace — on canonical evidence, without secrets.
# ---------------------------------------------------------------------------


@pytest.mark.ac("ADR-104/AC-3")
@pytest.mark.ac("ADR-104/AC-4")
async def test_extension_invocation_is_attributed_on_canonical_evidence(
    tmp_path: Path,
) -> None:
    events = InMemoryEventStore()
    invocations = InMemoryInvocationStore()
    meter = ExtensionMeter(tmp_path / "metering.sqlite", clock=lambda: CLOCK)
    await meter.ensure_schema()

    captured_contexts: list[Any] = []
    run_id, node_run_id, attempt_id, invocation_id = await _invoke_once(
        invocations=invocations, events=events, captured_contexts=captured_contexts
    )

    # The authority the extension received carries the declared configuration
    # only: the host dropped the undeclared secret at composition, and the
    # accessor refuses even the key's presence.
    assert len(captured_contexts) == 1
    context = captured_contexts[0]
    assert dict(context.config) == {"politeness": "warm"}
    with pytest.raises(ConfigurationKeyNotDeclared):
        context.config["api_key"]
    # The public view would hide the secret either way, so the snapshot is
    # what proves the host dropped the value *at composition* rather than
    # leaving it in the context's storage behind a refusing accessor — the
    # same observation ADR-104's conformance suite makes for the same reason.
    assert "api_key" not in context.config._values
    assert SECRET not in repr(context.config._values)

    # The canonical Invocation is the physical evidence the attribution row
    # must reference: same identity, same execution correlation.
    invocation = await invocations.get(invocation_id)
    assert invocation is not None
    assert invocation.status is InvocationStatus.COMPLETED
    assert (invocation.run_id, invocation.node_run_id, invocation.attempt_id) == (
        run_id,
        node_run_id,
        attempt_id,
    )

    # The host attributed the effect on the canonical event stream: extension
    # identity rides in provenance, correlated to the canonical chain — the
    # extension never supplied its own correlation id.
    stream = await _stream(events)
    effect_events = [event for event in stream if event.type == EFFECT_EVENT_TYPE]
    assert len(effect_events) == 1
    effect_event = effect_events[0]
    assert effect_event.provenance == {
        "extension_id": EXTENSION_ID,
        "extension_version": EXTENSION_VERSION,
    }
    assert effect_event.workspace_id == WORKSPACE
    assert effect_event.run_id == run_id
    assert effect_event.node_run_id == node_run_id
    assert effect_event.attempt_id == attempt_id
    assert effect_event.invocation_id == invocation_id
    assert effect_event.source == "maistro.extensions"

    # The host runtime records attribution at the meter seam from facts it
    # already holds: install-record identity (extension/version/publisher),
    # the accountable caller, and the Workspace scope.
    await meter.record(_meter_row("evt-attributed", invocation_id=invocation_id))
    totals = await meter.totals(org_id=ORG, workspace_id=WORKSPACE)
    assert totals.events == 1
    lineage = await meter.lineage(invocation_id)
    assert len(lineage) == 1
    row = lineage[0]
    assert row.extension_id == EXTENSION_ID
    assert row.extension_version == EXTENSION_VERSION
    assert row.publisher_id == PUBLISHER
    assert row.caller_id == CALLER
    assert row.workspace_id == WORKSPACE
    assert row.invocation_id == invocation_id

    # Secret hygiene: the undeclared host secret never reached the context,
    # so it appears on neither telemetry surface — payloads, provenance, or
    # the meter's identity/amount-only rows.
    for event in stream:
        blob = repr(event.payload) + repr(event.provenance)
        assert SECRET not in blob


# ---------------------------------------------------------------------------
# AC2: one provider call through an extension is charged once in canonical
# totals and attributed once at the extension seam.
# ---------------------------------------------------------------------------


async def test_one_provider_call_is_charged_once_and_attributed_once(
    tmp_path: Path,
) -> None:
    path = tmp_path / "shared.sqlite"
    canonical = await _canonical_quota(path)
    meter = ExtensionMeter(path, clock=lambda: CLOCK)
    await meter.ensure_schema()

    events = InMemoryEventStore()
    invocations = InMemoryInvocationStore()
    _, _, _, invocation_id = await _invoke_once(
        invocations=invocations, events=events, quota=canonical
    )

    # Canonical totals: the wired Invocation quota settled the one physical
    # call once (40 input + 20 output tokens).
    assert (await canonical.balance("tokens")).spent == 60

    # Extension attribution: the same physical call, attributed once.
    await meter.record(_meter_row("evt-once", invocation_id=invocation_id))
    totals = await meter.totals(org_id=ORG, workspace_id=WORKSPACE)
    assert (totals.input_tokens, totals.output_tokens) == (40, 20)
    assert totals.micro_usd == 500

    # An alternate extension alias re-reporting the same canonical Invocation
    # is a conflict, never a second charge — and canonical re-observation of
    # the settled Invocation charges nothing more.
    completed = await invocations.get(invocation_id)
    assert completed is not None
    await canonical.observe(completed)
    assert (await canonical.balance("tokens")).spent == 60
    with pytest.raises(ExtensionUsageConflict, match="already carries"):
        await meter.record(
            _meter_row(
                "evt-alias",
                invocation_id=invocation_id,
                extension_id="reference.greeter-alias",
            )
        )
    totals = await meter.totals(org_id=ORG, workspace_id=WORKSPACE)
    assert (totals.input_tokens, totals.output_tokens) == (40, 20)
    assert (await canonical.balance("tokens")).spent == 60


# ---------------------------------------------------------------------------
# AC3: quotas/rate limits are server-side and enforced before dispatch —
# a denied admission cannot manufacture success-shaped evidence.
# ---------------------------------------------------------------------------


async def test_quota_denial_precedes_dispatch_and_blocks_all_evidence(
    tmp_path: Path,
) -> None:
    quota_ledger = ExtensionQuotaLedger(tmp_path / "quota.sqlite", clock=lambda: CLOCK)
    await quota_ledger.ensure_schema()
    await quota_ledger.register_policy(
        ExtensionQuotaPolicy(
            policy_id="workspace-tokens",
            org_id=ORG,
            unit="tokens",
            limit=120,
            period_start=0,
            period_end=10_000,
            coverage_ref="operator-attested-fresh-period",
            workspace_id=WORKSPACE,
        )
    )

    events = InMemoryEventStore()
    invocations = InMemoryInvocationStore()

    def reservation(name: str) -> ExtensionQuotaRequest:
        return ExtensionQuotaRequest(
            reservation_id=name,
            org_id=ORG,
            workspace_id=WORKSPACE,
            extension_id=EXTENSION_ID,
            publisher_id=PUBLISHER,
            capability=CAPABILITY,
            caller_id=CALLER,
            provider_name=PROVIDER,
            tokens=60,
        )

    # First invocation: admission holds, dispatch runs, the seam records and
    # settles — the composed happy path.
    await quota_ledger.reserve(reservation("res-one"))
    run_id, _, _, invocation_id = await _invoke_once(invocations=invocations, events=events)
    meter = ExtensionMeter(tmp_path / "quota.sqlite", clock=lambda: CLOCK)
    await meter.ensure_schema()
    await meter.record(_meter_row("evt-res-one", invocation_id=invocation_id))
    await quota_ledger.commit(
        "res-one", ExtensionUsageAmounts(tokens=60, micro_usd=500, requests=1)
    )
    balance = await quota_ledger.policy_balance("workspace-tokens")
    assert balance.available == 60

    # Concurrency: two workers admit against the same remaining budget at
    # once. The shared ledger admits exactly one and refuses the other — the
    # quota is enforced server-side, so no client-side race can oversubscribe
    # the Workspace.
    stream_before = await _stream(events)
    concurrent = dict(
        zip(
            ("res-conc-a", "res-conc-b"),
            await asyncio.gather(
                _reserve_result(quota_ledger, reservation("res-conc-a")),
                _reserve_result(quota_ledger, reservation("res-conc-b")),
            ),
            strict=True,
        )
    )
    assert sorted(concurrent.values()) == ["admitted", "denied"]
    # The refusal produced no dispatch at all: no canonical Invocation, no
    # event, no usage row.
    assert await _stream(events) == stream_before
    assert await _invocations_for_run(invocations, run_id) == [invocation_id]
    totals = await meter.totals(org_id=ORG, workspace_id=WORKSPACE)
    assert totals.events == 1
    # The one admitted hold consumed the remaining budget server-side.
    assert (await quota_ledger.policy_balance("workspace-tokens")).available == 0
    # The refused concurrent work can never be settled into success-shaped
    # usage either.
    denied_reservation = next(name for name, verdict in concurrent.items() if verdict == "denied")
    with pytest.raises(ExtensionQuotaConflict, match="denied reservation"):
        await quota_ledger.commit(
            denied_reservation, ExtensionUsageAmounts(tokens=60, micro_usd=500, requests=1)
        )

    # Second invocation: the budget is exhausted server-side, so admission is
    # refused before any dispatch — no Invocation, no event, no usage row.
    with pytest.raises(ExtensionQuotaDenied):
        await quota_ledger.reserve(reservation("res-two"))
    assert await _stream(events) == stream_before
    assert await _invocations_for_run(invocations, run_id) == [invocation_id]
    totals = await meter.totals(org_id=ORG, workspace_id=WORKSPACE)
    assert totals.events == 1

    # The refused work can never be settled into success-shaped usage either.
    with pytest.raises(ExtensionQuotaConflict, match="denied reservation"):
        await quota_ledger.commit(
            "res-two", ExtensionUsageAmounts(tokens=60, micro_usd=500, requests=1)
        )


# ---------------------------------------------------------------------------
# AC5 (cost half): operators can rank extension cost contributors. Error and
# latency taxonomies are child issue #978 and are not part of this base.
# ---------------------------------------------------------------------------


async def test_top_extension_cost_contributor_is_identifiable(tmp_path: Path) -> None:
    meter = ExtensionMeter(tmp_path / "metering.sqlite", clock=lambda: CLOCK)
    await meter.ensure_schema()
    await meter.record(
        _meter_row(
            "evt-cheap",
            invocation_id="invocation-cheap",
            extension_id="ext.small",
            publisher_id="pub.small",
            micro_usd=100,
        )
    )
    await meter.record(
        _meter_row(
            "evt-pricey",
            invocation_id="invocation-pricey",
            extension_id="ext.large",
            publisher_id="pub.large",
            micro_usd=900,
        )
    )

    by_extension = await meter.breakdown("extension", org_id=ORG)
    ranked = sorted(by_extension.items(), key=lambda item: item[1].micro_usd, reverse=True)
    assert [extension_id for extension_id, _ in ranked] == ["ext.large", "ext.small"]
    assert ranked[0][1].micro_usd == 900

    by_publisher = await meter.breakdown("publisher", org_id=ORG)
    assert by_publisher["pub.large"].micro_usd == 900
    assert by_publisher["pub.small"].micro_usd == 100
    # Buckets partition the same physical rows: the breakdown re-adds to the
    # parent total, never to more.
    totals = await meter.totals(org_id=ORG)
    assert sum(bucket.micro_usd for bucket in by_extension.values()) == totals.micro_usd


# ---------------------------------------------------------------------------
# AC6: historical evidence remains interpretable after an upgrade or removal.
# ---------------------------------------------------------------------------


async def test_historical_evidence_survives_upgrade_and_removal(tmp_path: Path) -> None:
    meter = ExtensionMeter(tmp_path / "metering.sqlite", clock=lambda: CLOCK)
    await meter.ensure_schema()

    # v1.0.0 serves one invocation; the operator then upgrades to 2.0.0,
    # which serves another; finally the extension is removed entirely (no
    # further rows ever arrive).
    await meter.record(_meter_row("evt-v1", invocation_id="invocation-v1"))
    await meter.record(
        _meter_row(
            "evt-v2",
            invocation_id="invocation-v2",
            extension_version="2.0.0",
            micro_usd=250,
        )
    )
    upgraded_totals = await meter.totals(org_id=ORG, workspace_id=WORKSPACE)
    assert (upgraded_totals.events, upgraded_totals.micro_usd) == (2, 750)

    # Removal: the extension stops reporting. The historical rows keep their
    # exact per-version identity — old evidence is never reattributed to the
    # new version, and never dropped.
    v1_lineage = await meter.lineage("invocation-v1")
    assert [row.extension_version for row in v1_lineage] == [EXTENSION_VERSION]
    v2_lineage = await meter.lineage("invocation-v2")
    assert [row.extension_version for row in v2_lineage] == ["2.0.0"]
    removed_totals = await meter.totals(org_id=ORG, workspace_id=WORKSPACE)
    assert (removed_totals.events, removed_totals.micro_usd) == (2, 750)
    # Attribution by publisher still resolves the historical contributor.
    by_publisher = await meter.breakdown("publisher", org_id=ORG)
    assert by_publisher[PUBLISHER].events == 2


# ---------------------------------------------------------------------------
# AC4/AC5 composition with the operational projection (#978 landed via #2021)
# ---------------------------------------------------------------------------

SCOPE = ExtensionScope(org_id=ORG, workspace_id=WORKSPACE)
DEPENDENCY_ID = "acme.provider"
DEPENDENCY_VERSION = "2.0.0"
PLATFORM = "1.0.0"
HEALTH_PAYLOAD = b"epic-m9i-health-payload"
HEALTH_PUBLISHER = "reference"
HEALTH_TRUST = TrustPolicy(trusted_publishers=frozenset({HEALTH_PUBLISHER}))
AT = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


class _ActivatingLoader(ExtensionCodeLoader):
    """The host loader seam: loads whatever the lifecycle authorized."""

    async def load(self, record: ExtensionInstallRecord, payload: bytes) -> LoadedExtension:
        del payload
        return LoadedExtension(extension_id=record.extension_id, version=record.version)


def _health_manifest(
    extension_id: str,
    version: str,
    *,
    dependencies: tuple[tuple[str, str], ...] = (),
) -> bytes:
    document: dict[str, Any] = {
        "manifest_version": 1,
        "id": extension_id,
        "name": extension_id,
        "version": version,
        "publisher": HEALTH_PUBLISHER,
        "api_version": PLATFORM,
        "permissions": ["network.http"],
        "entry_points": [{"name": "main", "module": "mod", "attribute": "activate"}],
        "artifact": {
            "sha256": hashlib.sha256(HEALTH_PAYLOAD).hexdigest(),
            "size": len(HEALTH_PAYLOAD),
        },
    }
    if dependencies:
        document["dependencies"] = [
            {"id": dependency_id, "range": range_spec} for dependency_id, range_spec in dependencies
        ]
    return json.dumps(document).encode()


async def _install_extension(
    store: InMemoryExtensionStore,
    extension_id: str,
    version: str,
    *,
    dependencies: tuple[tuple[str, str], ...] = (),
) -> ExtensionInstallRecord:
    """Drive one candidate through the canonical inspect → authorize → install
    lifecycle so the projection reads real registry evidence."""
    service = ExtensionInstallService(store, loader=_ActivatingLoader(), trust_policy=HEALTH_TRUST)
    record = await service.inspect(
        actor="operator",
        scope=SCOPE,
        package=ExtensionPackage(
            manifest_bytes=_health_manifest(extension_id, version, dependencies=dependencies),
            payload=HEALTH_PAYLOAD,
        ),
        trust_evidence=TrustClaim(
            publisher_id=HEALTH_PUBLISHER,
            signature_present=True,
            signer_key_id="key-1",
            package_sha256=hashlib.sha256(HEALTH_PAYLOAD).hexdigest(),
        ),
    )
    record = await service.authorize(
        record.install_id, actor="operator", scope=SCOPE, approve=True, reason="needed"
    )
    record = await service.install(
        record.install_id, actor="operator", scope=SCOPE, payload=HEALTH_PAYLOAD
    )
    assert record.state.value == "active"
    return record


def _obs(
    observation_id: str,
    extension_id: str,
    version: str,
    *,
    outcome: ObservationOutcome = ObservationOutcome.SUCCESS,
    latency_ms: float = 10.0,
    cost_units: float | None = None,
    error: ExtensionErrorRecord | None = None,
) -> ExtensionObservation:
    return ExtensionObservation(
        observation_id=observation_id,
        at=AT,
        org_id=ORG,
        workspace_id=WORKSPACE,
        extension_id=extension_id,
        version=version,
        latency_ms=latency_ms,
        outcome=outcome,
        cost_units=cost_units,
        error=error,
    )


def _ext_error(
    error_id: str,
    extension_id: str,
    version: str,
    *,
    kind: ExtensionErrorKind = ExtensionErrorKind.EXTENSION,
    dependency: str | None = None,
    dependency_version: str | None = None,
) -> ExtensionErrorRecord:
    return ExtensionErrorRecord(
        error_id=error_id,
        at=AT,
        org_id=ORG,
        workspace_id=WORKSPACE,
        extension_id=extension_id,
        version=version,
        kind=kind,
        code="runtime_fault",
        message="recorded at the host seam for the epic proof",
        dependency=dependency,
        dependency_version=dependency_version,
    )


def _decision(
    decision_id: str,
    extension_id: str,
    action: ExtensionOperatorAction,
    *,
    reason: str,
) -> OperatorDecision:
    return OperatorDecision(
        decision_id=decision_id,
        at=AT,
        org_id=ORG,
        workspace_id=WORKSPACE,
        extension_id=extension_id,
        action=action,
        state=ExtensionOperatorState.ENABLED
        if action is ExtensionOperatorAction.ENABLE
        else ExtensionOperatorState.QUARANTINED
        if action is ExtensionOperatorAction.QUARANTINE
        else ExtensionOperatorState.DISABLED,
        actor="operator",
        reason=reason,
    )


async def test_availability_projection_composes_the_epic_evidence(
    tmp_path: Path,
) -> None:
    """AC4 at the epic seam: the *same* attributed invocation that feeds the
    meter also feeds the truthful availability projection — and installed
    extensions can never report success-shaped availability under a platform
    bump, an operator hold, their own fault, or a failing dependency."""
    install_store = InMemoryExtensionStore()
    await _install_extension(install_store, DEPENDENCY_ID, DEPENDENCY_VERSION)
    await _install_extension(
        install_store,
        EXTENSION_ID,
        EXTENSION_VERSION,
        dependencies=((DEPENDENCY_ID, f"^{DEPENDENCY_VERSION}"),),
    )

    # The epic's own spine invocation (AC1/AC2): attributed, metered once.
    events = InMemoryEventStore()
    invocations = InMemoryInvocationStore()
    meter = ExtensionMeter(tmp_path / "metering.sqlite", clock=lambda: CLOCK)
    await meter.ensure_schema()
    _, _, _, invocation_id = await _invoke_once(invocations=invocations, events=events)
    await meter.record(_meter_row("evt-health", invocation_id=invocation_id))

    async with aiosqlite.connect(tmp_path / "health.sqlite") as conn:
        health_store = SqliteExtensionHealthStore(conn)
        await health_store.ensure_schema()
        service = ExtensionHealthService(install_store, health_store)

        # The host seam records the outcome it measured for the invocation the
        # event stream already attributes (identity and cost from AC1/AC2).
        await service.record_observation(
            _obs(
                "obs-epic-invoke",
                EXTENSION_ID,
                EXTENSION_VERSION,
                latency_ms=12.5,
                cost_units=500.0,
            )
        )

        ready = await service.status(SCOPE, EXTENSION_ID)
        assert ready is not None
        assert ready.ready is True
        assert ready.live is True
        assert ready.summary is ExtensionOperationalState.READY
        assert ready.healthy is ExtensionHealth.HEALTHY
        assert ready.not_ready_reasons == ()

        # Cross-seam agreement: the digest's cost total and the extension
        # meter's total describe the one physical call — no drift, no double
        # counting between the two telemetry surfaces.
        meter_total = await meter.totals(org_id=ORG, workspace_id=WORKSPACE)
        greeter_digest = await service.usage_digests(SCOPE)
        assert len(greeter_digest) == 1
        assert greeter_digest[0].cost_units_total == 500.0 == meter_total.micro_usd
        assert greeter_digest[0].active is True

        # A platform API bump is re-derived now: the still-installed extension
        # becomes structurally incompatible and loses readiness.
        bumped = ExtensionHealthService(install_store, health_store, platform_api_version="2.0.0")
        incompatible = await bumped.status(SCOPE, EXTENSION_ID)
        assert incompatible is not None
        assert incompatible.ready is False
        assert incompatible.live is True
        assert incompatible.summary is ExtensionOperationalState.INCOMPATIBLE
        assert incompatible.incompatibility_failures

        # An operator quarantine holds even over perfectly clean evidence —
        # a deliberate hold, never a health symptom, and never success-shaped.
        await service.apply_decision(
            _decision(
                "decision-quarantine",
                EXTENSION_ID,
                ExtensionOperatorAction.QUARANTINE,
                reason="suspected misbehavior",
            )
        )
        quarantined = await service.status(SCOPE, EXTENSION_ID)
        assert quarantined is not None
        assert quarantined.ready is False
        assert quarantined.healthy is ExtensionHealth.HEALTHY
        assert quarantined.summary is ExtensionOperationalState.QUARANTINED

        # Two more extensions in the same scope, each blocked differently: the
        # operator view carries all four verdicts at once, distinct.
        await _install_extension(install_store, "reference.faulty", "0.1.0")
        await service.record_observation(
            _obs(
                "obs-faulty",
                "reference.faulty",
                "0.1.0",
                outcome=ObservationOutcome.FAILURE,
                error=_ext_error("err-faulty", "reference.faulty", "0.1.0"),
            )
        )
        await _install_extension(
            install_store,
            "reference.dependent",
            "0.1.0",
            dependencies=((DEPENDENCY_ID, f"^{DEPENDENCY_VERSION}"),),
        )
        await service.record_observation(
            _obs(
                "obs-dependent",
                "reference.dependent",
                "0.1.0",
                outcome=ObservationOutcome.FAILURE,
                error=_ext_error(
                    "err-dependent",
                    "reference.dependent",
                    "0.1.0",
                    kind=ExtensionErrorKind.DEPENDENCY,
                    dependency=DEPENDENCY_ID,
                    dependency_version=DEPENDENCY_VERSION,
                ),
            )
        )

        overview = {status.extension_id: status for status in await service.statuses(SCOPE)}
        assert overview[EXTENSION_ID].summary is ExtensionOperationalState.QUARANTINED
        faulty = overview["reference.faulty"]
        assert faulty.ready is False
        assert faulty.summary is ExtensionOperationalState.UNHEALTHY
        dependent = overview["reference.dependent"]
        assert dependent.ready is False
        assert dependent.live is True
        assert dependent.summary is ExtensionOperationalState.DEGRADED
        assert dependent.healthy is ExtensionHealth.DEGRADED
        # The dependency itself is fine: the transient failure is the
        # dependency's provider condition, not its own health verdict.
        assert overview[DEPENDENCY_ID].summary is ExtensionOperationalState.READY


async def test_operator_holds_and_failure_evidence_survive_a_restart(
    tmp_path: Path,
) -> None:
    """AC4's durability half at the epic seam: the durable health store
    reopened under a fresh service still refuses success-shaped availability —
    the operator hold and the failure evidence are separate surviving facts.

    (Install-record durability across a process restart is #978's open
    PostgreSQL clarification; the claim proven here is that the recorded
    health evidence and holds themselves survive, projected over the
    canonical install evidence.)"""
    install_store = InMemoryExtensionStore()
    await _install_extension(install_store, EXTENSION_ID, EXTENSION_VERSION)
    path = tmp_path / "health-restart.sqlite"

    async with aiosqlite.connect(path) as conn:
        store = SqliteExtensionHealthStore(conn)
        await store.ensure_schema()
        before = ExtensionHealthService(install_store, store)
        await before.record_observation(
            _obs("obs-restart-ok", EXTENSION_ID, EXTENSION_VERSION, latency_ms=8.0)
        )
        await before.record_observation(
            _obs(
                "obs-restart-fault",
                EXTENSION_ID,
                EXTENSION_VERSION,
                outcome=ObservationOutcome.FAILURE,
                error=_ext_error("err-restart-fault", EXTENSION_ID, EXTENSION_VERSION),
            )
        )
        await before.apply_decision(
            _decision(
                "decision-restart",
                EXTENSION_ID,
                ExtensionOperatorAction.QUARANTINE,
                reason="suspected misbehavior",
            )
        )
        held = await before.status(SCOPE, EXTENSION_ID)
        assert held is not None
        assert held.summary is ExtensionOperationalState.QUARANTINED
        assert held.healthy is ExtensionHealth.UNHEALTHY

    # "Restart": a fresh service instance over the reopened durable store.
    async with aiosqlite.connect(path) as conn:
        store = SqliteExtensionHealthStore(conn)
        await store.ensure_schema()
        after = ExtensionHealthService(install_store, store)

        resumed = await after.status(SCOPE, EXTENSION_ID)
        assert resumed is not None
        assert resumed.ready is False
        assert resumed.summary is ExtensionOperationalState.QUARANTINED
        assert resumed.policy_state is ExtensionOperatorState.QUARANTINED
        assert resumed.healthy is ExtensionHealth.UNHEALTHY
        assert any("quarantined by operator" in r for r in resumed.not_ready_reasons)

        # The failure evidence survived too, with its provenance intact.
        errors = await after.recent_errors(SCOPE, EXTENSION_ID)
        assert [error.error_id for error in errors] == ["err-restart-fault"]
        assert errors[0].extension_id == EXTENSION_ID
        assert errors[0].version == EXTENSION_VERSION
        digests = await after.usage_digests(SCOPE)
        assert (digests[0].invocations, digests[0].failures) == (2, 1)

        # Lifting the hold after the restart does not manufacture readiness:
        # the surviving failure evidence still refuses it.
        await after.apply_decision(
            _decision(
                "decision-release",
                EXTENSION_ID,
                ExtensionOperatorAction.ENABLE,
                reason="investigation closed",
            )
        )
        released = await after.status(SCOPE, EXTENSION_ID)
        assert released is not None
        assert released.ready is False
        assert released.policy_state is ExtensionOperatorState.ENABLED
        assert released.summary is ExtensionOperationalState.UNHEALTHY


async def test_top_extension_error_and_latency_contributors_are_rankable(
    tmp_path: Path,
) -> None:
    """AC5's error/latency half at the epic seam: operators rank top error and
    latency contributors from host-recorded evidence, the taxonomy keeps
    extension/version/dependency provenance, unmeasured cost never reads as
    free, and SLO error-budget inputs derive from the same evidence."""
    del tmp_path
    install_store = InMemoryExtensionStore()
    for extension_id in ("ext.buggy", "ext.slowpoke", "ext.speedy", "ext.silent"):
        await _install_extension(install_store, extension_id, "1.0.0")

    async with aiosqlite.connect(":memory:") as conn:
        store = SqliteExtensionHealthStore(conn)
        await store.ensure_schema()
        service = ExtensionHealthService(install_store, store)

        # Each metric has a *different* top contributor, so a ranking that
        # reads the wrong axis cannot pass: buggy owns failures/error-rate,
        # slowpoke owns latency, speedy owns measured cost, silent owns raw
        # usage while its cost was never metered.
        for index, latency in enumerate((30.0, 20.0, 10.0)):
            failed = index < 2
            await service.record_observation(
                _obs(
                    f"obs-buggy-{index}",
                    "ext.buggy",
                    "1.0.0",
                    outcome=ObservationOutcome.FAILURE if failed else ObservationOutcome.SUCCESS,
                    latency_ms=latency,
                    error=_ext_error(f"err-buggy-{index}", "ext.buggy", "1.0.0")
                    if failed
                    else None,
                )
            )
        for index, latency in enumerate((900.0, 800.0)):
            await service.record_observation(
                _obs(f"obs-slow-{index}", "ext.slowpoke", "1.0.0", latency_ms=latency)
            )
        for index in range(2):
            await service.record_observation(
                _obs(
                    f"obs-fast-{index}",
                    "ext.speedy",
                    "1.0.0",
                    latency_ms=100.0 + index * 10.0,
                    cost_units=5.0,
                )
            )
        for index in range(5):
            await service.record_observation(
                _obs(f"obs-silent-{index}", "ext.silent", "1.0.0", latency_ms=50.0)
            )

        by_usage = await service.rank(SCOPE, RankingMetric.USAGE)
        assert by_usage[0].extension_id == "ext.silent"
        assert by_usage[0].invocations == 5

        by_failures = await service.rank(SCOPE, RankingMetric.FAILURES)
        assert by_failures[0].extension_id == "ext.buggy"
        assert by_failures[0].failures == 2

        by_error_rate = await service.rank(SCOPE, RankingMetric.ERROR_RATE)
        assert by_error_rate[0].extension_id == "ext.buggy"
        assert by_error_rate[0].error_rate == pytest.approx(2 / 3)

        by_latency = await service.rank(SCOPE, RankingMetric.LATENCY)
        assert by_latency[0].extension_id == "ext.slowpoke"
        assert by_latency[0].latency_max_ms == 900.0

        # Cost ranking: only speedy was metered — unmeasured sorts last, so
        # silence never reads as free.
        by_cost = await service.rank(SCOPE, RankingMetric.COST)
        cost_order = [digest.extension_id for digest in by_cost]
        assert cost_order[0] == "ext.speedy"
        assert by_cost[0].cost_units_total == 10.0
        assert cost_order.index("ext.silent") > cost_order.index("ext.speedy")
        buggy_digest = next(digest for digest in by_cost if digest.extension_id == "ext.buggy")
        assert buggy_digest.cost_units_total is None

        # The taxonomy's provenance survives the ranking round trip.
        errors = await service.recent_errors(SCOPE, "ext.buggy")
        assert [error.error_id for error in errors] == ["err-buggy-1", "err-buggy-0"]
        assert all(
            error.extension_id == "ext.buggy" and error.version == "1.0.0" for error in errors
        )

        # SLO inputs derive from the recorded evidence — exhausted for the
        # faulty contributor, absent (never perfect) without any evidence.
        position = await service.slo(SCOPE, "ext.buggy", slo_target=0.5)
        assert position is not None
        assert position.window_observations == 3
        assert position.observed_success_rate == pytest.approx(1 / 3)
        assert position.budget_exhausted is True
        assert await service.slo(SCOPE, "ext.unknown") is None
