from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from maistro.agents.context_builder import ContextBuilder
from maistro.agents.intents import IntentRegistry
from maistro.classifier.engine import ClassifierEngine
from maistro.container import Container
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
    responses: list[dict[str, Any]]

    async def send_prompt(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        messages = [{"role": "user", "content": prompt}]
        result = await self.provider.complete(messages, **kwargs)
        self.responses.append(result)
        return result

    def get_last_response(self) -> dict[str, Any] | None:
        return self.responses[-1] if self.responses else None

    def reset(self) -> None:
        self.responses.clear()
        self.provider._responses.clear()
        self.provider.reset()


def create_test_environment(
    *,
    provider: FauxProvider | None = None,
    config: AgentConfig | None = None,
    agents: dict[str, Any] | None = None,
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

    return HarnessEnvironment(
        container=container,
        classifier=classifier,
        router=router,
        provider=provider,
        responses=[],
    )
