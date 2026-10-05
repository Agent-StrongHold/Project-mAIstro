"""A reference extension executes using only public extension-context objects.

The acceptance this suite pins (#950): an extension driven through the
canonical ``Graph → Run → NodeRun → Attempt`` execution —
``AttemptExecutionService`` over ``PythonExecutionRuntime`` — can activate,
invoke, report progress, and cross the governed capability seam with nothing
but ``maistro.extensions`` public objects; its authority-sensitive effect
produces a real canonical Invocation; cancellation through the canonical
Attempt fence reaches the extension; and provenance lands on the canonical
event stream. The extension below imports nothing from host internals.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.governed_invocation import (
    GovernedInvocationExecutionService,
    InvocationPolicyContext,
)
from maistro.capabilities.invocation import (
    InMemoryInvocationStore,
    InvocationExecutionService,
)
from maistro.events.envelope import EventEnvelope, InMemoryEventStore
from maistro.extensions import (
    EffectNotDeclared,
    EffectRoute,
    EventStoreProgressSink,
    ExtensionContext,
    ExtensionContractError,
    ExtensionDescriptor,
    ExtensionHost,
    ExtensionIdentity,
    ExtensionLifecycleError,
    GovernedEffectRoute,
    InvocationScope,
    ScopeMismatch,
)
from maistro.graph import Graph, Node
from maistro.policy.types import Decision, PolicyVerdict
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.concurrency import RunConcurrencyLimits
from maistro.runs.execution import AttemptExecutionService
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.runtime import PythonExecutionRuntime
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

pytestmark = pytest.mark.contract("behavioral")

WORKSPACE = "extension-ws"
PROJECT = "extension-project"


class ReferenceGreeter:
    """The reference extension: public SDK objects only, end to end.

    Its invoke() reports progress, reads declared configuration, calls its
    one granted service, and crosses its one declared governed effect.
    """

    def __init__(self) -> None:
        self.activated: str | None = None
        self.deactivated = False
        self.saw_cancellation = False
        self.result: dict[str, Any] | None = None

    async def activate(self, context: ExtensionContext) -> None:
        self.activated = context.scope.workspace_id

    async def invoke(self, context: ExtensionContext) -> dict[str, Any]:
        await context.report_progress("greeting", percent=10.0)
        politeness = context.config["politeness"]
        clock = context.service("clock")
        receipt = await context.invoke_effect("echo", {"greeting": politeness})
        self.result = {
            "politeness": politeness,
            "clock": clock,
            "invocation_id": receipt.invocation_id,
            "effect": receipt.result,
        }
        return self.result

    async def deactivate(self, context: ExtensionContext) -> None:
        self.deactivated = True


class _EchoProvider:
    name = "reference-provider"
    # ResolvedBinding.from_provider requires the resolved slot to match the
    # Binding capability — the same rule any production provider satisfies.
    slot = "ext.reference.echo"
    trust_tier = "trusted"


def _governed_route(
    *,
    effect_key: str,
    events: InMemoryEventStore,
    invocations: InMemoryInvocationStore,
) -> GovernedEffectRoute:
    """Host-side wiring of one declared effect across the governed seam."""

    async def allow_policy(
        _binding: Binding,
        _request: Any,
        _context: InvocationPolicyContext,
    ) -> PolicyVerdict:
        return PolicyVerdict(
            Decision.ALLOW,
            reason="reference extension effect",
            rule="test.reference-allow",
        )

    async def _resolver(_binding: Binding) -> _EchoProvider:
        return _EchoProvider()

    async def _executor(_provider: _EchoProvider, request: Any) -> dict[str, Any]:
        return {"echoed": request}

    governed = GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(store=invocations),
        event_store=events,
        policy_evaluator=allow_policy,
    )
    return GovernedEffectRoute(
        effect_key=effect_key,
        binding=Binding(
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            capability="ext.reference.echo",
        ),
        invocations=governed,
        resolver=_resolver,
        executor=_executor,
    )


@pytest.fixture
async def host_with_route() -> Any:
    """Host + governed route + canonical stores over the reference extension."""
    events = InMemoryEventStore()
    invocations = InMemoryInvocationStore()
    descriptor = ExtensionDescriptor(
        identity=ExtensionIdentity(extension_id="reference.greeter", version="0.1.0"),
        config_keys=frozenset({"politeness"}),
        services=frozenset({"clock"}),
        effects=frozenset({"echo"}),
    )
    host = ExtensionHost(
        descriptor=descriptor,
        config_values={"politeness": "warm", "api_key": "host-only"},
        service_grants={"clock": "wall-clock"},
        effect_routes={
            "echo": _governed_route(effect_key="echo", events=events, invocations=invocations)
        },
        progress_sink=EventStoreProgressSink(events),
        events=events,
    )
    return host, events, invocations


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
        name="Reference extension execution",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    node_run = await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    node_run = await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    return run.run_id, node_run.node_run_id


def _extension_scope(
    run_id: str,
    node_run_id: str,
    attempt: Any,
) -> InvocationScope:
    return InvocationScope(
        workspace_id=WORKSPACE,
        agent_id="agent-1",
        run_id=run_id,
        node_run_id=node_run_id,
        attempt_id=attempt.attempt_id,
    )


async def test_reference_extension_executes_through_canonical_attempt(
    host_with_route: Any,
) -> None:
    host, events, invocations = host_with_route
    store, workspace_id, project_id = await _spine()
    run_id, node_run_id = await _running_node_run(store, workspace_id, project_id)
    extension = ReferenceGreeter()

    activation = host.activation_context(workspace_id=workspace_id, agent_id="agent-1")
    await host.activate(extension, activation)

    def context_factory(attempt: Any, _execution_context: Any) -> Any:
        return host.invocation_context(_extension_scope(run_id, node_run_id, attempt))

    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())
    terminal = await service.execute(
        node_run_id,
        None,
        None,
        executor=lambda _work, context: host.invoke(extension, context),
        context_factory=context_factory,
    )
    await host.deactivate(extension, activation)

    # The Attempt is the lifecycle truth; the extension result rode inside it.
    assert terminal.status is AttemptStatus.COMPLETED
    assert extension.activated == workspace_id
    assert extension.deactivated is True
    assert extension.result is not None
    node_run = await store.get_node_run(node_run_id)
    assert node_run is not None and node_run.status is RunStatus.COMPLETED

    # The effect crossed the governed seam: a real canonical Invocation was
    # persisted with full run/node-run/attempt correlation.
    stored = await invocations.get(extension.result["invocation_id"])
    assert stored is not None
    assert stored.run_id == run_id
    assert stored.node_run_id == node_run_id
    assert stored.attempt_id == terminal.attempt_id
    assert stored.effect_key == "echo"
    assert stored.status.value == "completed"
    assert stored.result == {"echoed": {"greeting": "warm"}}

    # Provenance flows through the canonical envelope: extension identity in
    # the provenance field, Attempt correlation on the envelope itself.
    stream = await events.list_stream(f"workspace:{workspace_id}")
    effect_events = [e for e in stream if e.type == "extension.effect.invoked"]
    assert len(effect_events) == 1
    effect_event: EventEnvelope = effect_events[0]
    assert effect_event.provenance == {
        "extension_id": "reference.greeter",
        "extension_version": "0.1.0",
    }
    assert effect_event.run_id == run_id
    assert effect_event.node_run_id == node_run_id
    assert effect_event.attempt_id == terminal.attempt_id
    assert effect_event.invocation_id == stored.invocation_id

    # The capability plane's own policy event correlates the same Attempt.
    policy_events = [e for e in stream if e.type == "capability.invocation.policy_decision"]
    assert policy_events and policy_events[0].attempt_id == terminal.attempt_id

    # Progress flowed through the canonical event stream too.
    progress_events = [e for e in stream if e.type == "extension.progress"]
    assert len(progress_events) == 1
    assert progress_events[0].payload["message"] == "greeting"
    assert progress_events[0].payload["percent"] == 10.0
    assert progress_events[0].provenance["extension_id"] == "reference.greeter"
    assert progress_events[0].attempt_id == terminal.attempt_id

    # Declared configuration reached the extension; the undeclared host value
    # is dropped at composition, so it never travels with the context — not
    # even in the context's private storage.
    assert extension.result["politeness"] == "warm"
    assert "api_key" not in host.descriptor.config_keys
    assert "api_key" not in host._config_values
    with pytest.raises(Exception, match="not declared"):
        activation = host.activation_context(workspace_id=workspace_id, agent_id="agent-1")
        activation.config["api_key"]
    assert "api_key" not in activation.config._values
    assert extension.result["clock"] == "wall-clock"


async def test_reference_extension_effect_requires_canonical_invocation_path(
    host_with_route: Any,
) -> None:
    """An undeclared effect has no dispatch path, even with a route granted."""
    host, _events, _invocations = host_with_route
    scope = InvocationScope(
        workspace_id=WORKSPACE,
        agent_id="agent-1",
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-1",
    )
    context = host.invocation_context(scope)
    with pytest.raises(EffectNotDeclared):
        await context.invoke_effect("undeclared-effect", {"value": 1})


async def test_governed_route_refuses_dispatch_outside_an_attempt(
    host_with_route: Any,
) -> None:
    """Activation scopes carry no Attempt, so no effect can dispatch from one."""
    host, _events, _invocations = host_with_route
    activation = host.activation_context(workspace_id=WORKSPACE, agent_id="agent-1")
    # Host wiring is host-side; the test reads it the way the host runtime
    # would when composing the route map.
    route: EffectRoute = host._effect_routes["echo"]

    class _EffectTryingLifecycle:
        async def activate(self, context: ExtensionContext) -> None:
            await context.invoke_effect("echo", {})

        async def invoke(self, context: ExtensionContext) -> None: ...

        async def deactivate(self, context: ExtensionContext) -> None: ...

    # The hook refusal surfaces attributed to the extension that raised it,
    # with the contract refusal preserved as the cause.
    with pytest.raises(ExtensionLifecycleError, match=r"reference\.greeter.*activate") as exc_info:
        await host.activate(_EffectTryingLifecycle(), activation)
    assert isinstance(exc_info.value.__cause__, EffectNotDeclared)
    assert "outside an Attempt" in str(exc_info.value.__cause__)
    with pytest.raises(EffectNotDeclared, match="outside an Attempt"):
        await route.dispatch(scope=activation.scope, request={})


async def test_governed_route_refuses_cross_workspace_dispatch(
    host_with_route: Any,
) -> None:
    """A scope from another workspace can never spend this route's binding.

    The governed service derives the Invocation and its policy events from the
    binding while provenance follows the scope, so a mismatched pair would
    spend one workspace's authorization and split the audit trail across
    tenants. The route must refuse before invoking.
    """
    host, events, invocations = host_with_route
    route: EffectRoute = host._effect_routes["echo"]
    foreign_scope = InvocationScope(
        workspace_id="other-workspace",
        agent_id="agent-1",
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-1",
    )
    with pytest.raises(ScopeMismatch, match="other-workspace"):
        await route.dispatch(scope=foreign_scope, request={"value": 1})
    # Nothing crossed the seam: no Invocation settled and no effect event
    # landed on either workspace's stream.
    binding = host._effect_routes["echo"]._binding
    assert (
        await invocations.list_effect(
            run_id="run-1",
            node_run_id="node-run-1",
            binding_id=binding.binding_id,
            effect_key="echo",
        )
        == []
    )
    assert await events.list_stream("workspace:other-workspace") == []


async def test_cancellation_through_attempt_fence_reaches_the_extension(
    host_with_route: Any,
) -> None:
    """service.cancel(attempt_id) is what the extension's view observes."""
    host, _events, _invocations = host_with_route
    store, workspace_id, project_id = await _spine()
    run_id, node_run_id = await _running_node_run(store, workspace_id, project_id)
    extension = ReferenceGreeter()
    progress_worked = asyncio.Event()

    class WaitingLifecycle:
        async def activate(self, context: ExtensionContext) -> None: ...

        async def invoke(self, context: ExtensionContext) -> None:
            await context.report_progress("waiting")
            progress_worked.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                # Evidence-keeping shape: observe the view, then re-raise so
                # the canonical fence records the cancellation untouched.
                extension.saw_cancellation = context.cancellation.cancelled()
                raise

        async def deactivate(self, context: ExtensionContext) -> None: ...

    lifecycle = WaitingLifecycle()

    def context_factory(attempt: Any, _execution_context: Any) -> Any:
        return host.invocation_context(_extension_scope(run_id, node_run_id, attempt))

    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())
    task = asyncio.create_task(
        service.execute(
            node_run_id,
            None,
            None,
            executor=lambda _work, context: lifecycle.invoke(context),
            context_factory=context_factory,
        )
    )
    await progress_worked.wait()
    attempts = await store.list_attempts(node_run_id)
    attempt_id = attempts[-1].attempt_id

    assert await service.cancel(attempt_id) is True
    with pytest.raises(asyncio.CancelledError):
        await task

    assert extension.saw_cancellation is True
    attempts = await store.list_attempts(node_run_id)
    # The Attempt is CANCELLED — the canonical fence settled it (#230). The
    # cause field itself is staged unknown on the model (#1884); the request
    # evidence lives in the recovery-events plane, not on the executor path.
    assert attempts[-1].status is AttemptStatus.CANCELLED
    node_run = await store.get_node_run(node_run_id)
    run = await store.get_run(run_id)
    assert node_run is not None and node_run.status is RunStatus.CANCELLED
    assert run is not None and run.status is RunStatus.CANCELLED


async def test_progress_without_sink_is_a_loud_refusal() -> None:
    """A host that granted no progress sink fails the report, not silently."""
    store, workspace_id, project_id = await _spine()
    run_id, node_run_id = await _running_node_run(store, workspace_id, project_id)
    refusals: list[str] = []
    host = ExtensionHost(
        descriptor=ExtensionDescriptor(
            identity=ExtensionIdentity(extension_id="reference.greeter", version="0.1.0"),
        ),
    )

    class _ReportingLifecycle:
        async def activate(self, context: ExtensionContext) -> None: ...

        async def invoke(self, context: ExtensionContext) -> None:
            try:
                await context.report_progress("invisible")
            except ExtensionContractError as exc:
                refusals.append(str(exc))

        async def deactivate(self, context: ExtensionContext) -> None: ...

    lifecycle = _ReportingLifecycle()

    def context_factory(attempt: Any, _execution_context: Any) -> Any:
        return host.invocation_context(_extension_scope(run_id, node_run_id, attempt))

    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())
    terminal = await service.execute(
        node_run_id,
        None,
        None,
        executor=lambda _work, context: lifecycle.invoke(context),
        context_factory=context_factory,
    )
    assert terminal.status is AttemptStatus.COMPLETED
    assert refusals and "no progress sink" in refusals[0]
    del workspace_id
