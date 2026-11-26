"""Scope enforcement, secret boundaries, and upstream error normalization.

Acceptance criteria under test (issue #963):

- AC5: a connector cannot access undeclared Workspaces or secrets — the
  refusals come from the host before connector code runs, and the secret
  boundary only ever resolves descriptor-declared names;
- error normalization: raw ``httpx`` failures escaping a connector surface as
  the canonical error types, with the checkpoint untouched so a retry resumes
  from the same cursor.
"""

from __future__ import annotations

import httpx
import pytest

from connectors.connector_fixtures import Page, ScriptedConnector
from maistro.connectors import (
    ConnectorInstance,
    ConnectorRateLimitedError,
    ConnectorScopeError,
    ConnectorUnavailableError,
    MemoryCheckpointStore,
    MemoryIngestStore,
    SecretRef,
    SourceItem,
    StaticSecretAuthority,
    SyncEngine,
)

WORKSPACE = "ws-declared"
UNDECLARED_WORKSPACE = "ws-forbidden"


def _item(external_id: str) -> SourceItem:
    return SourceItem(source_id="repo", external_id=external_id, content="content", version="v1")


def _connector(**kwargs) -> ScriptedConnector:
    return ScriptedConnector({None: Page(items=(_item("doc-1"),), next_cursor=None)}, **kwargs)


def _instance(
    source: ScriptedConnector,
    *,
    workspaces: frozenset[str] | None = None,
    secrets: StaticSecretAuthority | None = None,
) -> ConnectorInstance:
    return ConnectorInstance(
        descriptor=source.descriptor,
        workspace_ids=workspaces or frozenset({WORKSPACE}),
        secrets=secrets,
    )


async def test_undeclared_workspace_is_refused_before_the_connector_runs():
    """AC5: the engine refuses an undeclared Workspace without invoking code."""
    source = _connector()
    engine = SyncEngine(MemoryIngestStore(), MemoryCheckpointStore())

    with pytest.raises(ConnectorScopeError, match=r"ws-forbidden"):
        await engine.run(source, _instance(source), workspace_id=UNDECLARED_WORKSPACE)


async def test_scope_refusal_leaves_no_records_and_no_checkpoint():
    """A refused sync is a no-op: nothing ingested, nothing persisted."""
    source = _connector()
    ingest = MemoryIngestStore()
    checkpoints = MemoryCheckpointStore()
    engine = SyncEngine(ingest, checkpoints)
    instance = _instance(source)

    with pytest.raises(ConnectorScopeError):
        await engine.run(source, instance, workspace_id=UNDECLARED_WORKSPACE)

    assert await ingest.records(UNDECLARED_WORKSPACE, "tests.scripted") == ()
    assert await checkpoints.load(UNDECLARED_WORKSPACE, "tests.scripted", "default") is None


async def test_undeclared_secret_name_is_refused():
    """AC5: resolution refuses names the descriptor never declared."""
    from maistro.connectors import ConnectorSession

    source = _connector(
        secret_refs=(SecretRef(name="api_token", description="Upstream API token"),)
    )
    bound = ConnectorSession.create(
        _instance(source, secrets=StaticSecretAuthority({(WORKSPACE, "api_token"): "hunter2"})),
        workspace_id=WORKSPACE,
        config_id="default",
        config={},
    )
    assert await bound.resolve_secret("api_token") == "hunter2"
    with pytest.raises(ConnectorScopeError, match=r"not declared"):
        await bound.resolve_secret("admin_password")


async def test_declared_but_unprovisioned_secret_raises_lookup_error():
    """A declared secret with no provisioned value is an operator gap, not a leak."""
    from maistro.connectors import ConnectorSession

    source = _connector(
        secret_refs=(SecretRef(name="api_token", description="Upstream API token"),)
    )
    bound = ConnectorSession.create(
        _instance(source, secrets=StaticSecretAuthority({})),
        workspace_id=WORKSPACE,
        config_id="default",
        config={},
    )

    with pytest.raises(LookupError):
        await bound.resolve_secret("api_token")


async def test_session_cannot_be_rescoped_to_another_workspace():
    """The session factory is the only binder, and it checks the allowlist."""
    from maistro.connectors import ConnectorSession

    source = _connector()
    instance = _instance(source)

    with pytest.raises(ConnectorScopeError, match=UNDECLARED_WORKSPACE):
        ConnectorSession.create(
            instance,
            workspace_id=UNDECLARED_WORKSPACE,
            config_id="default",
            config={},
        )


async def test_session_config_is_scoped_to_the_binding():
    """Config threading carries the binding's config_id, not a global."""
    from maistro.connectors import ConnectorSession

    source = _connector()
    bound = ConnectorSession.create(
        _instance(source),
        workspace_id=WORKSPACE,
        config_id="cfg-42",
        config={"feed": "https://example.test/rss"},
    )

    assert bound.config_id == "cfg-42"
    assert bound.config["feed"] == "https://example.test/rss"
    assert bound.workspace_id == WORKSPACE


class _UpstreamFailer(ScriptedConnector):
    """A connector whose upstream fails with a raw httpx exception."""

    def __init__(self, exc: Exception, **kwargs) -> None:
        super().__init__(**kwargs)
        self._exc = exc

    async def list_items(self, ctx):
        raise self._exc


def _http_429(retry_after: str | None) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://upstream.test/items")
    headers = {"Retry-After": retry_after} if retry_after else {}
    response = httpx.Response(429, headers=headers, request=request)
    return httpx.HTTPStatusError("too many requests", request=request, response=response)


def _engine_for(source) -> SyncEngine:
    return SyncEngine(MemoryIngestStore(), MemoryCheckpointStore())


async def test_raw_429_becomes_rate_limited_with_parsed_retry_after():
    """A raw upstream 429 surfaces as the canonical rate-limit error."""
    source = _UpstreamFailer(_http_429("30"), pages={None: Page(items=())})
    engine = _engine_for(source)

    with pytest.raises(ConnectorRateLimitedError, match=r"tests\.scripted") as excinfo:
        await engine.run(source, _instance(source), workspace_id=WORKSPACE)

    assert excinfo.value.retry_after == 30.0


async def test_429_without_retry_after_header_reports_none():
    source = _UpstreamFailer(_http_429(None), pages={None: Page(items=())})
    engine = _engine_for(source)

    with pytest.raises(ConnectorRateLimitedError) as excinfo:
        await engine.run(source, _instance(source), workspace_id=WORKSPACE)

    assert excinfo.value.retry_after is None


async def test_transport_failure_becomes_unavailable_error():
    source = _UpstreamFailer(httpx.ConnectError("connection refused"), pages={None: Page(items=())})
    engine = _engine_for(source)

    with pytest.raises(ConnectorUnavailableError, match=r"tests\.scripted"):
        await engine.run(source, _instance(source), workspace_id=WORKSPACE)


async def test_other_http_statuses_become_unavailable_error():
    request = httpx.Request("GET", "https://upstream.test/items")
    response = httpx.Response(503, request=request)
    source = _UpstreamFailer(
        httpx.HTTPStatusError("unavailable", request=request, response=response),
        pages={None: Page(items=())},
    )
    engine = _engine_for(source)

    with pytest.raises(ConnectorUnavailableError):
        await engine.run(source, _instance(source), workspace_id=WORKSPACE)


async def test_failed_sync_leaves_the_checkpoint_untouched():
    """A normalized failure must not advance the cursor past what it ingested."""
    inner = MemoryCheckpointStore()
    failing = _UpstreamFailer(
        httpx.ConnectError("connection refused"), pages={None: Page(items=())}
    )
    engine = SyncEngine(MemoryIngestStore(), inner)
    instance = _instance(failing)

    with pytest.raises(ConnectorUnavailableError):
        await engine.run(failing, instance, workspace_id=WORKSPACE)

    assert await inner.load(WORKSPACE, "tests.scripted", "default") is None


async def test_non_terminating_cursor_fails_closed_within_the_page_budget():
    """A cursor that never ends hits the page budget and fails loudly."""
    from maistro.connectors import ConnectorError

    looping = ScriptedConnector(
        {
            None: Page(items=(_item("doc-1"),), next_cursor="same"),
            "same": Page(items=(_item("doc-1"),), next_cursor="same"),
        }
    )
    engine = _engine_for(looping)

    with pytest.raises(ConnectorError, match="did not terminate"):
        await engine.run(looping, _instance(looping), workspace_id=WORKSPACE)
