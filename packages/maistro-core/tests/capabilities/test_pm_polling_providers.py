"""Coverage for maistro.capabilities.providers.pm_polling's refusal and error
paths (#1362 diff-coverage gate).

`test_pm_polling_nodes.py` drives these Providers end to end through the
graph nodes, but only along the configurations that actually reach a live
HTTP call: a matching provider name, a supported Jira flavor, a
credential-routed provider of the right concrete type, a request the
Provider recognizes, and a successful JSON response. Every refusal this
module can make before or after that call -- a Binding pinned to a different
vendor, an unsupported Jira flavor, a request routed to the wrong
provider/credential plumbing, a foreign request type, a dead connection, a
non-object response body -- was therefore never exercised. These tests call
`resolve_jira_provider`/`resolve_airtable_provider`/`execute_jira`/
`execute_airtable` directly so each refusal can be pinned without a full
Binding/Invocation round trip.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.credential_routing import CredentialBackedProvider
from maistro.capabilities.invocation import EffectNotApplied
from maistro.capabilities.providers.pm_polling import (
    AirtablePollRequest,
    AirtableProvider,
    JiraPollRequest,
    JiraProvider,
    execute_airtable,
    execute_jira,
    resolve_airtable_provider,
    resolve_jira_provider,
)
from maistro.capabilities.types import Unavailable
from maistro.credentials.types import CredentialRecord


def _binding(**overrides: Any) -> Binding:
    values: dict[str, Any] = {
        "binding_id": "binding-1",
        "workspace_id": "ws-1",
        "project_id": "project-1",
        "node_id": "node-1",
        "capability": "jira.search",
    }
    values.update(overrides)
    return Binding(**values)


def _credential_routed(base: Any) -> CredentialBackedProvider:
    return CredentialBackedProvider(
        base=base,
        credential=CredentialRecord(key_id="key-1", provider=base.name, api_key="secret"),
        workspace_id="ws-1",
        project_id="project-1",
    )


# --------------------------------------------------------------------------
# resolve_jira_provider / resolve_airtable_provider
# --------------------------------------------------------------------------


async def test_resolve_jira_provider_rejects_a_binding_pinned_to_another_provider() -> None:
    """A Binding naming a non-Jira provider must never resolve to a
    JiraProvider that would route Jira credentials/policy to it."""
    binding = _binding(provider_name="not-jira", config={"base_url": "https://jira.example.com"})

    result = await resolve_jira_provider(binding)

    assert isinstance(result, Unavailable)
    assert result.reason == "Binding pins unsupported Jira provider 'not-jira'"


async def test_resolve_jira_provider_rejects_an_unsupported_flavor() -> None:
    """Only `server`/`cloud` are recognized Jira API shapes; anything else
    must be refused rather than guessed at (the flavor picks the API path
    and the auth scheme in `execute_jira`)."""
    binding = _binding(
        config={"base_url": "https://jira.example.com", "flavor": "datacenter-legacy"}
    )

    result = await resolve_jira_provider(binding)

    assert isinstance(result, Unavailable)
    assert result.reason == "unsupported Jira flavor 'datacenter-legacy'"


async def test_resolve_airtable_provider_rejects_a_binding_pinned_to_another_provider() -> None:
    binding = _binding(capability="airtable.records", provider_name="not-airtable")

    result = await resolve_airtable_provider(binding)

    assert isinstance(result, Unavailable)
    assert result.reason == "Binding pins unsupported Airtable provider 'not-airtable'"


# --------------------------------------------------------------------------
# _provider_and_credential, exercised through execute_jira/execute_airtable
# --------------------------------------------------------------------------


async def test_execute_jira_rejects_a_provider_that_was_never_credential_routed() -> None:
    """Every real call path wraps the resolved Provider in
    `CredentialRouting` before it reaches an executor; a bare Provider here
    means that seam was skipped, and the secret-bearing request must not go
    out regardless."""
    provider = JiraProvider(base_url="https://jira.example.com", flavor="cloud", email=None,
                             capability="jira.search")

    with pytest.raises(TypeError, match="must be credential-routed"):
        await execute_jira(provider, JiraPollRequest(jql="x", max_results=1), timeout_s=1.0)


async def test_execute_jira_rejects_a_credential_routed_airtable_provider() -> None:
    """The Jira executor must refuse to run against a routed provider whose
    underlying implementation is some other vendor's -- a resolver/executor
    mismatch, not a Jira call with the wrong `base`."""
    provider = _credential_routed(AirtableProvider(base_url="https://api.airtable.com"))

    with pytest.raises(TypeError, match="unexpected implementation"):
        await execute_jira(provider, JiraPollRequest(jql="x", max_results=1), timeout_s=1.0)


# --------------------------------------------------------------------------
# execute_jira
# --------------------------------------------------------------------------


def _jira_provider(**overrides: Any) -> CredentialBackedProvider:
    defaults: dict[str, Any] = {
        "base_url": "https://jira.example.com",
        "flavor": "cloud",
        "email": "bot@example.com",
        "capability": "jira.search",
    }
    defaults.update(overrides)
    return _credential_routed(JiraProvider(**defaults))


async def test_execute_jira_rejects_a_foreign_request_type() -> None:
    """Neither the search nor the subtasks request -- a request built for a
    different capability module must not be dispatched as a Jira call just
    because it reached this executor."""
    provider = _jira_provider()

    with pytest.raises(TypeError, match="foreign request"):
        await execute_jira(provider, object(), timeout_s=1.0)


async def test_execute_jira_wraps_a_dead_connection_as_effect_not_applied(
    monkeypatch: Any,
) -> None:
    """A connection that never reached Jira means no effect happened --
    `EffectNotApplied`, not a bare connection error the retry machinery
    cannot distinguish from "maybe applied, maybe not"."""

    class DeadClient:
        is_closed = False

        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        async def __aenter__(self) -> DeadClient:
            return self

        async def __aexit__(self, *args: Any) -> None: ...

        async def get(self, *args: Any, **kwargs: Any) -> Any:
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "AsyncClient", DeadClient)
    provider = _jira_provider()

    with pytest.raises(EffectNotApplied, match="Jira unreachable"):
        await execute_jira(provider, JiraPollRequest(jql="x", max_results=1), timeout_s=1.0)


async def test_execute_jira_rejects_a_non_object_response_body(monkeypatch: Any) -> None:
    """Jira is contractually expected to answer a search with a JSON object;
    anything else (a bare list, a scalar) must not be handed to node output
    shaping as if it were one."""

    class Response:
        status_code = 200

        def json(self) -> Any:
            return ["not", "an", "object"]

    class Client:
        is_closed = False

        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *args: Any) -> None: ...

        async def get(self, *args: Any, **kwargs: Any) -> Response:
            return Response()

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    provider = _jira_provider()

    with pytest.raises(RuntimeError, match="non-object response body"):
        await execute_jira(provider, JiraPollRequest(jql="x", max_results=1), timeout_s=1.0)


# --------------------------------------------------------------------------
# execute_airtable
# --------------------------------------------------------------------------


def _airtable_provider() -> CredentialBackedProvider:
    return _credential_routed(AirtableProvider(base_url="https://api.airtable.com"))


async def test_execute_airtable_rejects_a_foreign_request_type() -> None:
    provider = _airtable_provider()

    with pytest.raises(TypeError, match="foreign request"):
        await execute_airtable(provider, object(), timeout_s=1.0)


async def test_execute_airtable_wraps_a_dead_connection_as_effect_not_applied(
    monkeypatch: Any,
) -> None:
    class DeadClient:
        is_closed = False

        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        async def __aenter__(self) -> DeadClient:
            return self

        async def __aexit__(self, *args: Any) -> None: ...

        async def get(self, *args: Any, **kwargs: Any) -> Any:
            raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx, "AsyncClient", DeadClient)
    provider = _airtable_provider()

    with pytest.raises(EffectNotApplied, match="Airtable unreachable"):
        await execute_airtable(
            provider, AirtablePollRequest(base_id="app-1", table="Work"), timeout_s=1.0
        )


async def test_execute_airtable_rejects_a_non_object_response_body(monkeypatch: Any) -> None:
    class Response:
        status_code = 200

        def json(self) -> Any:
            return [1, 2, 3]

    class Client:
        is_closed = False

        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *args: Any) -> None: ...

        async def get(self, *args: Any, **kwargs: Any) -> Response:
            return Response()

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    provider = _airtable_provider()

    with pytest.raises(RuntimeError, match="non-object response body"):
        await execute_airtable(
            provider, AirtablePollRequest(base_id="app-1", table="Work"), timeout_s=1.0
        )
