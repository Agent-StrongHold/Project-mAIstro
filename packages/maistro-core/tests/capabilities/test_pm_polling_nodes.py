"""Governed Jira/Airtable graph-node egress tests for issue #1195."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import (
    CapabilityEffectContext,
    new_in_memory_effect_context,
)
from maistro.credentials.types import CredentialRecord
from maistro.graph.nodes import NodeContext
from maistro.graph.nodes.airtable_poll import AirtablePollNode
from maistro.graph.nodes.jira_poll import JiraPollNode
from maistro.graph.nodes.jira_wait_for_subtasks import JiraWaitForSubtasksNode


def _ctx(node_id: str = "n1", **overrides: Any) -> NodeContext:
    values: dict[str, Any] = {
        "run_id": "run-1",
        "dag_id": "graph-1",
        "node_id": node_id,
        "node_run_id": "node-run-1",
        "attempt_id": "attempt-1",
        "workspace_id": "ws-1",
        "project_id": "project-1",
    }
    values.update(overrides)
    return NodeContext(**values)


async def _effects(
    capability: str, *, config: dict[str, Any], provider: str
) -> CapabilityEffectContext:
    effects = new_in_memory_effect_context()
    binding = Binding(
        binding_id=f"{provider}-binding",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="n1",
        capability=capability,
        provider_name=provider,
        config=config,
        credential_refs=(f"{provider}-key",),
    )
    await effects.bindings.put(binding)
    # The key is held by the scoped CredentialRouter, never by node input.
    effects.credentials.add(
        workspace_id="ws-1",
        project_id="project-1",
        record=CredentialRecord(
            key_id=f"{provider}-key", provider=provider, api_key=f"secret-{provider}"
        ),
    )
    return effects


async def test_jira_poll_crosses_binding_and_invocation_without_secret_in_payload(
    monkeypatch: Any,
) -> None:
    effects = await _effects(
        "jira.search",
        config={"base_url": "https://jira.example.com", "flavor": "server"},
        provider="jira",
    )
    seen: dict[str, Any] = {}

    class Response:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "issues": [
                    {"key": "P-1", "fields": {"summary": "Ship", "status": {"name": "Done"}}}
                ]
            }

    class Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *args: Any) -> None: ...

        async def get(self, url: str, **kwargs: Any) -> Response:
            seen.update(url=url, **kwargs)
            return Response()

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    node = JiraPollNode(effect_context=effects)
    result = await node.run(
        {"binding_id": "jira-binding", "jql": "status = Done"},
        _ctx(),
    )

    assert result.success is True
    assert result.output.count == 1
    assert seen["headers"]["Authorization"] == "Bearer secret-jira"
    history = await effects.invocation_store.list_effect(
        run_id="run-1",
        node_run_id="node-run-1",
        binding_id="jira-binding",
        effect_key="jira.poll.search:status = Done:20:summary,status,updated,issuetype",
    )
    assert len(history) == 1
    assert history[0].binding.provider_name == "jira"
    assert "secret-jira" not in json.dumps(history[0].model_dump(mode="json"), default=str)
    assert "secret-jira" not in json.dumps(
        [vars(event) for event in effects.event_store._events_by_id.values()], default=str
    )


async def test_missing_binding_fails_before_airtable_http(monkeypatch: Any) -> None:
    effects = new_in_memory_effect_context()
    called = False

    class Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        async def __aenter__(self) -> Client:
            nonlocal called
            called = True
            return self

        async def __aexit__(self, *args: Any) -> None: ...

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    result = await AirtablePollNode(effect_context=effects).run(
        {"binding_id": "missing", "base_id": "app-1", "table": "Work"},
        _ctx(),
    )

    assert result.success is False
    assert result.error_code == "BindingNotFound"
    assert called is False


async def test_airtable_poll_is_governed_and_repeats_deduplicate(monkeypatch: Any) -> None:
    effects = await _effects(
        "airtable.records",
        config={},
        provider="airtable",
    )
    calls = 0

    class Response:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"records": [{"id": "rec-1", "fields": {"Name": "Alpha"}}]}

    class Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *args: Any) -> None: ...

        async def get(self, *args: Any, **kwargs: Any) -> Response:
            nonlocal calls
            calls += 1
            assert kwargs["headers"]["Authorization"] == "Bearer secret-airtable"
            return Response()

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    node = AirtablePollNode(effect_context=effects)
    inputs = {"binding_id": "airtable-binding", "base_id": "app-1", "table": "Work"}
    first = await node.run(inputs, _ctx())
    second = await node.run(inputs, _ctx(attempt_id="attempt-2"))

    assert first.success is True
    assert second.success is True
    assert calls == 1
    effects_history = await effects.invocation_store.list_effect(
        run_id="run-1",
        node_run_id="node-run-1",
        binding_id="airtable-binding",
        effect_key="airtable.poll.records:app-1:Work:",
    )
    assert len(effects_history) == 1


async def test_wait_poll_assigns_a_new_effect_key_to_each_resume(monkeypatch: Any) -> None:
    effects = await _effects(
        "jira.subtasks",
        config={"base_url": "https://jira.example.com", "flavor": "server"},
        provider="jira",
    )

    class Response:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "fields": {"subtasks": [{"key": "P-2", "fields": {"status": {"name": "Open"}}}]}
            }

    class Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *args: Any) -> None: ...

        async def get(self, *args: Any, **kwargs: Any) -> Response:
            return Response()

    Client.is_closed = False
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    node = JiraWaitForSubtasksNode(effect_context=effects)
    first = await node.run(
        {"binding_id": "jira-binding", "parent_key": "P-1", "poll_interval_seconds": 1},
        _ctx(),
    )
    assert first.status == "paused"
    second = await node.run(
        {"binding_id": "jira-binding", "parent_key": "P-1", "poll_interval_seconds": 1},
        _ctx(
            attempt_id="attempt-2",
            metadata={
                "resumed_pause": {
                    "first_seen": datetime.now(UTC).isoformat(),
                    "poll_number": 1,
                }
            },
        ),
    )
    assert second.status == "paused"
    history = await effects.invocation_store.list_effect(
        run_id="run-1",
        node_run_id="node-run-1",
        binding_id="jira-binding",
        effect_key="jira.wait_for_subtasks.status:P-1:0",
    )
    assert len(history) == 1
    history = await effects.invocation_store.list_effect(
        run_id="run-1",
        node_run_id="node-run-1",
        binding_id="jira-binding",
        effect_key="jira.wait_for_subtasks.status:P-1:1",
    )
    assert len(history) == 1


async def test_binding_without_endpoint_config_fails_before_http(monkeypatch: Any) -> None:
    effects = await _effects("jira.search", config={}, provider="jira")
    called = False

    class Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            nonlocal called
            called = True

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    result = await JiraPollNode(effect_context=effects).run(
        {"binding_id": "jira-binding", "jql": "status = Open"},
        _ctx(),
    )

    assert result.success is False
    assert result.error_code == "CapabilityUnavailable"
    assert called is False


async def test_unknown_http_outcome_blocks_a_repeated_poll(monkeypatch: Any) -> None:
    effects = await _effects("airtable.records", config={}, provider="airtable")
    calls = 0

    class Response:
        status_code = 500

        def json(self) -> dict[str, Any]:
            return {}

    class Client:
        is_closed = False

        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *args: Any) -> None: ...

        async def get(self, *args: Any, **kwargs: Any) -> Response:
            nonlocal calls
            calls += 1
            return Response()

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    node = AirtablePollNode(effect_context=effects)
    inputs = {"binding_id": "airtable-binding", "base_id": "app-1", "table": "Work"}
    first = await node.run(inputs, _ctx(run_id="unknown-poll"))
    second = await node.run(inputs, _ctx(run_id="unknown-poll", attempt_id="attempt-2"))

    assert first.error_code == "PollingHttpError"
    assert second.error_code == "UnsafeEffectRetry"
    assert calls == 1
