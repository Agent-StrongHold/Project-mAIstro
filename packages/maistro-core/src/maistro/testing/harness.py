from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from maistro.agents.context_builder import ContextBuilder
from maistro.agents.intents import IntentRegistry
from maistro.classifier.engine import ClassifierEngine
from maistro.container import Container
from maistro.graph.events import GraphEvent
from maistro.graph.run import GraphRun
from maistro.graph.types import (
    AgentRole,
    GraphConfig,
    GraphEdge,
    GraphTask,
    HyperagentOutput,
)
from maistro.memory.learnings.extractor import ToolCorrectionExtractor
from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.memory.outcomes import InMemoryOutcomeStore
from maistro.quota.tracker import InMemoryQuotaTracker
from maistro.router.selector import RouterEngine
from maistro.security._types import PermissionTable
from maistro.security.gate import Gate
from maistro.security.permission_policy import build_permission_table
from maistro.security.sentinel.audit import InMemoryAuditLog
from maistro.security.sentinel.policy import Sentinel
from maistro.security.strikes import InMemoryStrikeTracker
from maistro.security.warden.detector import Warden
from maistro.sessions.store import InMemorySessionStore
from maistro.testing.faux_provider import FauxProvider
from maistro.types.config import AgentConfig


@dataclass
class HarnessEnvironment:
    container: Container
    classifier: ClassifierEngine
    router: RouterEngine
    provider: FauxProvider
    graph_run: GraphRun
    events: list[GraphEvent] = field(default_factory=list)
    responses: list[dict[str, Any]] = field(default_factory=list)
    _event_filter: set[str] | None = field(default=None, repr=False)
    _graph_config: GraphConfig = field(default_factory=lambda: GraphConfig(nodes=[]), repr=False)

    async def send_prompt(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        messages = [{"role": "user", "content": prompt}]
        result = await self.provider.complete(messages, **kwargs)
        self.responses.append(result)
        return result

    def get_events(self, event_type: str | None = None) -> list[GraphEvent]:
        if event_type is None:
            return list(self.events)
        return [e for e in self.events if e.type == event_type]

    def get_last_response(self) -> dict[str, Any] | None:
        return self.responses[-1] if self.responses else None

    def assert_event_type(self, event_type: str, count: int = 1) -> list[GraphEvent]:
        matching = [e for e in self.events if e.type == event_type]
        actual = len(matching)
        if actual != count:
            raise AssertionError(f"Expected {count} events of type '{event_type}', got {actual}")
        return matching

    def reset(self) -> None:
        self.events.clear()
        self.responses.clear()
        self.provider._responses.clear()
        self.provider.reset()

    async def run_graph(self, **kwargs: Any) -> HyperagentOutput:
        task_description = kwargs.pop("task_description", "test task")
        # This is a test-harness default — the string is consumed by GraphTask
        # which never writes to it directly; sandbox writes are gated by
        # tools/sandbox/workspace.validate_workspace_path. False positive.
        workspace = kwargs.pop("workspace", "/tmp")  # nosec B108 — test fixture default, not a file op
        task = GraphTask(description=task_description, workspace=workspace)
        new_run = GraphRun(config=self._graph_config, task=task)
        env = self

        async def _capture(event: GraphEvent) -> None:
            if env._event_filter is None or event.type in env._event_filter:
                env.events.append(event)

        new_run.event_callbacks.append(_capture)
        self.graph_run = new_run
        return await new_run.start(llm_call=self.provider, **kwargs)


def create_test_environment(
    *,
    provider: FauxProvider | None = None,
    config: AgentConfig | None = None,
    agents: dict[str, Any] | None = None,
    graph_config: GraphConfig | None = None,
    event_filter: set[str] | None = None,
) -> HarnessEnvironment:
    if provider is None:
        provider = FauxProvider()
    if config is None:
        config = AgentConfig(router_api_key="test-key")

    warden = Warden()
    learning_extractor = ToolCorrectionExtractor()
    quota_tracker = InMemoryQuotaTracker()
    learning_store = InMemoryLearningStore()
    outcome_store = InMemoryOutcomeStore()
    session_store = InMemorySessionStore()

    router = RouterEngine(quota_tracker)
    classifier = ClassifierEngine()
    context_builder = ContextBuilder()
    intent_registry = IntentRegistry()
    # Mirror create_container's security wiring rather than hardcoding it.
    # This function accepts an AgentConfig and previously ignored its security
    # section entirely, so a test doing
    #   create_test_environment(config=AgentConfig(security=SecurityConfig(
    #       permission_preset="dangerous_tools_admin")))
    # silently observed an empty permission table and no strike tracker. That is
    # the same "second assembly path drifts from the real one" shape that let
    # the empty permission_table and missing strike_tracker survive a green
    # suite in the first place; a test harness that cannot reproduce the
    # container's security posture cannot catch a regression in it.
    strike_tracker: InMemoryStrikeTracker | None = None
    if config.security.strike_tracking_enabled:
        strike_tracker = InMemoryStrikeTracker()
    gate = Gate(warden=warden, strike_tracker=strike_tracker)

    audit_log = InMemoryAuditLog()
    permission_table: PermissionTable = build_permission_table(
        preset=config.security.permission_preset,
        permissions=config.security.permissions,
    )
    sentinel = Sentinel(
        warden=warden,
        permission_table=permission_table,
        audit_log=audit_log,
    )

    container = Container(
        config=config,
        router=router,
        classifier=classifier,
        quota_tracker=quota_tracker,
        learning_store=learning_store,
        learning_extractor=learning_extractor,
        outcome_store=outcome_store,
        session_store=session_store,
        warden=warden,
        gate=gate,
        strike_tracker=strike_tracker,
        sentinel=sentinel,
        context_builder=context_builder,
        intent_registry=intent_registry,
        audit_log=audit_log,
    )

    if agents:
        container.agents.update(agents)
        for name in agents:
            intent_registry.register(name, name)

    if graph_config is None:
        graph_config = GraphConfig(
            nodes=[AgentRole.PLANNER, AgentRole.CODER, AgentRole.REVIEWER],
            edges=[
                GraphEdge(from_role=AgentRole.PLANNER, to_role=AgentRole.CODER),
                GraphEdge(from_role=AgentRole.CODER, to_role=AgentRole.REVIEWER),
            ],
        )

    graph_run = GraphRun(config=graph_config)

    env = HarnessEnvironment(
        container=container,
        classifier=classifier,
        router=router,
        provider=provider,
        graph_run=graph_run,
        _event_filter=event_filter,
        _graph_config=graph_config,
    )

    async def _capture(event: GraphEvent) -> None:
        if event_filter is None or event.type in event_filter:
            env.events.append(event)

    graph_run.event_callbacks.append(_capture)

    return env
