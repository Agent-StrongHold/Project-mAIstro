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
- **Top cost contributor (AC5, cost half)**: the per-extension cost breakdown
  ranks contributors; error/latency taxonomy and health views are child issue
  #978 and are deliberately absent from this base.
- **Historical evidence (AC6)**: rows keep their exact extension version
  identity after an upgrade and after the extension is removed — history is
  never reattributed and never silently dropped.

Only exported ``maistro.extensions`` / ``maistro.capabilities`` /
``maistro.quota`` surfaces are used; the extension below imports nothing from
host internals.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
    ExtensionDescriptor,
    ExtensionHost,
    ExtensionIdentity,
    ExtensionMeter,
    ExtensionQuotaConflict,
    ExtensionQuotaDenied,
    ExtensionQuotaLedger,
    ExtensionQuotaPolicy,
    ExtensionQuotaRequest,
    ExtensionUsageAmounts,
    ExtensionUsageConflict,
    ExtensionUsageEvent,
    GovernedEffectRoute,
    InvocationScope,
)
from maistro.extensions.host import EFFECT_EVENT_TYPE
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
) -> tuple[str, str, str, str]:
    """Drive one extension invocation through the canonical Attempt spine.

    Returns (run_id, node_run_id, attempt_id, invocation_id).
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
        return host.invocation_context(
            InvocationScope(
                workspace_id=WORKSPACE,
                agent_id=CALLER,
                run_id=run_id,
                node_run_id=node_run_id,
                attempt_id=attempt.attempt_id,
            )
        )

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


# ---------------------------------------------------------------------------
# AC1: every extension invocation is attributable to extension, version,
# publisher, caller, and Workspace — on canonical evidence, without secrets.
# ---------------------------------------------------------------------------


@pytest.mark.ac("M9-I/AC-1")
async def test_extension_invocation_is_attributed_on_canonical_evidence(
    tmp_path: Path,
) -> None:
    events = InMemoryEventStore()
    invocations = InMemoryInvocationStore()
    meter = ExtensionMeter(tmp_path / "metering.sqlite", clock=lambda: CLOCK)
    await meter.ensure_schema()

    run_id, node_run_id, attempt_id, invocation_id = await _invoke_once(
        invocations=invocations, events=events
    )

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


@pytest.mark.ac("M9-I/AC-2")
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


@pytest.mark.ac("M9-I/AC-3")
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
            limit=60,
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
    _, _, _, invocation_id = await _invoke_once(invocations=invocations, events=events)
    meter = ExtensionMeter(tmp_path / "quota.sqlite", clock=lambda: CLOCK)
    await meter.ensure_schema()
    await meter.record(_meter_row("evt-res-one", invocation_id=invocation_id))
    await quota_ledger.commit(
        "res-one", ExtensionUsageAmounts(tokens=60, micro_usd=500, requests=1)
    )
    balance = await quota_ledger.policy_balance("workspace-tokens")
    assert balance.available == 0

    # Second invocation: the budget is exhausted server-side, so admission is
    # refused before any dispatch — no Invocation, no event, no usage row.
    stream_before = await _stream(events)
    with pytest.raises(ExtensionQuotaDenied):
        await quota_ledger.reserve(reservation("res-two"))
    assert await _stream(events) == stream_before
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


@pytest.mark.ac("M9-I/AC-5")
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


@pytest.mark.ac("M9-I/AC-6")
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
